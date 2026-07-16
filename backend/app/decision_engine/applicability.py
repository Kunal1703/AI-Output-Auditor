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

from app.shared.schemas import AuditResult

__all__ = ["ApplicabilityPartition", "partition"]


@dataclass(frozen=True)
class ApplicabilityPartition:
    """The result of Stage 3.

    Attributes:
        scored: Results that participate in aggregation, keyed by dimension.
        excluded: Results excluded as N/A, keyed by dimension.
        reasons: ``applicability_reason`` per excluded dimension, carried
            through to the report so every exclusion is auditable.
    """

    scored: Mapping[str, AuditResult]
    excluded: Mapping[str, AuditResult]
    reasons: Mapping[str, str]

    @property
    def excluded_dimensions(self) -> tuple[str, ...]:
        """Names of the excluded dimensions, sorted."""
        return tuple(sorted(self.excluded))


def partition(results: Sequence[AuditResult]) -> ApplicabilityPartition:
    """Split results into scored and N/A sets.

    Args:
        results: The eight ``AuditResult`` objects.

    Returns:
        The partition, with reasons for every exclusion.

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Applicability partitioning is implemented in Milestone 2 "
        "(Document 3, §9)."
    )
