"""Layered Decision Engine — the non-compensatory verdict (AI Output Auditor, MB4).

Implements the frozen decision flow of Evaluation Framework §6 over the metric
results of one output. **It consumes ``MetricResult`` objects only** — never
evaluator internals — and never re-runs an evaluator.

The layers, and their fixed roles:

* **Layer 1 — Grounding (non-compensatory).** A *critical* grounding finding — a
  contradiction, a critical numeric error, or (from Layer 2) a meaning reversal —
  caps the verdict at **Fail**, regardless of how well the output reads. A
  *major* grounding finding caps at **Needs Revision**.
* **Layer 2 — Information Quality (partial gating).** A *critical* omission caps
  at **Needs Revision**; Coverage and Meaning Preservation otherwise feed the
  compensatory score.
* **Layer 3 — Presentation (compensatory).** Readability, Conciseness, and Bias
  shape the quality score *within* the ceiling the higher layers set — they can
  never buy back a grounding failure.
* **Confidence overlay.** If grounding cannot be established with sufficient
  confidence, and there is no definite grounding failure, the verdict is
  **Unable to Verify** rather than a pass.

Only thresholds and weights are configuration (``settings.verdict``); the rules
above are fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.core.config import Settings
from app.shared.scoring import weighted_mean
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    Layer,
    MetricResult,
    VerdictBand,
)

__all__ = ["GroundingDecisionEngine", "DecisionOutcome"]

#: Verdict severity rank, higher = better. Used to take the worse (min) of a
#: compensatory band and a gate ceiling.
_BAND_RANK: dict[VerdictBand, int] = {
    VerdictBand.FAIL: 0,
    VerdictBand.UNABLE_TO_VERIFY: 1,
    VerdictBand.NEEDS_REVISION: 2,
    VerdictBand.GOOD: 3,
    VerdictBand.EXCELLENT: 4,
}


@dataclass(frozen=True)
class DecisionOutcome:
    """The Decision Engine's verdict for one output.

    Attributes:
        verdict: The final :class:`VerdictBand`.
        reason: Plain-language justification (gating finding, confidence gap, or
            band).
        quality_score: The confidence-weighted compensatory quality score in
            [0, 1], or None when no quality metric could be scored.
        grounding_confidence: The Layer-1 confidence the overlay tested.
        gating_finding_ids: Ids of the findings that gated the verdict.
    """

    verdict: VerdictBand
    reason: str
    quality_score: float | None
    grounding_confidence: float
    gating_finding_ids: list[str] = field(default_factory=list)


class GroundingDecisionEngine:
    """Resolves one output's metric results into a verdict.

    Args:
        settings: Supplies ``verdict.*`` thresholds and weights.
    """

    def __init__(self, settings: Settings) -> None:
        self._cfg = settings.verdict

    def decide(self, metrics: Sequence[MetricResult]) -> DecisionOutcome:
        """Produce the verdict for one output from its metric results.

        Args:
            metrics: Every ``MetricResult`` for the output (all layers).

        Returns:
            The decision outcome.
        """
        l1 = [m for m in metrics if m.layer is Layer.L1_GROUNDING]
        l2 = [m for m in metrics if m.layer is Layer.L2_INFO]
        l3 = [m for m in metrics if m.layer is Layer.L3_PRESENTATION]

        critical_grounding = self._findings(l1, severity=FindingSeverity.CRITICAL)
        meaning_reversals = [
            f
            for m in l2
            for f in m.findings
            if f.type is FindingType.MEANING_DISTORTION
            and f.severity is FindingSeverity.CRITICAL
        ]
        major_grounding = self._findings(l1, severity=FindingSeverity.MAJOR)
        l2_critical_omissions = [
            f
            for m in l2
            for f in m.findings
            if f.type is FindingType.MISSING_CRITICAL_FACT
            and f.severity is FindingSeverity.CRITICAL
        ]

        grounding_confidence = min(
            (m.confidence for m in l1 if m.applicable), default=0.0
        )
        quality_score = self._quality_score([*l2, *l3])

        # 1. Layer-1 grounding gate (non-compensatory) — a definite critical
        #    grounding failure or a meaning reversal is a Fail, full stop.
        hard_fail = [*critical_grounding, *meaning_reversals]
        if hard_fail:
            return DecisionOutcome(
                verdict=VerdictBand.FAIL,
                reason=self._fail_reason(hard_fail),
                quality_score=quality_score,
                grounding_confidence=grounding_confidence,
                gating_finding_ids=[f.finding_id for f in hard_fail],
            )

        # 2. Confidence overlay — grounding could not be established, and there is
        #    no definite failure, so we decline to assert a pass.
        if grounding_confidence < self._cfg.min_grounding_confidence:
            return DecisionOutcome(
                verdict=VerdictBand.UNABLE_TO_VERIFY,
                reason=(
                    "Grounding could not be established with sufficient confidence "
                    f"({grounding_confidence:.0%} < "
                    f"{self._cfg.min_grounding_confidence:.0%}); the auditor "
                    "declines to assert a verdict."
                ),
                quality_score=quality_score,
                grounding_confidence=grounding_confidence,
            )

        # 3. Ceiling from major grounding faults and Layer-2 critical omissions.
        ceiling: VerdictBand | None = None
        ceiling_findings: list[Finding] = []
        if major_grounding:
            ceiling = VerdictBand.NEEDS_REVISION
            ceiling_findings = major_grounding
        elif l2_critical_omissions:
            ceiling = VerdictBand.NEEDS_REVISION
            ceiling_findings = l2_critical_omissions

        # 4. Compensatory band, capped by the ceiling.
        band = self._band(quality_score)
        verdict = self._worse(band, ceiling) if ceiling is not None else band

        return DecisionOutcome(
            verdict=verdict,
            reason=self._pass_reason(verdict, band, ceiling, ceiling_findings, quality_score),
            quality_score=quality_score,
            grounding_confidence=grounding_confidence,
            gating_finding_ids=[f.finding_id for f in ceiling_findings],
        )

    @staticmethod
    def _findings(
        metrics: Sequence[MetricResult], severity: FindingSeverity
    ) -> list[Finding]:
        """All findings of a given severity across the metrics."""
        return [f for m in metrics for f in m.findings if f.severity is severity]

    def _quality_score(self, metrics: Sequence[MetricResult]) -> float | None:
        """Confidence-weighted mean of the applicable Layer-2/3 metric scores."""
        pairs: list[tuple[float, float]] = []
        for metric in metrics:
            if not metric.applicable or metric.score is None:
                continue
            weight = self._cfg.quality_weights.get(metric.metric_id, 1.0)
            pairs.append((metric.score, weight * max(metric.confidence, 0.05)))
        if not pairs:
            return None
        return weighted_mean(pairs, default=0.0)

    def _band(self, quality_score: float | None) -> VerdictBand:
        """Map a compensatory quality score onto a band."""
        if quality_score is None:
            return VerdictBand.GOOD  # no quality signal; grounding carried it
        if quality_score >= self._cfg.excellent_band:
            return VerdictBand.EXCELLENT
        if quality_score >= self._cfg.good_band:
            return VerdictBand.GOOD
        return VerdictBand.NEEDS_REVISION

    @staticmethod
    def _worse(a: VerdictBand, b: VerdictBand) -> VerdictBand:
        """Return the lower-ranked (worse) of two bands."""
        return a if _BAND_RANK[a] <= _BAND_RANK[b] else b

    @staticmethod
    def _fail_reason(findings: Sequence[Finding]) -> str:
        top = findings[0]
        extra = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
        return (
            f"Grounding failure caps the verdict at Fail: {top.metric} — "
            f"{top.note}{extra}"
        )

    def _pass_reason(
        self,
        verdict: VerdictBand,
        band: VerdictBand,
        ceiling: VerdictBand | None,
        ceiling_findings: Sequence[Finding],
        quality_score: float | None,
    ) -> str:
        q = f"{quality_score:.2f}" if quality_score is not None else "n/a"
        if ceiling is not None and verdict is not band:
            top = ceiling_findings[0] if ceiling_findings else None
            note = f" — {top.metric}: {top.note}" if top is not None else ""
            return (
                f"Quality score {q} would be {band.value}, capped at "
                f"{verdict.value} by a grounding/information gate{note}"
            )
        return f"No gating failure; compensatory quality score {q} → {verdict.value}."
