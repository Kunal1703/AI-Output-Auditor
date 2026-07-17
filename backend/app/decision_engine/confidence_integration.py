"""Stage 7 — Confidence Integration (Document 3, §8).

Overlays per-dimension confidence on the Trust and Quality outcomes to decide
whether each verdict is assertable, or whether the run must be marked *Unable to
Verify*.

Confidence is a **first-class gate on assertability**, separate from the score,
exactly as the engines report it. This stage does not recompute engine
confidence — it interprets it to decide whether a verdict can honestly be
stated.

**Interpretation rules (Document 3, §8).**

| Situation | Behavior |
|---|---|
| **High score + low confidence** | The favorable score cannot be asserted. Trust-relevant → routes toward *Unable to Verify*; quality → contribution down-weighted and flagged low-confidence. **Never upgraded to Trusted on unverified strength.** |
| **Low score + high confidence** | A confident negative. Asserted firmly — drives *Untrusted* (if trust-relevant and gating) or *Needs Revision* / lower Quality. |
| **Conflicting confidence across dimensions** | Weight each contribution by its own confidence; a low-confidence dimension cannot outweigh a high-confidence one. If the conflict sits on a trust-relevant dimension and cannot be resolved, escalate that dimension to *Unable to Verify*. |
| **Low overall confidence** | If trust-relevant dimensions collectively fail to reach the minimum needed to assert a Trust Verdict, the Overall Verdict becomes *Unable to Verify*. |

**When *Unable to Verify* applies.** No qualifying Critical Finding is present
(so it is not *Untrusted*), **but** one or more trust-relevant dimensions cannot
be asserted with sufficient confidence — evidence could not be retrieved, a
Trust or Hybrid result is missing or invalid, or confidence on a gating
dimension falls below the minimum.

*Unable to Verify* is an **honest-uncertainty verdict, not a failure verdict.*
It says trust is *undetermined*, not that the content failed, and it routes to
human review. Thresholds are configuration; the principle — *insufficient
confidence on a trust dimension blocks a Trusted verdict* — is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.config import DecisionSettings
from app.core.constants import DIMENSION_SPECS, TRUST_RELEVANT_DIMENSIONS
from app.core.logging import bind, get_logger
from app.shared.confidence_service import (
    ConfidenceService,
    ConfidenceSignal,
    DefaultConfidenceService,
    signal,
)
from app.shared.schemas import (
    AuditResult,
    ConfidenceReport,
    DimensionType,
    QualityVerdict,
    TrustOutcome,
    TrustVerdict,
)

__all__ = ["IntegratedConfidence", "integrate"]

logger = get_logger(__name__)

#: How much each dimension's own confidence counts toward the overall figure.
#:
#: Trust-relevant dimensions dominate because the Overall Verdict is trust-led
#: (Document 3, §11): the auditor's confidence in its answer is mostly its
#: confidence in the trust half. A perfectly-measured Readability cannot make up
#: for an Accuracy nobody could check.
_TYPE_WEIGHT: dict[DimensionType, float] = {
    DimensionType.TRUST: 3.0,
    DimensionType.HYBRID: 2.0,
    DimensionType.QUALITY: 1.0,
}


@dataclass(frozen=True)
class IntegratedConfidence:
    """The result of Stage 7.

    Attributes:
        report: Per-dimension and overall confidence for the Final Audit Report.
        trust_assertable: Whether the Trust Verdict may be stated as-is. False
            escalates the run to *Unable to Verify* — unless trust is already
            gated to *Untrusted*, which a confidence gap never overturns. An
            established critical failure does not become uncertain just because
            another dimension was hard to measure.
        trust_verdict: The Trust Verdict after confidence overlay, possibly
            escalated to *Unable to Verify*.
        explanation: Why the overall confidence is what it is, weakest signal
            first. Every figure in the report traces to this sentence, which is
            what Document 3 §13 means by reconstructable.
    """

    report: ConfidenceReport
    trust_assertable: bool
    trust_verdict: TrustVerdict
    explanation: str = ""


def _overall_signals(
    results: Mapping[str, AuditResult],
    excluded: Sequence[str],
    violations: Mapping[str, Sequence[str]],
    settings: DecisionSettings,
) -> list[ConfidenceSignal]:
    """Build the signals behind the overall confidence figure.

    Five kinds, covering what Document 3 §8 says confidence must account for:
    engine confidence, verification coverage, missing information, degraded
    engines, and structural validity.

    N/A dimensions contribute **no signal**. An inapplicable dimension is
    excluded from aggregation entirely (§9), and that has to include this one:
    Diversity reporting 0.9 confidence in its *inapplicability* is a real
    judgment, but it is not evidence that the content was well audited, and
    letting it lift the overall figure would let an N/A quietly buy confidence.
    """
    signals: list[ConfidenceSignal] = []
    excluded_set = set(excluded)

    # -- 1. Each engine's own confidence, weighted by how much it matters. -- #
    for dimension, result in sorted(results.items()):
        if dimension in excluded_set:
            continue
        spec = DIMENSION_SPECS.get(dimension)
        weight = _TYPE_WEIGHT[spec.dimension_type] if spec else 1.0
        signals.append(
            signal(
                f"confidence:{dimension}",
                result.confidence,
                weight=weight,
                rationale=(
                    f"{dimension} reported {result.confidence:.0%} confidence in "
                    "its own judgment"
                ),
            )
        )

    # -- 2. Verification coverage across the trust-relevant half. ---------- #
    trust_dims = [d for d in TRUST_RELEVANT_DIMENSIONS if d not in excluded_set]
    if trust_dims:
        covered = sum(
            1
            for d in trust_dims
            if d in results and results[d].confidence >= settings.min_trust_confidence
        )
        signals.append(
            signal(
                "trust_verification_coverage",
                covered / len(trust_dims),
                weight=3.0,
                rationale=(
                    f"{covered} of {len(trust_dims)} trust-relevant dimensions "
                    f"reached the {settings.min_trust_confidence:.2f} confidence "
                    "needed to assert a verdict"
                ),
            )
        )

    # -- 3. Missing information: dimensions that produced no result at all. - #
    missing = [d for d in DIMENSION_SPECS if d not in results]
    if missing:
        signals.append(
            signal(
                "results_complete",
                1.0 - (len(missing) / len(DIMENSION_SPECS)),
                weight=3.0,
                rationale=(
                    f"{', '.join(sorted(missing))} produced no result at all, so "
                    "the audit is incomplete"
                ),
            )
        )

    # -- 4. Degraded engines — a measurement that did not happen. ---------- #
    degraded = sorted(
        d
        for d, r in results.items()
        if d not in excluded_set and r.confidence == 0.0
    )
    if degraded:
        signals.append(
            signal(
                "engines_sound",
                1.0 - (len(degraded) / max(len(results) - len(excluded_set), 1)),
                weight=2.0,
                rationale=(
                    f"{', '.join(degraded)} could not be evaluated and support no "
                    "conclusion"
                ),
            )
        )

    # -- 5. Structural validity of the contract itself. -------------------- #
    if violations:
        signals.append(
            signal(
                "results_contract_valid",
                1.0 - (len(violations) / max(len(results), 1)),
                weight=2.0,
                rationale=(
                    f"{', '.join(sorted(violations))} returned a result violating "
                    "the AuditResult contract, so it cannot be read as authoritative"
                ),
            )
        )

    return signals


def _evidence_backed(result: AuditResult) -> bool:
    """Whether a result's conclusions point at anything a reader can inspect.

    Evidence quality, in the only form the ``AuditResult`` contract exposes to
    this layer: a dimension that reported a real measurement but collected no
    evidence has asserted something it cannot show. The Decision Engine never
    generates evidence (§1), so this reads; it does not repair.
    """
    return bool(result.evidence) or result.confidence == 0.0


def integrate(
    results: Mapping[str, AuditResult],
    trust_verdict: TrustVerdict,
    quality_verdict: QualityVerdict,
    settings: DecisionSettings,
    excluded: Sequence[str] = (),
    violations: Mapping[str, Sequence[str]] | None = None,
    confidence: ConfidenceService | None = None,
) -> IntegratedConfidence:
    """Overlay confidence on the trust and quality outcomes.

    Reuses the shared §5.10 Confidence Estimator rather than reimplementing the
    arithmetic, so a confidence figure in the report is combined the same way an
    engine combines its own — one weighted mean over named, individually
    explainable signals, re-derivable by hand (Document 3, §13).

    Args:
        results: All eight results, keyed by dimension. Includes the excluded
            ones — an N/A dimension still reports confidence, and the report
            shows it.
        trust_verdict: Stage 5's output.
        quality_verdict: Stage 6's output.
        settings: Supplies ``min_trust_confidence``.
        excluded: Dimensions excluded as N/A, from Stage 3.
        violations: Contract violations by dimension, from Stage 2's validation.
        confidence: The shared Confidence Estimator. Injected; defaults to the
            standard implementation, which is stateless and pure.

    Returns:
        The confidence report and the possibly-escalated Trust Verdict.
    """
    service = confidence or DefaultConfidenceService()
    problems = dict(violations or {})
    excluded_set = set(excluded)

    signals = _overall_signals(results, excluded, problems, settings)
    overall = service.estimate(signals)
    explanation = service.explain(signals)

    per_dimension = {d: r.confidence for d, r in results.items()}
    low_confidence = sorted(
        d
        for d, r in results.items()
        if d not in excluded_set and r.confidence < settings.min_trust_confidence
    )

    # -- Assertability. --------------------------------------------------- #
    #
    # An established critical failure never becomes uncertain because some other
    # dimension was hard to measure. Untrusted is a conclusion the auditor
    # reached on evidence it has; a confidence gap elsewhere does not unmake it.
    if trust_verdict.verdict is TrustOutcome.UNTRUSTED:
        return IntegratedConfidence(
            report=ConfidenceReport(
                overall=overall,
                per_dimension=per_dimension,
                unable_to_verify_rationale=None,
                low_confidence_dimensions=low_confidence,
            ),
            trust_assertable=True,
            trust_verdict=trust_verdict,
            explanation=explanation,
        )

    gaps: list[str] = []
    if trust_verdict.verdict is TrustOutcome.UNABLE_TO_VERIFY:
        gaps.append(trust_verdict.reason)

    invalid_trust = sorted(d for d in problems if d in TRUST_RELEVANT_DIMENSIONS)
    if invalid_trust:
        # Document 3 §4 stage 2: a structurally invalid result for a Trust or
        # Hybrid dimension is a verification gap — trust cannot be asserted on
        # incomplete measurement.
        gaps.append(
            f"{', '.join(invalid_trust)} returned a result that violates the "
            "AuditResult contract, so it cannot be read as a measurement."
        )

    unbacked_trust = sorted(
        d
        for d in TRUST_RELEVANT_DIMENSIONS
        if d in results and not _evidence_backed(results[d])
    )
    if unbacked_trust:
        gaps.append(
            f"{', '.join(unbacked_trust)} reported a measurement but collected no "
            "evidence, so its conclusion cannot be inspected."
        )

    if not gaps:
        return IntegratedConfidence(
            report=ConfidenceReport(
                overall=overall,
                per_dimension=per_dimension,
                unable_to_verify_rationale=None,
                low_confidence_dimensions=low_confidence,
            ),
            trust_assertable=True,
            trust_verdict=trust_verdict,
            explanation=explanation,
        )

    rationale = (
        "Trust is undetermined rather than failed: no qualifying Critical "
        "Finding is present, but the auditor cannot assert a verdict on the "
        "available evidence. " + " ".join(gaps)
    )
    logger.info(
        "trust escalated to Unable to Verify",
        extra=bind(
            was=trust_verdict.verdict.value,
            gaps=len(gaps),
            low_confidence=low_confidence,
            overall_confidence=round(overall, 3),
        ),
    )
    return IntegratedConfidence(
        report=ConfidenceReport(
            overall=overall,
            per_dimension=per_dimension,
            unable_to_verify_rationale=rationale,
            low_confidence_dimensions=low_confidence,
        ),
        trust_assertable=False,
        trust_verdict=TrustVerdict(
            verdict=TrustOutcome.UNABLE_TO_VERIFY,
            reason=rationale,
            evidence_refs=list(trust_verdict.evidence_refs),
            gating_finding_ids=[],
        ),
        explanation=explanation,
    )

