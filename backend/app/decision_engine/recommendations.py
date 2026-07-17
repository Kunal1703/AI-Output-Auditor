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

import re
from typing import Mapping, Sequence

from app.core.constants import DIMENSION_SPECS
from app.core.logging import bind, get_logger
from app.shared.schemas import (
    SEVERITY_ORDER,
    AuditResult,
    CriticalFinding,
    DimensionType,
    PrioritizedRecommendation,
    Recommendation,
    RecommendationPriority,
    Severity,
)

__all__ = ["prioritize"]

logger = get_logger(__name__)

#: Trust → Hybrid → Quality, the second ordering key within a tier
#: (Document 3, §10).
_TYPE_RANK: dict[DimensionType, int] = {
    DimensionType.TRUST: 2,
    DimensionType.HYBRID: 1,
    DimensionType.QUALITY: 0,
}

#: Tier ordering for the final sort. Critical first.
_TIER_RANK: dict[RecommendationPriority, int] = {
    RecommendationPriority.CRITICAL: 3,
    RecommendationPriority.HIGH: 2,
    RecommendationPriority.MEDIUM: 1,
    RecommendationPriority.LOW: 0,
}

_WHITESPACE = re.compile(r"\s+")


def _tier(
    recommendation: Recommendation,
    dimension_type: DimensionType,
    finding_evidence: frozenset[str],
) -> RecommendationPriority:
    """Assign a recommendation's priority tier (Document 3, §10).

    **"Tied to a Critical Finding" is decided by shared evidence, not by
    guessing.** A recommendation earns the Critical tier when it points at the
    same evidence a Critical Finding points at — which is exactly what "tied to"
    means, and it is checkable rather than inferred from wording or severity.
    That keeps the top tier honest: an engine cannot talk its way into it, and a
    finding's remedy cannot fall out of it.

    The remaining tiers follow §10 directly: trust-relevant but non-gating is
    High; quality with material impact is Medium; polish is Low.
    """
    if finding_evidence and finding_evidence.intersection(recommendation.evidence_refs):
        return RecommendationPriority.CRITICAL

    if dimension_type in (DimensionType.TRUST, DimensionType.HYBRID):
        # A Trust or Hybrid dimension that raised no gating finding is still
        # speaking about trust — an unsupported claim, a weak source, a salient
        # gap. §10 puts all of that above any quality improvement.
        return RecommendationPriority.HIGH

    if SEVERITY_ORDER[recommendation.severity] >= SEVERITY_ORDER[Severity.MEDIUM]:
        return RecommendationPriority.MEDIUM
    return RecommendationPriority.LOW


def _dedupe_key(dimension: str, recommendation: Recommendation) -> tuple[str, str]:
    """The identity of a recommendation, for duplicate detection.

    ``(dimension, normalized text)``. **Scoped to one dimension deliberately.**
    Two engines independently advising the same action is signal, not noise: it
    means two different measurements converged, and a reader deserves to see
    both. Merging them would also force the report to name one engine as the
    source and drop the other, because ``PrioritizedRecommendation.dimension``
    is a single field in the frozen §12 report — so the merge would trade a
    truthful duplicate for a misattributed singleton.

    Within one dimension, the same text twice is a genuine duplicate.
    """
    return (dimension, _WHITESPACE.sub(" ", recommendation.text).strip().lower())


def prioritize(
    results: Mapping[str, AuditResult],
    findings: Sequence[CriticalFinding],
) -> list[PrioritizedRecommendation]:
    """Merge and order every engine recommendation.

    Orders and binds; never rewrites or invents. The text is carried through
    verbatim from the engine that authored it (Document 3, §1 and §10).

    Args:
        results: All eight results, keyed by dimension.
        findings: The severity-ordered Critical Findings from Stage 4. Used to
            identify which recommendations earn the Critical tier by being tied
            to a finding.

    Returns:
        The prioritized list, Critical → High → Medium → Low, each entry bound
        to its evidence. Recommendations with no traceable evidence are dropped
        rather than emitted unbacked.
    """
    finding_evidence = frozenset(
        ref for finding in findings for ref in finding.evidence_refs
    )

    seen: dict[tuple[str, str], PrioritizedRecommendation] = {}
    dropped_unbacked = 0
    duplicates = 0

    for dimension, result in results.items():
        spec = DIMENSION_SPECS.get(dimension)
        dimension_type = spec.dimension_type if spec else DimensionType.QUALITY

        for recommendation in result.recommendations:
            if not recommendation.evidence_refs:
                # Document 3 §10: "A recommendation without traceable evidence is
                # not emitted." The engines already enforce this at creation
                # (RecommendationService drops them), so reaching here means a
                # result was assembled some other way. Drop it — an unbacked
                # action item is one the reader cannot check, and the whole
                # report is evidence-first or it is nothing.
                dropped_unbacked += 1
                logger.warning(
                    "dropping recommendation with no traceable evidence",
                    extra=bind(
                        dimension=dimension,
                        recommendation_id=recommendation.recommendation_id,
                    ),
                )
                continue

            key = _dedupe_key(dimension, recommendation)
            tier = _tier(recommendation, dimension_type, finding_evidence)
            existing = seen.get(key)

            if existing is None:
                seen[key] = PrioritizedRecommendation(
                    priority=tier,
                    dimension=dimension,
                    text=recommendation.text,
                    evidence_refs=list(recommendation.evidence_refs),
                    source_severity=recommendation.severity,
                )
                continue

            # A genuine duplicate from one engine: keep the stronger tier and
            # severity, and union the evidence so the merge loses no pointer.
            duplicates += 1
            seen[key] = existing.model_copy(
                update={
                    "priority": max(
                        existing.priority, tier, key=lambda p: _TIER_RANK[p]
                    ),
                    "source_severity": max(
                        existing.source_severity,
                        recommendation.severity,
                        key=lambda s: SEVERITY_ORDER[s],
                    ),
                    "evidence_refs": list(
                        dict.fromkeys(
                            [*existing.evidence_refs, *recommendation.evidence_refs]
                        )
                    ),
                }
            )

    def order(item: PrioritizedRecommendation) -> tuple:
        spec = DIMENSION_SPECS.get(item.dimension)
        dimension_type = spec.dimension_type if spec else DimensionType.QUALITY
        confidence = results[item.dimension].confidence if item.dimension in results else 0.0
        return (
            _TIER_RANK[item.priority],
            SEVERITY_ORDER[item.source_severity],
            _TYPE_RANK[dimension_type],
            confidence,  # act on confident findings first (§10)
            # Stable, total tie-break so the report is byte-identical across runs.
            item.dimension,
        )

    ordered = sorted(seen.values(), key=order, reverse=True)

    logger.info(
        "recommendations prioritized",
        extra=bind(
            total=len(ordered),
            critical=sum(
                1 for r in ordered if r.priority is RecommendationPriority.CRITICAL
            ),
            high=sum(1 for r in ordered if r.priority is RecommendationPriority.HIGH),
            duplicates_merged=duplicates,
            dropped_unbacked=dropped_unbacked,
        ),
    )
    return ordered
