"""Meaning Preservation — holistic distortion, derived from MB2/MB3 signals.

Individually-true claims can still misrepresent the whole: cherry-picking,
dropped caveats, tone shift, reversal (Evaluation Framework §3.3). This evaluator
catches distortion that per-claim faithfulness misses, and a **severe** distortion
(meaning reversal) is a hard gate.

Per the MB3 constraint it **reuses Attribution instead of rebuilding grounding**,
plus the Coverage result:

* **Distortion / reversal** — output claims the NLI labelled *contradicted* are
  where the output states something the source denies; each is a
  ``MEANING_DISTORTION`` finding (a reversal), and its presence is a severe
  distortion.
* **Context loss** — high-salience source key points the output dropped
  (Coverage's Missing Critical Facts) are lost essential context; each is a
  ``CONTEXT_LOSS`` finding.

The score starts from Coverage's salience-weighted base (how much of the source's
meaning is retained) and is penalized for contradictions and dropped context.
Evidence is reused from Attribution and Coverage — nothing is recorded twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.attribution.attribution import AttributionResult
from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids
from app.evaluators.coverage import CoverageResult
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)
from app.shared.scoring import clamp

__all__ = ["MeaningPreservationEvaluator", "MeaningPreservationResult"]

_METRIC_ID = "Meaning Preservation"


@dataclass(frozen=True)
class MeaningPreservationResult:
    """The Meaning Preservation outcome for one output.

    Attributes:
        metric_result: The standardized :class:`MetricResult`.
        distortions: ``MEANING_DISTORTION`` findings (contradictions / reversals).
        context_losses: ``CONTEXT_LOSS`` findings (dropped high-salience context).
        severe: Whether a severe distortion (reversal) was found — the hard-gate
            signal the Decision Engine reads in MB4.
    """

    metric_result: MetricResult
    distortions: tuple[Finding, ...]
    context_losses: tuple[Finding, ...]
    severe: bool


class MeaningPreservationEvaluator:
    """Derives Meaning Preservation from attribution + coverage.

    Args:
        settings: Supplies ``meaning.*``.
    """

    metric_id = _METRIC_ID
    layer = Layer.L2_INFO
    gate_role = GateRole.PARTIAL_GATING

    def __init__(self, settings: Settings) -> None:
        self._cfg = settings.meaning

    def evaluate(
        self, attribution: AttributionResult, coverage: CoverageResult
    ) -> MeaningPreservationResult:
        """Produce the Meaning Preservation score and distortion findings.

        Args:
            attribution: The MB2 attribution map (reused for contradictions).
            coverage: The MB3 Coverage result (reused for base score + losses).

        Returns:
            The Meaning Preservation result — score, findings, evidence.
        """
        ids = finding_ids("mean")

        distortions = [
            self._distortion_finding(next(ids), att)
            for att in attribution.contradicted
        ]
        context_losses = [
            self._context_loss_finding(next(ids), fact)
            for fact in coverage.missing_critical_facts
        ]

        base = coverage.metric_result.score
        base = base if base is not None else 1.0
        score = clamp(
            base
            - self._cfg.contradiction_penalty * len(distortions)
            - self._cfg.context_loss_penalty * len(context_losses)
        )
        severe = len(distortions) > 0

        findings = [*distortions, *context_losses]
        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L2_INFO,
            gate_role=GateRole.PARTIAL_GATING,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(attribution, coverage),
            applicable=True,
            findings=findings,
            metadata={
                "base_coverage_score": round(base, 4),
                "distortions": len(distortions),
                "context_losses": len(context_losses),
                "severe_distortion": severe,
            },
        )
        return MeaningPreservationResult(
            metric_result=metric,
            distortions=tuple(distortions),
            context_losses=tuple(context_losses),
            severe=severe,
        )

    def _distortion_finding(self, finding_id: str, att) -> Finding:
        """A meaning reversal: the output states what the source contradicts."""
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L2_INFO,
            type=FindingType.MEANING_DISTORTION,
            severity=FindingSeverity.CRITICAL,
            note=(
                "The output reverses or distorts the source's meaning: "
                f"{att.claim.text!r} conflicts with the source."
            ),
            output_span=att.entry.output_span,
            source_span=att.entry.source_span,
            evidence_refs=list(att.evidence_ids),
        )

    def _context_loss_finding(self, finding_id: str, fact: Finding) -> Finding:
        """A dropped high-salience key point — lost essential context."""
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L2_INFO,
            type=FindingType.CONTEXT_LOSS,
            severity=FindingSeverity.MAJOR,
            note=(
                "Essential context from the source is lost in the output: "
                + fact.note
            ),
            source_span=fact.source_span,
            evidence_refs=list(fact.evidence_refs),
            centrality=fact.centrality,
        )

    @staticmethod
    def _confidence(attribution: AttributionResult, coverage: CoverageResult) -> float:
        """Confidence: the mean of the attribution and coverage confidences."""
        attr_conf = (
            sum(a.confidence for a in attribution) / len(attribution)
            if len(attribution)
            else 0.2
        )
        return round((attr_conf + coverage.metric_result.confidence) / 2, 4)
