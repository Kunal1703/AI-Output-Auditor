"""Faithfulness — the headline Layer-1 metric, derived from Attribution.

Faithfulness is *precision over claims*: is every claim in the output supported
by the source, with nothing fabricated or contradicting it? Per the Evaluation
Framework (§2.1) the score is **derived, not asserted** — it is read off the
Attribution pass and the grounding findings, so it always traces to itemized
evidence rather than an opaque model score.

This evaluator consumes the :class:`~app.attribution.attribution.AttributionResult`
(already computed and cached on the output) and produces:

* a **score** — the severity-weighted fraction of supported claims;
* three finding views the framework names separately, all drawn from the same
  attribution so nothing is double-counted:
    - **Contradictions** (§2.5) — claims the NLI labels *contradicted*; these are
      the *intrinsic* hallucinations (§2.2);
    - **Unsupported Claims** (§2.4) — claims the NLI labels *neutral*; these are
      the *extrinsic* hallucinations (§2.2);
    - **Hallucinations** (§2.2) — the union of the two.

Findings reuse the evidence records Attribution already wrote (the output span
and the source span it was judged against), so every Faithfulness finding is
evidence-linked without recording anything twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.attribution.attribution import AttributionResult, ClaimAttribution
from app.core.config import Settings
from app.evaluators.base import band_from_score, finding_ids
from app.shared.schemas import (
    Finding,
    FindingSeverity,
    FindingType,
    GateRole,
    Layer,
    MetricResult,
)

__all__ = ["FaithfulnessEvaluator", "FaithfulnessResult"]

_METRIC_ID = "Faithfulness"

#: Credit each attribution state earns toward the score.
_CREDIT = {"supported": 1.0, "neutral": 0.0, "contradicted": 0.0}


@dataclass(frozen=True)
class FaithfulnessResult:
    """The Faithfulness outcome for one output.

    Attributes:
        metric_result: The standardized :class:`MetricResult`.
        contradictions: Findings for claims that contradict the source
            (intrinsic hallucinations).
        unsupported_claims: Findings for claims unsupported by the source
            (extrinsic hallucinations).
    """

    metric_result: MetricResult
    contradictions: tuple[Finding, ...]
    unsupported_claims: tuple[Finding, ...]

    @property
    def hallucinations(self) -> tuple[Finding, ...]:
        """All ungrounded content — intrinsic and extrinsic (§2.2)."""
        return self.contradictions + self.unsupported_claims


class FaithfulnessEvaluator:
    """Derives Faithfulness for one output from its attribution map.

    Args:
        settings: Configuration (reserved for future thresholds; the evaluator is
            deterministic given the attribution result).
    """

    metric_id = _METRIC_ID
    layer = Layer.L1_GROUNDING
    gate_role = GateRole.GATING

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self, attribution: AttributionResult
    ) -> FaithfulnessResult:
        """Produce the Faithfulness score and grounding findings.

        Args:
            attribution: The output's attribution map (from
                :class:`~app.attribution.attribution.AttributionService`).

        Returns:
            The Faithfulness result — score, findings, and evidence.
        """
        ids = finding_ids("faith")
        contradictions: list[Finding] = []
        unsupported: list[Finding] = []

        credit = 0.0
        for att in attribution.attributions:
            if att.is_supported:
                credit += _CREDIT["supported"]
                continue
            if att.is_contradicted:
                contradictions.append(self._contradiction_finding(next(ids), att))
            else:  # neutral → unsupported / extrinsic hallucination
                unsupported.append(self._unsupported_finding(next(ids), att))

        total = len(attribution.attributions)
        score = credit / total if total else None
        findings = [*contradictions, *unsupported]
        evidence_refs = [ref for att in attribution for ref in att.evidence_ids]

        metric = MetricResult(
            metric_id=_METRIC_ID,
            layer=Layer.L1_GROUNDING,
            gate_role=GateRole.GATING,
            score=score,
            band=band_from_score(score),
            confidence=self._confidence(attribution),
            applicable=True,
            applicability_reason=(
                "" if total else "No checkable claims were extracted from the output."
            ),
            findings=findings,
            metadata={
                "claims_total": attribution.claims_total,
                "claims_attributed": total,
                "claims_skipped": attribution.claims_skipped,
                "supported": len(attribution.supported),
                "unsupported": len(unsupported),
                "contradicted": len(contradictions),
                "hallucinations": len(findings),
                "evidence_refs": evidence_refs,
            },
        )
        return FaithfulnessResult(
            metric_result=metric,
            contradictions=tuple(contradictions),
            unsupported_claims=tuple(unsupported),
        )

    def _contradiction_finding(self, finding_id: str, att: ClaimAttribution) -> Finding:
        """A claim that directly conflicts with the source — a hard grounding fault."""
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L1_GROUNDING,
            type=FindingType.CONTRADICTION,
            severity=FindingSeverity.CRITICAL,
            note=(
                "Claim contradicts the source (intrinsic hallucination): "
                f"{att.claim.text!r}."
            ),
            output_span=att.entry.output_span,
            source_span=att.entry.source_span,
            evidence_refs=list(att.evidence_ids),
        )

    def _unsupported_finding(self, finding_id: str, att: ClaimAttribution) -> Finding:
        """A claim with no support in the source — an extrinsic hallucination."""
        return Finding(
            finding_id=finding_id,
            metric=_METRIC_ID,
            layer=Layer.L1_GROUNDING,
            type=FindingType.UNSUPPORTED_CLAIM,
            severity=FindingSeverity.MAJOR,
            note=(
                "Claim is not supported by the source (extrinsic hallucination): "
                f"{att.claim.text!r}."
            ),
            output_span=att.entry.output_span,
            source_span=att.entry.source_span,
            evidence_refs=list(att.evidence_ids),
        )

    def _confidence(self, attribution: AttributionResult) -> float:
        """Confidence in the Faithfulness verdict.

        A transparent, hand-reconstructable blend of two named signals: how
        decisive the NLI verdicts were (mean winning-class probability) and how
        many claims were traced to a located output span. Empty attribution → low
        confidence, never a confident vacuous pass.
        """
        if not attribution.attributions:
            return 0.2
        mean_nli = sum(a.nli_score for a in attribution) / len(attribution)
        located = sum(1 for a in attribution if a.claim.source_span is not None)
        located_rate = located / len(attribution)
        return round(0.6 * mean_nli + 0.4 * located_rate, 4)
