"""Stage 3 — Applicability Handling (Document 3, §9).

Partitions the eight results into *scored* and *N/A* sets so that a dimension
which legitimately does not apply neither helps nor harms the outcome.

The four rules, verbatim in intent from Document 3 §9:

1. **Detect via metadata, not via score.** A dimension is N/A only when
   ``metadata.applicable`` is False. An ``"N/A"`` score is always paired with it.
2. **Exclude from aggregation.** Removed entirely — not scored as zero, not
   counted in any denominator, not weighted.
3. **Preserve transparency.** Recorded in the report as *Not Applicable* with
   its ``applicability_reason``, so the exclusion is explicit and auditable.
4. **No trust impact.** Diversity is a Quality dimension with no critical-finding
   capability, so an N/A result can never affect the Trust Verdict.

Rule 2 is the one with teeth. Scoring an inapplicable dimension as zero would
unfairly depress the Quality Verdict; omitting it silently would hide a gap.
Explicit exclusion with a recorded reason is the only option that keeps the
verdict fair *and* the report honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.logging import bind, get_logger
from app.shared.schemas import NOT_APPLICABLE, AuditResult

__all__ = ["ApplicabilityPartition", "partition"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class ApplicabilityPartition:
    """The result of Stage 3.

    **Two sets, and only one of them is an exclusion.** ``scored`` and
    ``excluded`` are the partition Document 3 §9 defines; ``failed`` is a *view
    over* ``scored``, not a third bucket.

    That distinction is load-bearing. A dimension that *could not be measured* is
    still a dimension the audit was supposed to measure — excluding it the way an
    N/A dimension is excluded would quietly convert a verification gap into a
    non-event, and the gap is exactly what Document 3 §8 needs in order to reach
    *Unable to Verify*. So a failed dimension stays in ``scored``, where its zero
    confidence does the right thing everywhere: it weighs nothing in the
    compensatory Quality aggregate, and it blocks assertability in the
    non-compensatory Trust evaluation.

    An N/A dimension is the opposite case: it is excluded *by rule*, because the
    question did not apply. Nothing was missed.

    Attributes:
        scored: Results that participate in aggregation, keyed by dimension.
            Includes failed and low-confidence results — see above.
        excluded: Results excluded as N/A, keyed by dimension. Removed from
            aggregation entirely.
        reasons: ``applicability_reason`` per excluded dimension, carried
            through to the report so every exclusion is auditable.
        failed: The subset of ``scored`` that reported zero confidence — a
            measurement that did not happen (a degraded engine, per
            ``AuditEngine.degraded_result``). Diagnostic; these are *not*
            excluded.
    """

    scored: Mapping[str, AuditResult]
    excluded: Mapping[str, AuditResult]
    reasons: Mapping[str, str]
    failed: Mapping[str, AuditResult]

    @property
    def excluded_dimensions(self) -> tuple[str, ...]:
        """Names of the excluded dimensions, sorted."""
        return tuple(sorted(self.excluded))

    @property
    def failed_dimensions(self) -> tuple[str, ...]:
        """Names of the dimensions that could not be measured, sorted."""
        return tuple(sorted(self.failed))

    def low_confidence(self, threshold: float) -> tuple[str, ...]:
        """Scored dimensions whose confidence falls below ``threshold``.

        Includes the failed ones — zero confidence is below every threshold.

        The threshold is a parameter rather than a field because *"can this be
        asserted?"* is Stage 7's question, not Stage 3's (Document 3, §4 orders
        confidence integration after applicability). This method exposes the
        view; it does not make the call.

        Args:
            threshold: The confidence floor, e.g. ``min_trust_confidence``.

        Returns:
            The dimension names, sorted.
        """
        return tuple(
            sorted(d for d, r in self.scored.items() if r.confidence < threshold)
        )


def partition(results: Sequence[AuditResult]) -> ApplicabilityPartition:
    """Split results into scored and N/A sets.

    **Detects via metadata, never via score** (Document 3, §9 rule 1). A
    dimension is N/A only when ``metadata.applicable`` is False. Reading the
    score instead would be fragile in the one direction that matters: a
    contract-violating result carrying ``score="N/A"`` with ``applicable=True``
    would be silently excluded, and the run would lose a dimension without
    saying so.

    Args:
        results: The eight ``AuditResult`` objects.

    Returns:
        The partition, with reasons for every exclusion.
    """
    scored: dict[str, AuditResult] = {}
    excluded: dict[str, AuditResult] = {}
    reasons: dict[str, str] = {}
    failed: dict[str, AuditResult] = {}

    for result in results:
        dimension = result.metadata.dimension

        if not result.metadata.applicable:
            excluded[dimension] = result
            reasons[dimension] = (
                result.metadata.applicability_reason.strip()
                or "The engine reported this dimension as not applicable but "
                "supplied no reason."
            )
            continue

        scored[dimension] = result
        if result.confidence == 0.0:
            failed[dimension] = result

        if result.score == NOT_APPLICABLE:
            # applicable=True with an N/A score is a contract violation that
            # validate_contract() already reports. Log it and keep the dimension
            # scored: dropping it here would hide the defect and shrink the
            # denominator on the strength of a malformed result.
            logger.error(
                "result carries an N/A score while declaring itself applicable; "
                "keeping it scored so the contract violation stays visible",
                extra=bind(dimension=dimension),
            )

    logger.info(
        "applicability partitioned",
        extra=bind(
            scored=len(scored),
            excluded=sorted(excluded),
            failed=sorted(failed),
        ),
    )
    return ApplicabilityPartition(
        scored=scored, excluded=excluded, reasons=reasons, failed=failed
    )
