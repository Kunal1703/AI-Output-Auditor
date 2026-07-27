"""Attribution — per-claim retrieve → NLI → support map with evidence.

This is the core of the whole system (Software Architecture D2): for each output
claim it retrieves candidate source spans, runs the local NLI cross-encoder over
each ``(source-span, claim)`` pair, and aggregates SummaC-style (max entailment /
max contradiction over the candidates) into one of three states — **Supported /
Neutral / Contradicted** — with the supporting source span and an evidence
record. Every Layer-1 metric (Faithfulness, Hallucinations, Unsupported Claims,
Contradictions) is then *derived* from this one pass, which is why it is built
once and cached on the :class:`~app.shared.output_context.OutputContext`.

**Reuse.** Claims come from the existing ``ClaimExtractionService``; candidate
retrieval uses the shared ``RetrievalService`` over the source sentences
(sentence granularity, per SummaC); entailment uses the MB1 ``NLIService``;
evidence is recorded through the existing ``EvidenceStore`` / ``EvidenceCollector``.
Nothing here duplicates those.

**Label mapping.** The three NLI states map onto the frozen
:class:`~app.shared.schemas.SupportLabel` per Software Architecture §10:
``entailed → SUPPORTED``, ``neutral → PARTIAL``, ``contradicted → NOT_FOUND``.
The unambiguous NLI label is retained on :class:`ClaimAttribution` so the
Faithfulness evaluator can distinguish an unsupported claim (neutral) from a
contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.logging import bind, get_logger
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.nli_service import NLILabel, NLIService
from app.shared.output_context import OutputContext, OutputKeys
from app.shared.retrieval_service import Chunk, RetrievalService, RetrievedPassage
from app.shared.schemas import AttributionEntry, Span, SupportLabel
from app.shared.source_context import SourceContext
from app.shared.text_segmentation import TextSpan

if TYPE_CHECKING:
    from app.shared.embedding_service import EmbeddingService
    from app.shared.extraction.claims import ClaimExtractionService
    from app.shared.extraction.models import Claim

__all__ = ["AttributionService", "AttributionResult", "ClaimAttribution"]

logger = get_logger(__name__)

#: NLI state → frozen SupportLabel (Software Architecture §10).
_SUPPORT_BY_LABEL: dict[NLILabel, SupportLabel] = {
    NLILabel.SUPPORTED: SupportLabel.SUPPORTED,
    NLILabel.NEUTRAL: SupportLabel.PARTIAL,
    NLILabel.CONTRADICTED: SupportLabel.NOT_FOUND,
}

#: How far below the best retrieval score a candidate may still be considered
#: *contradicting* evidence for a claim. Retrieval returns the top-k source
#: sentences by similarity, but the tail of that list is often off-topic, and an
#: NLI cross-encoder routinely emits a spurious "contradiction" on unrelated
#: sentence pairs that merely share a date or a name (e.g. a claim about a 2028
#: film vs. a sentence about the 2007/2011 films). Crediting those flips faithful,
#: on-topic claims to CONTRADICTED. A genuine contradiction, by contrast, is
#: expressed by the claim's *own* evidence sentence, which retrieval ranks at or
#: near the top. Requiring the contradicting span to sit within this margin of the
#: best-retrieved span keeps genuine contradictions while dropping the off-topic
#: false positives. Support (entailment) is unaffected — it still scans all top-k.
#: The gate only ever narrows when CONTRADICTED is declared; it can never reduce a
#: SUPPORTED grounding. Calibrated against real pairs: false-positive contradictors
#: trailed the best span by 0.28–0.42 in similarity, genuine ones by 0.0.
_CONTRA_RELEVANCE_MARGIN = 0.15


@dataclass(frozen=True)
class ClaimAttribution:
    """One output claim's attribution to the source.

    Attributes:
        claim: The output claim.
        nli_label: The unambiguous NLI verdict — Supported / Neutral /
            Contradicted. The authority the Layer-1 metrics read.
        support: The frozen-contract projection of ``nli_label``.
        nli_score: Confidence of the winning NLI state, in [0, 1].
        confidence: Attribution confidence for this claim.
        source_span: The best supporting (or contradicting) source span, or
            ``None`` when nothing relevant was retrieved.
        source_passage: The retrieved passage the decision rested on.
        entry: The serializable :class:`AttributionEntry` for the report.
        evidence_ids: Evidence records backing this attribution.
    """

    claim: "Claim"
    nli_label: NLILabel
    support: SupportLabel
    nli_score: float
    confidence: float
    source_span: TextSpan | None
    source_passage: RetrievedPassage | None
    entry: AttributionEntry
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def is_supported(self) -> bool:
        return self.nli_label is NLILabel.SUPPORTED

    @property
    def is_contradicted(self) -> bool:
        return self.nli_label is NLILabel.CONTRADICTED

    @property
    def is_neutral(self) -> bool:
        return self.nli_label is NLILabel.NEUTRAL


@dataclass(frozen=True)
class AttributionResult:
    """The attribution map for one output, plus diagnostics.

    Attributes:
        attributions: One :class:`ClaimAttribution` per attributed claim.
        claims_total: How many claims the output produced.
        claims_skipped: Claims dropped by the ``max_claims`` cap (not attributed).
    """

    attributions: tuple[ClaimAttribution, ...]
    claims_total: int = 0
    claims_skipped: int = 0

    def __iter__(self):
        return iter(self.attributions)

    def __len__(self) -> int:
        return len(self.attributions)

    @property
    def supported(self) -> list[ClaimAttribution]:
        return [a for a in self.attributions if a.is_supported]

    @property
    def neutral(self) -> list[ClaimAttribution]:
        return [a for a in self.attributions if a.is_neutral]

    @property
    def contradicted(self) -> list[ClaimAttribution]:
        return [a for a in self.attributions if a.is_contradicted]

    @property
    def schema_entries(self) -> list[AttributionEntry]:
        """The serializable attribution map for ``OutputAudit.attribution``."""
        return [a.entry for a in self.attributions]


class AttributionService:
    """Builds the attribution map for an output, once, and caches it.

    Args:
        settings: Supplies ``attribution.*`` and ``nli.entail_threshold``.
        retrieval: Shared retrieval service (candidate source spans).
        nli: Shared NLI service (entailment).
        embeddings: Shared embedding service (to warm source-sentence vectors).
        claim_extraction: Shared claim extraction service.
    """

    def __init__(
        self,
        settings: Settings,
        retrieval: RetrievalService,
        nli: NLIService,
        embeddings: "EmbeddingService",
        claim_extraction: "ClaimExtractionService",
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval
        self._nli = nli
        self._embeddings = embeddings
        self._claim_extraction = claim_extraction

    async def attribute(
        self, output: OutputContext, evidence_store: EvidenceStore
    ) -> AttributionResult:
        """Attribute every output claim to the source, caching the result.

        Args:
            output: The output to attribute against its shared source.
            evidence_store: The run-scoped evidence store; span pairs are
                recorded here and referenced by the returned entries.

        Returns:
            The attribution map. Also cached on the output under
            ``OutputKeys.ATTRIBUTION`` so the Layer-1 metrics reuse it.
        """
        cached = output.peek(OutputKeys.ATTRIBUTION)
        if isinstance(cached, AttributionResult):
            return cached

        collector = EvidenceCollector(evidence_store, "Attribution")
        claims = await output.claims(self._claim_extraction)
        candidates = self._candidate_chunks(output.source)

        # Warm the source-sentence embeddings once so every claim's retrieval is
        # served from the shared cache rather than re-encoding the source.
        await output.source.sentence_embeddings(self._embeddings)

        cap = self._settings.attribution.max_claims
        selected = claims[:cap]
        skipped = max(0, len(claims) - len(selected))

        attributions: list[ClaimAttribution] = []
        for claim in selected:
            passages = await self._retrieval.search(
                claim.text, candidates, top_k=self._settings.attribution.top_k
            )
            attributions.append(
                await self._attribute_claim(claim, passages, collector)
            )

        result = AttributionResult(
            attributions=tuple(attributions),
            claims_total=len(claims),
            claims_skipped=skipped,
        )
        await output.get_or_compute(OutputKeys.ATTRIBUTION, lambda: result)

        logger.info(
            "attribution complete",
            extra=bind(
                audit_id=output.audit_id,
                output_id=output.output_id,
                claims=len(claims),
                supported=len(result.supported),
                neutral=len(result.neutral),
                contradicted=len(result.contradicted),
                skipped=skipped,
            ),
        )
        return result

    def _candidate_chunks(self, source: SourceContext) -> list[Chunk]:
        """Build one retrieval chunk per source sentence (SummaC granularity).

        Sentence-level candidates keep the entailment premise short and precise,
        which is what makes an NLI model trained on sentence pairs work on a
        document-length source.
        """
        return [
            Chunk(
                chunk_id=f"src_{span.index}",
                text=span.text,
                start=span.start,
                end=span.end,
                source_ref="source",
            )
            for span in source.sentences
        ]

    async def _attribute_claim(
        self,
        claim: "Claim",
        passages: list[RetrievedPassage],
        collector: EvidenceCollector,
    ) -> ClaimAttribution:
        """Run NLI over a claim's candidate passages and build its attribution."""
        entail_floor = self._settings.nli.entail_threshold
        contra_floor = self._settings.attribution.contradiction_threshold

        nli_label = NLILabel.NEUTRAL
        score = 0.0
        confidence = 0.0
        chosen: RetrievedPassage | None = None

        if passages:
            results = await self._nli.label_batch(
                [(p.chunk.text, claim.text) for p in passages]
            )
            # SummaC aggregation: best entailment across all candidate source
            # spans, best contradiction across only the *relevant* ones. Support
            # can legitimately come from any retrieved span; a contradiction only
            # counts from a span that is actually about the claim (see
            # _CONTRA_RELEVANCE_MARGIN), which drops off-topic NLI false positives
            # without touching support recall.
            best_support_i = max(
                range(len(results)), key=lambda i: results[i].entailment
            )
            # Passages are ordered by descending retrieval score, so passages[0]
            # is the best-matched span. Index 0 always clears the margin, so the
            # relevant set is never empty.
            top_score = passages[0].score
            relevant = [
                i
                for i in range(len(results))
                if passages[i].score >= top_score - _CONTRA_RELEVANCE_MARGIN
            ]
            best_contra_i = max(relevant, key=lambda i: results[i].contradiction)
            support_prob = results[best_support_i].entailment
            contra_prob = results[best_contra_i].contradiction

            if support_prob >= entail_floor:
                nli_label = NLILabel.SUPPORTED
                chosen = passages[best_support_i]
                score = support_prob
            elif contra_prob >= contra_floor:
                nli_label = NLILabel.CONTRADICTED
                chosen = passages[best_contra_i]
                score = contra_prob
            else:
                nli_label = NLILabel.NEUTRAL
                chosen = passages[0]  # best-retrieved, for context
                score = results[0].probabilities.get(NLILabel.NEUTRAL, 0.0)
            confidence = score

        support = _SUPPORT_BY_LABEL[nli_label]
        source_span = (
            TextSpan(
                text=chosen.chunk.text,
                start=chosen.chunk.start,
                end=chosen.chunk.end,
                kind="reference_passage",
            )
            if chosen is not None
            else None
        )

        # Evidence: the output span for the claim, and the source span it was
        # (or was not) grounded against.
        output_ev = (
            collector.output_span(claim.source_span)
            if claim.source_span is not None
            else None
        )
        source_ev = (
            collector.reference_passage(source_span, source_ref="source")
            if source_span is not None
            else None
        )
        evidence_ids = collector.refs(output_ev, source_ev)

        entry = AttributionEntry(
            output_unit_id=claim.claim_id,
            output_span=_output_span(claim),
            support=support,
            source_span=(
                _span_from(source_span, "source") if source_span is not None else None
            ),
            nli_score=round(score, 4),
            confidence=round(confidence, 4),
        )

        return ClaimAttribution(
            claim=claim,
            nli_label=nli_label,
            support=support,
            nli_score=round(score, 4),
            confidence=round(confidence, 4),
            source_span=source_span,
            source_passage=chosen,
            entry=entry,
            evidence_ids=evidence_ids,
        )


def _span_from(text_span: TextSpan, ref: str) -> Span:
    """Project a :class:`TextSpan` into a contract :class:`Span`."""
    return Span(
        text=text_span.text,
        start=text_span.start,
        end=text_span.end,
        ref="source" if ref == "source" else "output",
        locator=text_span.locator(),
    )


def _output_span(claim: "Claim") -> Span:
    """The output-side span for a claim, from its located sentence or its text."""
    if claim.source_span is not None:
        return _span_from(claim.source_span, "output")
    return Span(text=claim.text, start=0, end=len(claim.text), ref="output")
