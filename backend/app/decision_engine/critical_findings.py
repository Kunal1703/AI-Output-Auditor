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

import re
from dataclasses import dataclass
from typing import Sequence

from app.core.config import DecisionSettings
from app.core.constants import DIMENSION_SPECS
from app.core.logging import bind, get_logger
from app.shared.schemas import (
    SEVERITY_ORDER,
    AuditResult,
    CriticalFinding,
    CriticalFindingCapability,
    DimensionType,
)

__all__ = ["CriticalFindingOutcome", "process"]

logger = get_logger(__name__)

#: Trust ahead of Hybrid, per Document 3 §5's second ordering key. Quality is
#: present only for completeness — a Quality dimension's finding never reaches
#: the ordering, because it never reaches this stage at all.
_TYPE_RANK: dict[DimensionType, int] = {
    DimensionType.TRUST: 2,
    DimensionType.HYBRID: 1,
    DimensionType.QUALITY: 0,
}

_WHITESPACE = re.compile(r"\s+")


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


def _dimension_type(dimension: str) -> DimensionType:
    """Read a dimension's frozen routing class.

    Reads ``core.constants`` — the transcribed Document 2 §4.1 matrix — rather
    than the finding's own result, so a finding cannot influence its own
    ordering priority. Unknown dimensions sort last rather than raising: an
    unrecognized name is a defect, and losing the finding would be a worse
    response to it than mis-ranking it.
    """
    spec = DIMENSION_SPECS.get(dimension)
    return spec.dimension_type if spec else DimensionType.QUALITY


def _dedupe_key(finding: CriticalFinding) -> tuple[str, str, str]:
    """The identity of a finding, for duplicate detection.

    ``(dimension, type, normalized description)``. **Deliberately includes the
    dimension**, so findings from two different engines are never merged even
    when they read alike. Accuracy's "contradicted claim" and Credibility's
    "misattributed citation" about the same sentence are two distinct failures
    with two distinct remedies, and collapsing them would delete one of them
    from the report.

    What this *does* catch is one engine emitting the same finding twice —
    which is the duplicate Document 3 §2 asks to be removed.
    """
    return (
        finding.dimension,
        finding.type.strip().lower(),
        _WHITESPACE.sub(" ", finding.description).strip().lower(),
    )


def _merge(existing: CriticalFinding, duplicate: CriticalFinding) -> CriticalFinding:
    """Fold a duplicate into the finding it duplicates, losing nothing.

    Evidence is **unioned**, never replaced: Document 3 §12 requires every
    finding to carry the evidence that proves it, and a merge that dropped one
    copy's pointers would make the surviving finding less traceable than the two
    it replaced. Severity and centrality take the *maximum* — if the engine
    reported the same issue at two severities, the gate must see the higher one,
    because the alternative is a merge that un-gates trust.
    """
    refs = list(dict.fromkeys([*existing.evidence_refs, *duplicate.evidence_refs]))
    severity = max(
        existing.severity, duplicate.severity, key=lambda s: SEVERITY_ORDER[s]
    )
    centralities = [
        c for c in (existing.centrality, duplicate.centrality) if c is not None
    ]
    return existing.model_copy(
        update={
            "evidence_refs": refs,
            "severity": severity,
            "centrality": max(centralities) if centralities else None,
        }
    )


def process(
    results: Sequence[AuditResult], settings: DecisionSettings
) -> CriticalFindingOutcome:
    """Collect, deduplicate, order, and gate on Critical Findings.

    Args:
        results: The eight ``AuditResult`` objects. Engines with capability
            ``No`` contribute nothing here — a Quality dimension can never gate
            trust (Document 3, §5).
        settings: Supplies ``trust_blocking_severity``. The threshold is
            deployment configuration; the rule that a qualifying finding gates
            trust is fixed.

    Returns:
        The ordered findings and the gating subset.
    """
    collected: dict[tuple[str, str, str], CriticalFinding] = {}
    duplicates = 0

    for result in results:
        capability = result.metadata.critical_finding_capability
        if not result.critical_findings:
            continue

        if capability is not CriticalFindingCapability.YES:
            # A Quality dimension can never gate trust (Document 3, §5), and
            # that invariant outranks any finding it managed to emit. Both
            # AuditEngine.run() and validate_contract() should have caught this
            # upstream, so reaching here is a real defect — drop the findings so
            # the invariant holds, and log loudly so the defect is visible
            # rather than silently honoured.
            logger.error(
                "dropping critical findings from an engine whose capability is "
                "not Yes; a Quality dimension must never gate trust",
                extra=bind(
                    dimension=result.metadata.dimension,
                    capability=capability.value,
                    dropped=len(result.critical_findings),
                ),
            )
            continue

        for finding in result.critical_findings:
            key = _dedupe_key(finding)
            existing = collected.get(key)
            if existing is None:
                collected[key] = finding
            else:
                collected[key] = _merge(existing, finding)
                duplicates += 1

    # Severity, then Trust ahead of Hybrid, then centrality — Document 3 §5's
    # three keys, applied in that order. finding_id breaks any remaining tie so
    # the ordering is total and the report is byte-stable across runs.
    ordered = tuple(
        sorted(
            collected.values(),
            key=lambda f: (
                SEVERITY_ORDER[f.severity],
                _TYPE_RANK[_dimension_type(f.dimension)],
                f.centrality if f.centrality is not None else 0.0,
                f.finding_id,
            ),
            reverse=True,
        )
    )

    blocking = SEVERITY_ORDER[settings.trust_blocking_severity]
    gating = tuple(f for f in ordered if SEVERITY_ORDER[f.severity] >= blocking)

    logger.info(
        "critical findings processed",
        extra=bind(
            findings=len(ordered),
            gating=len(gating),
            duplicates_merged=duplicates,
            dimensions=sorted({f.dimension for f in ordered}),
            blocking_severity=settings.trust_blocking_severity.value,
        ),
    )
    return CriticalFindingOutcome(findings=ordered, gating=gating)
