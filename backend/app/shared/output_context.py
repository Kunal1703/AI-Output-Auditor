"""OutputContext — the per-output view of one output under audit.

The AI Output Auditor audits each output independently against the same source.
This is the *output* tier of the two-tier context design (Software Architecture
D3): one :class:`OutputContext` per output, each holding a reference to the
single shared :class:`~app.shared.source_context.SourceContext` for the audit.

It mirrors the legacy :class:`~app.shared.context.SharedContext` caching design —
synchronous lazy properties for cheap CPU derivations (segmentation, statistics,
metadata) and an async :meth:`get_or_compute` store with per-key locks for the
expensive per-output derivations: the output's atomic claims, its embeddings, its
numeric ledger, and the **attribution map** every Layer-1 metric is derived from.

**MB1 scope.** The container, the sync text derivations, the link to the source,
and the shared async store are complete. The expensive derivations (claims,
attribution) are computed by the Attribution substrate and evaluators in MB2;
their cache keys are declared in :class:`OutputKeys`.

**It does not evaluate.** Deriving *what the output is* lives here; deciding
*whether it is faithful* is a metric and lives in an evaluator (MB2).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypeVar

from app.core.logging import bind, get_logger
from app.shared.document_analysis import (
    DocumentMetadata,
    DocumentStatistics,
    analyze_metadata,
    analyze_statistics,
)
from app.shared.extraction.models import Claim
from app.shared.numeric_ledger import NumericMention, extract_numeric_mentions
from app.shared.schemas import OutputType, Producer
from app.shared.source_context import SourceContext
from app.shared.text_segmentation import TextSegmenter, TextSpan

if TYPE_CHECKING:  # imported for typing only — avoids importing heavy services
    from app.shared.embedding_service import EmbeddingService
    from app.shared.extraction.claims import ClaimExtractionService

__all__ = ["OutputContext", "OutputKeys"]

logger = get_logger(__name__)

T = TypeVar("T")


class OutputKeys:
    """Canonical cache keys for per-output derivations.

    Declared in MB1 so the MB2 producers (Attribution) and consumers (the
    Layer-1 metrics that read the attribution map) agree on one name. The
    artifacts themselves are computed in MB2.
    """

    #: The output decomposed into atomic, independently checkable claims
    #: (ClaimExtractionService), the unit Attribution and Faithfulness operate on.
    OUTPUT_CLAIMS = "output_claims"

    #: Embeddings of the output claims/sentences, for retrieval against source.
    OUTPUT_EMBEDDINGS = "output_embeddings"

    #: The output numeric/entity ledger (Factual & Numeric Accuracy).
    NUMERIC_LEDGER = "output_numeric_ledger"

    #: The attribution map — per claim, its supporting source span or "absent".
    #: The single fan-in every Layer-1 metric derives from (Attribution §5.1).
    ATTRIBUTION = "attribution"


@dataclass
class OutputContext:
    """One output under audit, its derivations, and a link to the source.

    Attributes:
        audit_id: The run this output belongs to.
        output_id: Run-unique id for this output; used to key its results and
            comparison row.
        text: The output text, exactly as submitted.
        source: The shared per-audit source context this output is audited
            against.
        producer: Who produced the output (human / LLM / unknown).
        output_type: The kind of output, which narrows some metrics (MB2).
        task_prompt: The instruction that produced the output, when known.
        source_uri: The original URL/filename, when the output came from one.
        extraction_metadata: Provenance of the extraction.
    """

    audit_id: str
    output_id: str
    text: str
    source: SourceContext
    producer: Producer = Producer.UNKNOWN
    output_type: OutputType = OutputType.OTHER
    task_prompt: str | None = None
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
        """Paragraph spans of the output, computed once."""
        return self._memo("paragraphs", lambda: self._segmenter.paragraphs(self.text))

    @property
    def sentences(self) -> tuple[TextSpan, ...]:
        """Sentence spans of the output, computed once.

        The basis for claim extraction, attribution, and the presentation-layer
        metrics. Every span carries source offsets for locatable evidence.
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
        """Size and shape measurements of the output (facts, not judgments)."""
        return self._memo(
            "statistics",
            lambda: analyze_statistics(self.text, self.sentences, self.paragraphs),
        )

    @property
    def metadata(self) -> DocumentMetadata:
        """Title, language, format, and citation markers of the output."""
        return self._memo(
            "metadata",
            lambda: analyze_metadata(self.text, self.extraction_metadata),
        )

    @property
    def has_task_prompt(self) -> bool:
        """Whether a task prompt was supplied for this output."""
        return bool(self.task_prompt and self.task_prompt.strip())

    @property
    def compression_ratio(self) -> float | None:
        """Output length as a fraction of source length, or None if source empty.

        A cheap deterministic fact used by Compression's applicability gate (MB2)
        and available now for logging. Not a judgment — whether the compression
        was *good* is a metric.
        """
        source_words = self.source.statistics.word_count
        if source_words <= 0:
            return None
        return self.statistics.word_count / source_words

    @property
    def numeric_mentions(self) -> tuple[NumericMention, ...]:
        """The output numeric ledger — figures/dates/percentages/quantities.

        Deterministic and model-free; a synchronous lazy derivation. The Numeric
        Accuracy evaluator compares each of these against the source ledger.
        """
        return self._memo(
            "numeric_mentions",
            lambda: extract_numeric_mentions(self.text, self.sentences),
        )

    # -- Expensive async derivations (MB2) ---------------------------------- #

    async def claims(
        self, extraction: "ClaimExtractionService"
    ) -> tuple[Claim, ...]:
        """Decompose the output into atomic, independently checkable claims.

        The unit Attribution and Faithfulness operate on. Reuses the existing
        ``ClaimExtractionService`` (§7.2 stage 2) unchanged; the returned claims
        carry ``claim_type``/``centrality`` as ``None`` (classification is a
        later stage the auditor does not run in MB2).

        Args:
            extraction: The shared claim extraction service.

        Returns:
            The output's claims, in output order.
        """

        async def compute() -> tuple[Claim, ...]:
            result = await extraction.extract(self.text)
            return tuple(result.units)

        return await self.get_or_compute(OutputKeys.OUTPUT_CLAIMS, compute)

    async def claim_embeddings(
        self, embeddings: "EmbeddingService", claims: tuple[Claim, ...]
    ) -> list[list[float]]:
        """Embed the output claims once, warming the shared cache.

        Args:
            embeddings: The shared embedding service.
            claims: The claims to embed (from :meth:`claims`).

        Returns:
            One vector per claim, in claim order.
        """

        async def compute() -> list[list[float]]:
            texts = [claim.text for claim in claims]
            return await embeddings.embed(texts) if texts else []

        return await self.get_or_compute(OutputKeys.OUTPUT_EMBEDDINGS, compute)

    # -- Shared async derivation store -------------------------------------- #

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[T] | T]
    ) -> T:
        """Return the per-output artifact at ``key``, computing it once if absent.

        Args:
            key: A stable name, preferably from :class:`OutputKeys`.
            factory: Produces the artifact; may be sync or async. Called at most
                once per key per output.

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
                "output artifact computed",
                extra=bind(
                    audit_id=self.audit_id, output_id=self.output_id, artifact=key
                ),
            )
            return result  # type: ignore[return-value]

    def peek(self, key: str) -> Any | None:
        """Return a per-output artifact if already computed, without computing it."""
        return self._artifacts.get(key)

    @property
    def artifact_keys(self) -> tuple[str, ...]:
        """Names of the async per-output derivations computed so far, sorted."""
        return tuple(sorted(self._artifacts))

    def describe(self) -> dict[str, Any]:
        """Summarize the output for structured logging — ids and counts only."""
        stats = self.statistics
        return {
            "audit_id": self.audit_id,
            "output_id": self.output_id,
            "producer": self.producer.value,
            "output_type": self.output_type.value,
            "output_char_count": len(self.text),
            "output_word_count": stats.word_count,
            "output_sentence_count": stats.sentence_count,
            "has_task_prompt": self.has_task_prompt,
        }

    @classmethod
    def build(
        cls,
        audit_id: str,
        output_id: str,
        text: str,
        source: SourceContext,
        producer: Producer = Producer.UNKNOWN,
        output_type: OutputType = OutputType.OTHER,
        task_prompt: str | None = None,
        source_uri: str | None = None,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> "OutputContext":
        """Wrap a normalized output into a per-output context.

        Args:
            audit_id: The run's id.
            output_id: Run-unique id for this output.
            text: The output text, already extracted to plain text.
            source: The shared per-audit source context.
            producer: Who produced the output.
            output_type: The kind of output.
            task_prompt: The instruction that produced it, when known.
            source_uri: The original URL/filename, when applicable.
            extraction_metadata: Provenance of the extraction.

        Returns:
            A context ready to hand to the per-output pipeline (MB2).
        """
        return cls(
            audit_id=audit_id,
            output_id=output_id,
            text=text,
            source=source,
            producer=producer,
            output_type=output_type,
            task_prompt=task_prompt,
            source_uri=source_uri,
            extraction_metadata=dict(extraction_metadata or {}),
        )
