"""The Decision Engine's ordered pipeline (Document 3, §4).

This module is the "brain" of the auditor: it consumes the eight ``AuditResult``
objects and produces one explainable, evidence-backed decision.

**The ordering is deliberate, not incidental.** Applicability and Critical
Findings resolve *before* any scoring is interpreted, so a disqualifying
condition short-circuits the rest of the reasoning::

    Receive AuditResults
            ↓
    Validate Results
            ↓
    Handle Applicability (N/A)
            ↓
    Process Critical Findings
            ↓
    Trust Evaluation
            ↓
    Quality Evaluation
            ↓
    Confidence Integration
            ↓
    Recommendation Prioritization
            ↓
    Generate Final Verdict
            ↓
    Generate Audit Report

**What this engine may not do (Document 3, §1).** It never re-measures a
dimension, never overrides an engine's per-dimension score, and never generates
new evidence. It only *interprets* what the engines produced. Every
determination traces back to an ``AuditResult`` field.

**Verdict resolution order (Document 3, §11) — deterministic.**

1. A qualifying Critical Finding present → **Untrusted**.
2. Else trust-relevant dimensions lack sufficient confidence/evidence →
   **Unable to Verify**.
3. Else trust passes but quality or non-gating trust issues require correction →
   **Needs Revision**.
4. Else trust passes with only minor issues → **Trusted with Caveats**.
5. Else → **Trusted**.

This order guarantees that non-compensatory trust failures and honest
uncertainty are always resolved *before* any favorable verdict is considered.
Given the same inputs and configuration it is fully deterministic and
repeatable — only the engines' internal judgments carry model variability
(Document 3, §13), which is what makes this layer cheap and exhaustive to test
(Document 4, §10).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from app.core.config import Settings
from app.core.logging import bind, get_logger
from app.decision_engine import (
    applicability,
    confidence_integration,
    critical_findings,
    quality_eval,
    recommendations,
    trust_eval,
)
from app.shared.confidence_service import ConfidenceService, DefaultConfidenceService
from app.shared.schemas import (
    AuditResult,
    DecisionResult,
    DimensionSummary,
    OverallVerdict,
    QualityBand,
    QualityVerdict,
    TrustOutcome,
    TrustVerdict,
)

__all__ = ["DecisionEngine", "validate_results"]

logger = get_logger(__name__)


def validate_results(results: Sequence[AuditResult]) -> dict[str, list[str]]:
    """Stage 2 — confirm each result conforms to the AuditResult Contract.

    Checks required fields, populated metadata, and ``critical_findings``
    present as an array (empty is valid for engines with capability ``No``).

    Reports rather than raises, because Document 3 §4 gives an invalid result a
    specific downstream meaning: a structurally invalid or missing result for a
    **Trust or Hybrid** dimension is a verification gap that pushes the run
    toward *Unable to Verify* — "trust cannot be asserted on incomplete
    measurement". Raising would deny the caller that path.

    Args:
        results: The eight results.

    Returns:
        Contract violations keyed by dimension. Empty means all conform.
    """
    problems: dict[str, list[str]] = {}
    for result in results:
        violations = result.validate_contract()
        if violations:
            problems[result.metadata.dimension] = violations
    return problems


class DecisionEngine:
    """Executes the Document 3 §4 workflow over eight ``AuditResult`` objects.

    Depends only on the ``AuditResult`` contract, never on engine internals.
    That is the stable seam: revising a dimension that still conforms to the
    contract requires no change here beyond routing metadata (Document 3, §13).

    Args:
        settings: Supplies the decision thresholds and weights. Injected rather
            than imported so the gate logic can be tested across configurations.
    """

    def __init__(
        self, settings: Settings, confidence: ConfidenceService | None = None
    ) -> None:
        self._settings = settings
        self._confidence = confidence or DefaultConfidenceService()

    @property
    def decision_settings(self):
        """The decision thresholds and weights in force."""
        return self._settings.decision

    def decide(self, results: Sequence[AuditResult]) -> DecisionResult:
        """Run stages 1–9 and produce the cross-dimensional outcome.

        Composes the stage modules in the frozen Document 3 §4 order. **The
        order is the design**: applicability and critical findings resolve
        before any score is interpreted, so a disqualifying condition
        short-circuits the reasoning rather than being averaged against it.

        Args:
            results: The eight ``AuditResult`` objects for the content.

        Returns:
            The ``DecisionResult`` — Trust Verdict, Quality Verdict, Overall
            Verdict, integrated confidence, findings, and prioritized
            recommendations.
        """
        decision_settings = self._settings.decision
        by_dimension = {r.metadata.dimension: r for r in results}

        # -- Stage 2: Validate Results ------------------------------------ #
        violations = validate_results(results)
        if violations:
            logger.warning(
                "results violate the AuditResult contract; treating trust-relevant "
                "violations as verification gaps",
                extra=bind(dimensions=sorted(violations)),
            )

        # -- Stage 3: Handle Applicability (N/A) -------------------------- #
        partition = applicability.partition(results)

        # -- Stage 4: Process Critical Findings --------------------------- #
        findings = critical_findings.process(results, decision_settings)

        # -- Stage 5: Trust Evaluation ------------------------------------ #
        trust = trust_eval.evaluate(partition.scored, findings, decision_settings)

        # -- Stage 6: Quality Evaluation ---------------------------------- #
        #
        # Independent of Stage 5 by construction: it receives the partition and
        # the settings, and neither the trust verdict nor the findings. Quality
        # cannot read what Trust decided, so it cannot be coloured by it.
        quality = quality_eval.evaluate(
            partition.scored, partition, decision_settings
        )

        # -- Stage 7: Confidence Integration ------------------------------ #
        integrated = confidence_integration.integrate(
            by_dimension,
            trust,
            quality,
            decision_settings,
            excluded=partition.excluded_dimensions,
            violations=violations,
            confidence=self._confidence,
        )

        # -- Stage 8: Recommendation Prioritization ----------------------- #
        prioritized = recommendations.prioritize(by_dimension, findings.findings)

        # -- Stage 9: Generate Final Verdict ------------------------------ #
        revision_needed, revision_reasons = self._needs_revision(
            partition.scored, quality, decision_settings
        )
        overall = self.resolve_verdict(
            trust_is_gated=findings.trust_is_gated,
            trust_assertable=integrated.trust_assertable,
            needs_revision=revision_needed,
            has_minor_issues=self._has_minor_issues(
                integrated.trust_verdict, quality, prioritized
            ),
        )

        summaries = self._dimension_summaries(results, partition)
        summary = self._summary(
            overall,
            integrated.trust_verdict,
            quality,
            findings.gating,
            revision_reasons,
            partition,
        )

        logger.info(
            "decision complete",
            extra=bind(
                overall_verdict=overall.value,
                trust_verdict=integrated.trust_verdict.verdict.value,
                quality_band=quality.band.value,
                quality_score=quality.score,
                overall_confidence=round(integrated.report.overall, 3),
                critical_findings=len(findings.findings),
                gating=len(findings.gating),
                recommendations=len(prioritized),
                excluded=partition.excluded_dimensions,
                failed=partition.failed_dimensions,
            ),
        )

        return DecisionResult(
            overall_verdict=overall,
            trust_verdict=integrated.trust_verdict,
            quality_verdict=quality,
            summary=summary,
            confidence=integrated.report,
            critical_findings=list(findings.findings),
            recommendations=prioritized,
            dimension_summaries=summaries,
        )

    # -- Stage 9 helpers ---------------------------------------------------- #

    @staticmethod
    def _needs_revision(
        scored: Mapping[str, AuditResult],
        quality: QualityVerdict,
        settings,
    ) -> tuple[bool, list[str]]:
        """Whether the content requires correction before reliance (§11 step 3).

        Two independent triggers, matching §11's wording — *"quality or
        non-gating trust issues require correction"*:

        * a trust-relevant dimension below its pass threshold (the non-gating
          trust half — see :mod:`app.decision_engine.trust_eval`);
        * a Low quality band (the quality half).

        A Low band with ``score=None`` does **not** trigger it: that band is a
        fail-safe default for "nothing could be scored", not a measurement, and
        demanding revision on the strength of an absent number would invent a
        finding. The confidence report already tells that story honestly.
        """
        reasons: list[str] = []

        trust_weak, trust_reasons = trust_eval.requires_revision(scored, settings)
        if trust_weak:
            reasons.extend(trust_reasons)

        if quality.band is QualityBand.LOW and quality.score is not None:
            reasons.append(
                f"Quality banded Low at {quality.score:.2f}, below the "
                f"{settings.quality_bands['adequate']:.2f} adequate threshold"
            )

        return bool(reasons), reasons

    @staticmethod
    def _has_minor_issues(
        trust: TrustVerdict,
        quality: QualityVerdict,
        prioritized: Sequence,
    ) -> bool:
        """Whether minor, non-blocking issues exist (§11 step 4).

        Reached only when trust passes and nothing needs revision, so anything
        true here is by definition minor: caveated trust, a merely-adequate
        quality band, or any surviving recommendation. *Trusted* is reserved for
        content with nothing to say about it.
        """
        return (
            trust.verdict is TrustOutcome.TRUST_PASS_WITH_CAVEATS
            or quality.band is QualityBand.ADEQUATE
            or bool(prioritized)
        )

    # -- Report material ---------------------------------------------------- #

    @staticmethod
    def _dimension_summaries(
        results: Sequence[AuditResult],
        partition: applicability.ApplicabilityPartition,
    ) -> list[DimensionSummary]:
        """Build the per-dimension rows of the report (§12 "Dimension Results").

        Every rationale is derived **only** from ``AuditResult`` fields. The
        Decision Engine does not re-measure (§1), so it can describe what an
        engine reported and nothing more — the ledger and evidence counts are
        facts about the result, not a second opinion about the content.
        """
        rows: list[DimensionSummary] = []
        for result in results:
            meta = result.metadata
            dimension = meta.dimension

            if not meta.applicable:
                rationale = (
                    "Not applicable, so excluded from the Quality Verdict "
                    "entirely — it neither helps nor harms. "
                    f"{partition.reasons.get(dimension, '')}"
                ).strip()
            elif result.confidence == 0.0:
                rationale = (
                    "Could not be evaluated, so it supports no conclusion. This "
                    "is a verification gap, not a failing measurement."
                )
            else:
                parts = [
                    f"Scored {result.score:.2f} with {result.confidence:.0%} "
                    f"confidence over {len(result.ledger)} ledger "
                    f"{'entry' if len(result.ledger) == 1 else 'entries'}"
                    if isinstance(result.score, float)
                    else f"Reported {result.score} with "
                    f"{result.confidence:.0%} confidence"
                ]
                if result.critical_findings:
                    parts.append(
                        f"{len(result.critical_findings)} critical "
                        f"{'finding' if len(result.critical_findings) == 1 else 'findings'}"
                    )
                if result.recommendations:
                    parts.append(
                        f"{len(result.recommendations)} "
                        f"{'recommendation' if len(result.recommendations) == 1 else 'recommendations'}"
                    )
                rationale = "; ".join(parts) + "."

            rows.append(
                DimensionSummary(
                    dimension=dimension,
                    dimension_type=meta.dimension_type,
                    score=result.score,
                    confidence=result.confidence,
                    rationale=rationale,
                    applicable=meta.applicable,
                    applicability_reason=meta.applicability_reason,
                )
            )
        return rows

    @staticmethod
    def _summary(
        overall: OverallVerdict,
        trust: TrustVerdict,
        quality: QualityVerdict,
        gating: Sequence,
        revision_reasons: Sequence[str],
        partition: applicability.ApplicabilityPartition,
    ) -> str:
        """Write the plain-language statement for a decision-maker (§12).

        Leads with the verdict and the reason for it, because that is the
        question the reader arrived with. Trust and Quality are stated as two
        separate sentences — never fused into one judgment — which is §7's
        separation guarantee surviving all the way into the prose.
        """
        band = quality.band.value.lower()
        quality_sentence = (
            f"Quality is {band}"
            + (f" at {quality.score:.2f}" if quality.score is not None else "")
            + (
                " — reported independently of trust, and it neither raises nor "
                "lowers it."
                if overall is OverallVerdict.UNTRUSTED
                else "."
            )
        )

        if overall is OverallVerdict.UNTRUSTED:
            headline = (
                f"Do not rely on this content. {len(gating)} qualifying critical "
                f"{'finding' if len(gating) == 1 else 'findings'} "
                f"{'was' if len(gating) == 1 else 'were'} found, and a single one "
                "is disqualifying regardless of how the content scores elsewhere."
            )
        elif overall is OverallVerdict.UNABLE_TO_VERIFY:
            headline = (
                "Trust is undetermined — not failed. The auditor could neither "
                "confirm nor deny trustworthiness on the available evidence, so "
                "this content should go to a human reviewer rather than be "
                "treated as passed or rejected."
            )
        elif overall is OverallVerdict.NEEDS_REVISION:
            headline = (
                "This content is not reliable as-is, but the problems are fixable "
                "and no disqualifying failure was found. "
                + " ".join(f"{r}." for r in revision_reasons)
            )
        elif overall is OverallVerdict.TRUSTED_WITH_CAVEATS:
            headline = (
                "This content is trustworthy overall, with minor issues worth "
                "knowing about before relying on it."
            )
        else:
            headline = (
                "This content is trustworthy and well-made. No critical finding "
                "was raised, and every trust-relevant dimension passed with "
                "sufficient confidence to say so."
            )

        parts = [headline, f"Trust: {trust.reason}", quality_sentence]
        if partition.excluded_dimensions:
            parts.append(
                f"{', '.join(partition.excluded_dimensions)} did not apply to this "
                "content and was excluded from the Quality Verdict rather than "
                "counted against it."
            )
        if partition.failed_dimensions:
            parts.append(
                f"{', '.join(partition.failed_dimensions)} could not be measured; "
                "the confidence reported here accounts for that gap."
            )
        return " ".join(parts)

    def resolve_verdict(
        self,
        trust_is_gated: bool,
        trust_assertable: bool,
        needs_revision: bool,
        has_minor_issues: bool,
    ) -> OverallVerdict:
        """Stage 9 — apply the deterministic verdict resolution order.

        Implemented now, ahead of the stages that feed it, because it is the
        correctness core of the whole system: it is where non-compensatory trust
        and honest uncertainty are guaranteed to be resolved before any
        favorable verdict. It is pure, total, and exhaustively testable on its
        own (Document 4, §10).

        Args:
            trust_is_gated: A qualifying Critical Finding is present.
            trust_assertable: Trust-relevant dimensions carry sufficient
                confidence and evidence to state a verdict.
            needs_revision: Significant trust-relevant weaknesses or low quality
                require correction before reliance.
            has_minor_issues: Minor, non-blocking issues are present.

        Returns:
            The Overall Verdict from the fixed set.
        """
        if trust_is_gated:
            return OverallVerdict.UNTRUSTED
        if not trust_assertable:
            return OverallVerdict.UNABLE_TO_VERIFY
        if needs_revision:
            return OverallVerdict.NEEDS_REVISION
        if has_minor_issues:
            return OverallVerdict.TRUSTED_WITH_CAVEATS
        return OverallVerdict.TRUSTED
