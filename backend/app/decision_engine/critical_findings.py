"""Stage 4 — Critical Finding Processing (Document 3, §5).

Gathers every ``critical_findings`` entry from the four capable engines
(Relevance, Accuracy, Coverage-as-Critical-Omissions, Credibility),
severity-orders them, and evaluates the non-compensatory gate.

**This stage runs before any scoring is interpreted.** That ordering is the
whole design: a disqualifying condition short-circuits the reasoning, so a
fabricated citation cannot be averaged away by a strong Readability score. It is
why Stage 4 precedes Stages 5 and 6 in the frozen workflow.

**Ordering (Document 3, §5).**

1. Severity, as supplied by the emitting engine — highest first.
2. Dimension type as tiebreaker: Trust (Accuracy, Credibility) ahead of Hybrid
   (Relevance, Coverage).
3. Centrality/salience where the source engine provided it — a hallucination in
   a load-bearing claim outranks one in an incidental aside.

**The gate is on presence and severity, not count.** One finding at or above the
configured blocking severity is sufficient. Two low-severity findings do not
"add up" to a trust block unless one independently meets the threshold.

**All findings are retained.** None are discarded or collapsed into a score. The
gate fires on the highest-severity finding, but the full set flows to the report
and the recommendations, so the reader sees every issue rather than only the
gating one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.core.config import DecisionSettings
from app.shared.schemas import AuditResult, CriticalFinding

__all__ = ["CriticalFindingOutcome", "process"]


@dataclass(frozen=True)
class CriticalFindingOutcome:
    """The result of Stage 4.

    Attributes:
        findings: Every finding from every capable engine, severity-ordered.
            The full set — nothing is dropped.
        gating: The findings meeting or exceeding the configured blocking
            severity. Non-empty means the Trust Verdict is forced to
            *Untrusted*, and no later stage may override it.
    """

    findings: tuple[CriticalFinding, ...]
    gating: tuple[CriticalFinding, ...]

    @property
    def trust_is_gated(self) -> bool:
        """Whether a qualifying finding forces *Untrusted*."""
        return bool(self.gating)


def process(
    results: Sequence[AuditResult], settings: DecisionSettings
) -> CriticalFindingOutcome:
    """Collect, order, and gate on Critical Findings.

    Args:
        results: The eight ``AuditResult`` objects. Engines with capability
            ``No`` contribute nothing here — a Quality dimension can never gate
            trust (Document 3, §5).
        settings: Supplies ``trust_blocking_severity``. The threshold is
            deployment configuration; the rule that a qualifying finding gates
            trust is fixed.

    Returns:
        The ordered findings and the gating subset.

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Critical Finding processing is implemented in Milestone 2 "
        "(Document 3, §5)."
    )
