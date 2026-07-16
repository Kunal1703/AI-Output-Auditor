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

from typing import Sequence

from app.core.config import Settings
from app.core.logging import get_logger
from app.shared.schemas import AuditResult, DecisionResult, OverallVerdict

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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def decision_settings(self):
        """The decision thresholds and weights in force."""
        return self._settings.decision

    def decide(self, results: Sequence[AuditResult]) -> DecisionResult:
        """Run stages 1–9 and produce the cross-dimensional outcome.

        The Milestone 2 implementation composes the stage modules in the frozen
        order — ``validate_results``, ``applicability.partition``,
        ``critical_findings.process``, ``trust_eval.evaluate``,
        ``quality_eval.evaluate``, ``confidence_integration.integrate``,
        ``recommendations.prioritize``, then :meth:`resolve_verdict`. Each stage
        already has its contract fixed in its own module.

        Args:
            results: The eight ``AuditResult`` objects for the content.

        Returns:
            The ``DecisionResult`` — Trust Verdict, Quality Verdict, Overall
            Verdict, integrated confidence, findings, and prioritized
            recommendations.

        Raises:
            NotImplementedError: Until Milestone 2.
        """
        raise NotImplementedError(
            "The Decision Engine workflow is implemented in Milestone 2 "
            "(Document 3, §4). Its stage modules are defined in this package."
        )

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
