"""Conciseness / Non-Redundancy — communication efficiency.

Redundant output wastes a reader's time (Evaluation Framework §4.3). This
evaluator **reuses the existing redundancy detection logic** from the legacy
Novelty engine — embedding similarity plus literal (Jaccard) overlap over the
output's own sentences, with the tuned ``engines.novelty`` thresholds (the
measured 0.60 semantic threshold is reused, not re-derived) — and scores by the
*mass* of confirmed-redundant text, not a count of pairs.

It is deterministic: the LLM functional-repetition review the legacy engine runs
is intentionally not invoked here (MB3 keeps this lightweight and model-free).
Compensatory Layer-3 metric; it never gates.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids, to_span
from app.shared.embedding_service import EmbeddingService, relatedness
from app.shared.evidence_pipeline import EvidenceCollector
from app.shared.evidence_store import EvidenceStore
from app.shared.output_context import OutputContext
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)
from app.shared.scoring import clamp
from app.shared.text_segmentation import TextSpan, normalize_whitespace

__all__ = ["ConcisenessEvaluator", "ConcisenessResult"]

_METRIC_ID = "Conciseness / Non-Redundancy"


@dataclass(frozen=True)
class ConcisenessResult:
    """The Conciseness outcome for one output."""

    metric_result: MetricResult
    findings: tuple[Finding, ...]


class ConcisenessEvaluator:
    """Scores redundancy from reused embedding + literal-overlap detection.

    Args:
        settings: Supplies ``engines.novelty`` (tuned thresholds reused).
        embeddings: The shared embedding service.
    """

    metric_id = _METRIC_ID
    layer = Layer.L3_PRESENTATION
    gate_role = GateRole.COMPENSATORY

    def __init__(self, settings: Settings, embeddings: EmbeddingService) -> None:
        self._cfg = settings.engines.novelty
        self._embeddings = embeddings

    async def evaluate(
        self, output: OutputContext, evidence_store: EvidenceStore
    ) -> ConcisenessResult:
        """Score conciseness and surface redundant passages.

        Args:
            output: The output being audited.
            evidence_store: The run-scoped evidence store.

        Returns:
            The Conciseness result — score, confidence, findings, evidence.
        """
        collector = EvidenceCollector(evidence_store, _METRIC_ID)
        ids = finding_ids("conc")

        segments = tuple(
            span
            for span in output.sentences
            if len(span.text.split()) >= self._cfg.min_segment_words
        )
        total_words = output.statistics.word_count

        if len(segments) < 2:
            return self._trivial_result(len(segments), total_words)

        vectors = await self._embeddings.embed([span.text for span in segments])
        normalized = [normalize_whitespace(span.text).lower() for span in segments]

        findings: list[Finding] = []
        redundant_words = 0
        counted: set[int] = set()

        for index in range(1, len(segments)):
            best_score, best_index = 0.0, -1
            for earlier in range(index):
                score = relatedness(vectors[index], vectors[earlier])
                if score > best_score:
                    best_score, best_index = score, earlier
            if best_index < 0:
                continue

            literal = self._is_literal_duplicate(normalized[index], normalized[best_index])
            if best_score < self._cfg.semantic_threshold and not literal:
                continue

            segment = segments[index]
            if segment.index not in counted:
                counted.add(segment.index)
                redundant_words += len(segment.text.split())
                findings.append(
                    self._redundancy_finding(
                        next(ids), segment, segments[best_index], best_score, literal, collector
                    )
                )

        score = clamp(1.0 - (redundant_words / total_words if total_words else 0.0))
        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L3_PRESENTATION,
            gate_role=GateRole.COMPENSATORY,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(total_words),
            applicable=True,
            findings=list(findings),
            metadata={
                "segments": len(segments),
                "redundant_segments": len(findings),
                "redundant_words": redundant_words,
                "total_words": total_words,
            },
        )
        return ConcisenessResult(metric_result=metric, findings=tuple(findings))

    def _is_literal_duplicate(self, left: str, right: str) -> bool:
        """Exact match or Jaccard token overlap above the literal threshold."""
        if left == right:
            return True
        left_tokens, right_tokens = set(left.split()), set(right.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        return overlap >= self._cfg.literal_threshold

    def _redundancy_finding(
        self,
        finding_id: str,
        segment: TextSpan,
        earlier: TextSpan,
        similarity: float,
        literal: bool,
        collector: EvidenceCollector,
    ) -> Finding:
        """A confirmed-redundant passage, with both spans as evidence."""
        seg_ev = collector.output_span(segment)
        earlier_ev = collector.output_span(earlier)
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L3_PRESENTATION,
            type=FindingType.REDUNDANCY,
            severity=FindingSeverity.MINOR,
            note=(
                f"Redundant passage (similarity {similarity:.2f}"
                f"{', literal' if literal else ''}): {segment.text[:80]!r} restates "
                f"{earlier.text[:80]!r}."
            ),
            output_span=to_span(segment, "output"),
            evidence_refs=[seg_ev.evidence_id, earlier_ev.evidence_id],
        )

    def _trivial_result(self, segments: int, total_words: int) -> ConcisenessResult:
        """One segment cannot repeat itself — a confident perfect score."""
        return ConcisenessResult(
            metric_result=MetricResult(
                metric_id=_METRIC_ID,
                layer=Layer.L3_PRESENTATION,
                gate_role=GateRole.COMPENSATORY,
                score=1.0,
                band=5,
                confidence=0.6,
                applicable=True,
                metadata={"segments": segments, "total_words": total_words},
            ),
            findings=(),
        )

    def _confidence(self, total_words: int) -> float:
        """Confidence rises with content — redundancy is hard to establish short."""
        return round(min(1.0, total_words / self._cfg.words_for_full_confidence), 4)
