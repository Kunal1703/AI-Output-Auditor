"""Stage 8 — Recommendation Prioritization (Document 3, §10).

Merges the ``recommendations`` from all engines into a single, ordered,
evidence-backed action list. This stage **does not rewrite or invent
recommendations** — it orders and binds the ones the engines produced. Authoring
belongs to the engines (Document 3, §1).

**Priority tiers.**

* **Critical** — tied to a Critical Finding (fabricated/misattributed citation,
  contradicted claim, violated hard requirement, critical omission).
  Trust-blocking; listed first.
* **High** — from Trust or Hybrid dimensions, addressing non-gating but
  trust-relevant issues (unsupported-but-not-contradicted claims, low-credibility
  sources, salient coverage gaps).
* **Medium** — quality improvements with material impact on usefulness or
  clarity (Readability, Engagement, Coverage partials).
* **Low** — polish (minor redundancy, stylistic clarity).

**Ordering within a tier.** By source severity, then dimension type
(Trust → Hybrid → Quality), then confidence — act on confident findings first.

**Evidence requirement.** Every recommendation must carry a pointer to the
``evidence`` and/or ``ledger`` entry that motivated it. *A recommendation
without traceable evidence is not emitted.* This is what enforces evidence-first
end to end: the reader can always see **why** each action is advised.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from app.shared.schemas import AuditResult, CriticalFinding, PrioritizedRecommendation

__all__ = ["prioritize"]


def prioritize(
    results: Mapping[str, AuditResult],
    findings: Sequence[CriticalFinding],
) -> list[PrioritizedRecommendation]:
    """Merge and order every engine recommendation.

    Args:
        results: All eight results, keyed by dimension.
        findings: The severity-ordered Critical Findings from Stage 4. Used to
            identify which recommendations earn the Critical tier by being tied
            to a finding.

    Returns:
        The prioritized list, Critical → High → Medium → Low, each entry bound
        to its evidence. Recommendations with no traceable evidence are dropped
        rather than emitted unbacked.

    Raises:
        NotImplementedError: Until Milestone 2.
    """
    raise NotImplementedError(
        "Recommendation Prioritization is implemented in Milestone 2 "
        "(Document 3, §10)."
    )
