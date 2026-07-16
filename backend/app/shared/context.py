"""SharedContext — the single source of truth for one audit run.

Produced by Preprocessing, consumed by every Audit Engine. It carries the
**Engine Input Contract** of Document 2 §6.1 — ``ai_output``, ``prompt``,
``reference_source``, and (via the orchestrator) ``prior_audit_results`` — and
owns every derivation of that input that more than one engine needs.

**Why it exists.** Eight engines read the same content in three waves, and
several need the same derivations from it. Without one shared object, each would
recompute: the same text segmented three times, the same reference document
chunked twice, the same sentences embedded twice. Worse than the cost, they
could *disagree* — two engines reporting different sentence counts for one
document is a report nobody can defend.

**Two caching tiers, chosen by cost.**

* **Lazy properties** (:attr:`sentences`, :attr:`paragraphs`, :attr:`statistics`,
  :attr:`metadata`) — pure CPU, milliseconds, no IO. Computed on first access
  and memoized. They are synchronous, so within one event loop no two engines
  can interleave mid-computation and no lock is needed.
* :meth:`get_or_compute` — anything expensive or IO-bound (embeddings, chunking,
  fetching). Async, with a per-key lock, because engines in the same wave
  genuinely race for these.

Using the async path for a regex split would add lock overhead to something that
costs less than the lock; using the sync path for a network fetch would block the
loop that six engines are running on. Hence two tiers rather than one.

**What it deliberately does not do: evaluate.** Document 4 §5 forbids
preprocessing from evaluating anything, and Document 2 assigns every judgment to
a specific engine's frozen stage. So the rule this object is built to:

    Deriving *what the text is* — its sentences, its word count, its detected
    language — is infrastructure, identical for every engine, and lives here.
    Deciding *whether that is any good* is a frozen pipeline stage and lives in
    the engine.

Novelty still performs "Text Segmentation" at its stage 2; it reads
:attr:`sentences` instead of carrying its own splitter. Relevance still performs
its "Deterministic Constraint Checks" at stage 7; it reads :attr:`metadata`
rather than re-detecting the language. Reuse of a mechanism is not relocation of
a stage — that distinction is what keeps this object spec-compliant.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

from app.core.logging import bind, get_logger
from app.shared.document_analysis import (
    DocumentMetadata,
    DocumentStatistics,
    analyze_metadata,
    analyze_statistics,
)
from app.shared.schemas import InputType, PreprocessedContent
from app.shared.text_segmentation import TextSegmenter, TextSpan

__all__ = ["SharedContext", "SharedKeys"]

logger = get_logger(__name__)

T = TypeVar("T")


class SharedKeys:
    """Canonical keys for derivations more than one engine needs.

    Constants rather than string literals, because :meth:`SharedContext.get_or_compute`
    keys on exact match: two engines reaching for the same derivation under
    ``"extracted_claims"`` and ``"claims_extracted"`` would each compute it and
    each pay for an LLM call, and nothing would report the waste.

    They live here rather than in an engine so that sharing a derivation never
    means importing one engine from another — Document 2 §8 permits exactly two
    cross-engine inputs, and both flow through the orchestrator. An import for a
    cache key would be a dependency the specification does not allow.
    """

    #: Claims extracted from the AI Output. Accuracy needs them for
    #: verification (§7.2, stage 2); Credibility needs them to map citations
    #: against (§7.4, stage 3). Both run in wave 1, so the per-key lock is what
    #: makes this one call instead of two.
    EXTRACTED_CLAIMS = "extracted_claims"

    #: The reference document, chunked for similarity retrieval. Accuracy uses
    #: it for reference-first evidence retrieval (§7.2, stage 5).
    REFERENCE_CHUNKS = "reference_chunks"


@dataclass
class SharedContext:
    """The normalized content, its derivations, and a shared derivation store.

    One instance per audit. Built by Preprocessing (``input_router``) and passed
    by the orchestrator to every engine's ``_execute`` — the *same* instance, so
    a derivation paid for by one engine is free for the next.

    Attributes:
        audit_id: The run this context belongs to. Correlates logs and keeps one
            run's derivations from leaking into another's.
        content: The normalized content — the Engine Input Contract of
            Document 2 §6.1.

    Example:
        Reading a lazily derived view of the AI Output::

            for sentence in context.sentences:
                ...  # sentence.text, sentence.start, sentence.end

        Sharing an expensive derivation across engines::

            chunks = await context.get_or_compute(
                "reference_chunks",
                lambda: retrieval.chunk(context.reference_source),
            )

        Accuracy and Coverage both want the reference document chunked, and they
        run in the same parallel wave. The per-key lock means whichever arrives
        first pays and the other gets it free.

    Note:
        Run-scoped and single-loop. The async store is guarded by asyncio locks
        because engines in a wave genuinely race; nothing here is thread-safe,
        which is fine — the orchestrator uses tasks, not threads.
    """

    audit_id: str
    content: PreprocessedContent
    _segmenter: TextSegmenter = field(default_factory=TextSegmenter, repr=False)
    _derived: dict[str, Any] = field(default_factory=dict, repr=False)
    _artifacts: dict[str, Any] = field(default_factory=dict, repr=False)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)
    _guard: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # -- Engine Input Contract passthroughs (Document 2, §6.1) -------------- #

    @property
    def ai_output(self) -> str:
        """The AI-generated content under audit. Used by all engines."""
        return self.content.ai_output

    @property
    def prompt(self) -> str | None:
        """The user's original instruction. Used by Relevance, Engagement, Diversity."""
        return self.content.prompt

    @property
    def reference_source(self) -> str | None:
        """Ground truth. Optional for Accuracy; required for Coverage to score."""
        return self.content.reference_source

    @property
    def options(self) -> dict[str, Any]:
        """Request flags, e.g. ``external_retrieval``."""
        return self.content.options

    @property
    def input_type(self) -> InputType:
        """How the content arrived."""
        return self.content.input_type

    @property
    def source_uri(self) -> str | None:
        """The original URL or filename, when applicable."""
        return self.content.source_uri

    @property
    def has_prompt(self) -> bool:
        """Whether a prompt was supplied.

        Relevance, Engagement, and Diversity measure against stated intent.
        Without it they have nothing to compare to, and each decides for itself
        what that means for its own result.
        """
        return bool(self.prompt and self.prompt.strip())

    @property
    def has_reference_source(self) -> bool:
        """Whether ground truth was supplied.

        **Coverage requires it in order to score** (Document 2, §6.1). Accuracy
        treats it as optional but consults it first (§7.2, stage 5).
        """
        return bool(self.reference_source and self.reference_source.strip())

    # -- Lazy derivations of the AI Output ---------------------------------- #

    def _memo(self, key: str, factory: Callable[[], T]) -> T:
        """Memoize a synchronous derivation.

        No lock: this never awaits, so on a single event loop it is atomic. An
        async caller cannot observe a half-built value.
        """
        if key not in self._derived:
            self._derived[key] = factory()
        return self._derived[key]

    @property
    def paragraphs(self) -> tuple[TextSpan, ...]:
        """Paragraph spans of the AI Output, computed once per run."""
        return self._memo(
            "paragraphs", lambda: self._segmenter.paragraphs(self.ai_output)
        )

    @property
    def sentences(self) -> tuple[TextSpan, ...]:
        """Sentence spans of the AI Output, computed once per run.

        The shared basis for Novelty's stage 2 segmentation, Relevance's scope
        drift detection, and Readability's structural analysis. Every span
        carries source offsets, so any engine can turn one into locatable
        evidence.
        """
        return self._memo("sentences", lambda: self._segmenter.segment(self.ai_output))

    @property
    def sentences_by_paragraph(self) -> tuple[tuple[TextSpan, ...], ...]:
        """Sentence spans grouped by paragraph, for structure-aware stages."""
        return self._memo(
            "sentences_by_paragraph",
            lambda: self._segmenter.sentences_by_paragraph(self.ai_output),
        )

    @property
    def statistics(self) -> DocumentStatistics:
        """Size and shape measurements of the AI Output.

        Facts, not judgments — see :mod:`app.shared.document_analysis`.
        """
        return self._memo(
            "statistics",
            lambda: analyze_statistics(self.ai_output, self.sentences, self.paragraphs),
        )

    @property
    def metadata(self) -> DocumentMetadata:
        """Title, detected language, format, and citation markers of the AI Output.

        Carries the extraction provenance forward in ``metadata.extra``, so a
        surprising report can be traced back to which extractor produced the
        text.
        """
        return self._memo(
            "metadata",
            lambda: analyze_metadata(self.ai_output, self.content.extraction_metadata),
        )

    # -- Lazy derivations of the reference source --------------------------- #

    @property
    def reference_paragraphs(self) -> tuple[TextSpan, ...]:
        """Paragraph spans of the reference source. Empty when none was supplied."""
        if not self.has_reference_source:
            return ()
        return self._memo(
            "reference_paragraphs",
            lambda: self._segmenter.paragraphs(self.reference_source or ""),
        )

    @property
    def reference_sentences(self) -> tuple[TextSpan, ...]:
        """Sentence spans of the reference source. Empty when none was supplied.

        The basis for Coverage's key-point extraction and Accuracy's
        reference-first evidence retrieval.
        """
        if not self.has_reference_source:
            return ()
        return self._memo(
            "reference_sentences",
            lambda: self._segmenter.segment(self.reference_source or ""),
        )

    @property
    def reference_statistics(self) -> DocumentStatistics | None:
        """Measurements of the reference source, or ``None`` when absent."""
        if not self.has_reference_source:
            return None
        return self._memo(
            "reference_statistics",
            lambda: analyze_statistics(
                self.reference_source or "",
                self.reference_sentences,
                self.reference_paragraphs,
            ),
        )

    # -- Lazy derivations of the prompt ------------------------------------- #

    @property
    def prompt_sentences(self) -> tuple[TextSpan, ...]:
        """Sentence spans of the prompt. Empty when none was supplied.

        The basis for Relevance's requirement extraction.
        """
        if not self.has_prompt:
            return ()
        return self._memo(
            "prompt_sentences", lambda: self._segmenter.segment(self.prompt or "")
        )

    # -- Shared async derivation store -------------------------------------- #

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[T] | T]
    ) -> T:
        """Return the artifact at ``key``, computing it once if absent.

        The async tier, for derivations too expensive or too IO-bound for a lazy
        property: embeddings, reference chunks, fetched sources.

        The per-key lock is the point. Six engines run concurrently in wave 1; a
        plain check-then-set would let two of them both miss and both compute. A
        single global lock would avoid that but serialize every derivation across
        the wave, undoing the concurrency the orchestrator exists to provide — so
        locks are per key.

        Args:
            key: Stable name for the derivation, e.g. ``"reference_chunks"``.
                Distinct derivations must use distinct keys; a collision returns
                the wrong object with no error, so prefix by concern when in
                doubt.
            factory: Produces the artifact. May be sync or async. Called at most
                once per key per run.

        Returns:
            The cached or freshly computed artifact.

        Raises:
            Exception: Whatever ``factory`` raises, propagated to the caller.
                Nothing is cached on failure, so a later engine may retry — the
                caller decides whether a failed derivation degrades its
                dimension (Document 4, §12).
        """
        if key in self._artifacts:
            return self._artifacts[key]

        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            # Re-check: another task may have computed this while we waited.
            if key in self._artifacts:
                return self._artifacts[key]

            result = factory()
            if isinstance(result, Awaitable):
                result = await result

            self._artifacts[key] = result
            logger.debug(
                "shared artifact computed",
                extra=bind(audit_id=self.audit_id, artifact=key),
            )
            return result  # type: ignore[return-value]

    def peek(self, key: str) -> Any | None:
        """Return an async artifact if already computed, without computing it.

        For an engine that can use a derivation opportunistically but has a
        cheaper path when it is absent.
        """
        return self._artifacts.get(key)

    @property
    def artifact_keys(self) -> tuple[str, ...]:
        """Names of the async derivations computed so far, sorted. For debugging."""
        return tuple(sorted(self._artifacts))

    @property
    def derived_keys(self) -> tuple[str, ...]:
        """Names of the lazy properties computed so far, sorted. For debugging."""
        return tuple(sorted(self._derived))

    def describe(self) -> dict[str, Any]:
        """Summarize the run for structured logging.

        Ids and measurements only — never the content itself. Document 4 §12
        restricts logs to ids because the text under audit is the user's, and it
        belongs in the report rather than in an aggregator.

        **Forces no expensive derivation.** Segmentation and statistics are
        regex-cheap, so they are computed. ``language`` is reported only if
        :attr:`metadata` has *already* been derived by something that actually
        needed it — because language detection is the one derivation here that
        costs real time, and a log line has no business paying for it. Logging
        that silently triggered work would make the laziness this class is built
        around a fiction.
        """
        stats = self.statistics
        summary: dict[str, Any] = {
            "audit_id": self.audit_id,
            "content_id": self.content.content_id,
            "input_type": self.input_type.value,
            "word_count": stats.word_count,
            "sentence_count": stats.sentence_count,
            "paragraph_count": stats.paragraph_count,
            "has_prompt": self.has_prompt,
            "has_reference_source": self.has_reference_source,
        }
        if "metadata" in self._derived:
            summary["language"] = self.metadata.language
        return summary

    @classmethod
    def build(cls, audit_id: str, content: PreprocessedContent) -> "SharedContext":
        """Wrap normalized content into a context for one run.

        The single constructor Preprocessing uses. Nothing is derived here —
        every derivation is lazy, so an audit that needs no reference sentences
        never pays to segment the reference document.

        Args:
            audit_id: The run's id.
            content: The normalized content.

        Returns:
            A context ready to hand to the orchestrator.
        """
        return cls(audit_id=audit_id, content=content)
