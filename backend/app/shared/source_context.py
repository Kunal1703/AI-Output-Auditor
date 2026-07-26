"""SourceContext — the per-audit, shared view of the ground-truth source.

The AI Output Auditor audits one mandatory **source article** against one or
more outputs, each independently. Every output's pipeline needs the same
source-side derivations — the source's sentences, its key-points and their
salience, its numeric ledger, its embeddings — so computing them once per audit
and sharing them across all N outputs is essential to the token budget
(Software Architecture D3: two context tiers, ``SourceContext`` per audit and
``OutputContext`` per output).

This is the *source* tier. It mirrors the legacy :class:`~app.shared.context.SharedContext`
two-tier caching design — synchronous lazy properties for cheap CPU derivations
(segmentation, statistics, metadata) and an async :meth:`get_or_compute` store
with per-key locks for anything expensive or IO-bound (embeddings, key-point
extraction, in MB2) — but is scoped to the source alone and is immutable input
shared across every :class:`~app.shared.output_context.OutputContext` built
against it.

**MB1 scope.** The container, the sync text derivations, and the shared async
store are complete. The expensive source derivations (key-points + salience,
numeric ledger, embeddings) are computed by the Attribution substrate and Layer
metrics in MB2; their cache keys are declared in :class:`SourceKeys` so the
producers and consumers agree on one name.

**It does not evaluate.** Deriving *what the source is* is infrastructure and
lives here; deciding *whether an output matches it* is a metric and lives in an
evaluator (MB2).
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
from app.shared.schemas import SourceMeta
from app.shared.text_segmentation import TextSegmenter, TextSpan

__all__ = ["SourceContext", "SourceKeys"]

logger = get_logger(__name__)

T = TypeVar("T")


class SourceKeys:
    """Canonical cache keys for source derivations more than one output needs.

    Constants rather than string literals so two consumers reaching for the same
    derivation cannot key it under two spellings and each pay for it. Declared
    here in MB1 so the MB2 producers (Attribution, Coverage) and consumers agree
    on one name; the artifacts themselves are computed in MB2.
    """

    #: Embeddings of the source sentences, for retrieval of candidate spans.
    SOURCE_EMBEDDINGS = "source_embeddings"

    #: Source key-points with salience (Coverage §7.3 / KeyPointExtraction +
    #: SalienceAssigner), shared across every output's Coverage check.
    KEY_POINTS = "source_key_points"

    #: The source numeric/entity ledger (Factual & Numeric Accuracy).
    NUMERIC_LEDGER = "source_numeric_ledger"


@dataclass
class SourceContext:
    """The normalized source article, its derivations, and a shared store.

    One instance per audit, shared (read-only) by every output's
    :class:`~app.shared.output_context.OutputContext`.

    Attributes:
        audit_id: The run this context belongs to; correlates logs and keeps one
            run's derivations from leaking into another's.
        text: The source article text, exactly as submitted.
        source_uri: The original URL or filename, when the source came from one.
        extraction_metadata: Provenance of the extraction (extractor used,
            character counts, title), carried forward for traceability.
    """

    audit_id: str
    text: str
    source_uri: str | None = None
    extraction_metadata: dict[str, Any] = field(default_factory=dict)
    _segmenter: TextSegmenter = field(default_factory=TextSegmenter, repr=False)
    _derived: dict[str, Any] = field(default_factory=dict, repr=False)
    _artifacts: dict[str, Any] = field(default_factory=dict, repr=False)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)
    _guard: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # -- Lazy synchronous derivations --------------------------------------- #

    def _memo(self, key: str, factory: Callable[[], T]) -> T:
        """Memoize a synchronous derivation (no lock; never awaits)."""
        if key not in self._derived:
            self._derived[key] = factory()
        return self._derived[key]

    @property
    def paragraphs(self) -> tuple[TextSpan, ...]:
        """Paragraph spans of the source, computed once per audit."""
        return self._memo("paragraphs", lambda: self._segmenter.paragraphs(self.text))

    @property
    def sentences(self) -> tuple[TextSpan, ...]:
        """Sentence spans of the source, computed once per audit.

        The basis for source-side retrieval (Attribution), key-point extraction,
        and the numeric ledger. Every span carries source offsets so any finding
        can be turned into locatable evidence.
        """
        return self._memo("sentences", lambda: self._segmenter.segment(self.text))

    @property
    def sentences_by_paragraph(self) -> tuple[tuple[TextSpan, ...], ...]:
        """Sentence spans grouped by paragraph, for structure-aware stages."""
        return self._memo(
            "sentences_by_paragraph",
            lambda: self._segmenter.sentences_by_paragraph(self.text),
        )

    @property
    def statistics(self) -> DocumentStatistics:
        """Size and shape measurements of the source (facts, not judgments)."""
        return self._memo(
            "statistics",
            lambda: analyze_statistics(self.text, self.sentences, self.paragraphs),
        )

    @property
    def metadata(self) -> DocumentMetadata:
        """Title, language, format, and citation markers of the source."""
        return self._memo(
            "metadata",
            lambda: analyze_metadata(self.text, self.extraction_metadata),
        )

    def source_meta(self) -> SourceMeta:
        """Project the report-header facts about the source (§6).

        ``key_point_count`` is read from the key-points artifact if it has
        already been computed (MB2); it is 0 until then rather than forcing the
        expensive extraction from a metadata call.
        """
        key_points = self._artifacts.get(SourceKeys.KEY_POINTS)
        key_point_count = len(key_points) if key_points is not None else 0
        return SourceMeta(
            title=self.metadata.title,
            char_count=len(self.text),
            sentence_count=self.statistics.sentence_count,
            key_point_count=key_point_count,
        )

    # -- Shared async derivation store -------------------------------------- #

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[T] | T]
    ) -> T:
        """Return the source artifact at ``key``, computing it once if absent.

        The async tier, for derivations too expensive or IO-bound for a lazy
        property. The per-key lock lets several outputs race for the same source
        derivation without each recomputing it, while still allowing distinct
        derivations to proceed in parallel.

        Args:
            key: A stable name, preferably from :class:`SourceKeys`.
            factory: Produces the artifact; may be sync or async. Called at most
                once per key per audit.

        Returns:
            The cached or freshly computed artifact.

        Raises:
            Exception: Whatever ``factory`` raises. Nothing is cached on failure.
        """
        if key in self._artifacts:
            return self._artifacts[key]

        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            if key in self._artifacts:
                return self._artifacts[key]
            result = factory()
            if isinstance(result, Awaitable):
                result = await result
            self._artifacts[key] = result
            logger.debug(
                "source artifact computed",
                extra=bind(audit_id=self.audit_id, artifact=key),
            )
            return result  # type: ignore[return-value]

    def peek(self, key: str) -> Any | None:
        """Return a source artifact if already computed, without computing it."""
        return self._artifacts.get(key)

    @property
    def artifact_keys(self) -> tuple[str, ...]:
        """Names of the async source derivations computed so far, sorted."""
        return tuple(sorted(self._artifacts))

    def describe(self) -> dict[str, Any]:
        """Summarize the source for structured logging — ids and counts only."""
        stats = self.statistics
        return {
            "audit_id": self.audit_id,
            "source_char_count": len(self.text),
            "source_word_count": stats.word_count,
            "source_sentence_count": stats.sentence_count,
            "source_paragraph_count": stats.paragraph_count,
            "source_uri": self.source_uri,
        }

    @classmethod
    def build(
        cls,
        audit_id: str,
        text: str,
        source_uri: str | None = None,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> "SourceContext":
        """Wrap a normalized source article into a per-audit context.

        Args:
            audit_id: The run's id.
            text: The source article, already extracted to plain text.
            source_uri: The original URL/filename, when applicable.
            extraction_metadata: Provenance of the extraction.

        Returns:
            A context ready to share across every output pipeline.
        """
        return cls(
            audit_id=audit_id,
            text=text,
            source_uri=source_uri,
            extraction_metadata=dict(extraction_metadata or {}),
        )
