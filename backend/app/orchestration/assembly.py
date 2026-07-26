"""Assembly — projecting metric results into the finalized contracts (MB4).

Pure projection over already-computed results: no evaluator is re-run, no
evidence is re-recorded. Turns one output's :class:`MetricResult` set plus its
:class:`~app.orchestration.decision.DecisionOutcome` into an :class:`OutputAudit`,
and a set of ``OutputAudit`` objects into a :class:`Comparison` and the final
:class:`ComparativeReport`.

Every ``Finding`` keeps its ``evidence_refs`` verbatim, and recommendations are
derived from findings (each carrying that finding's evidence), so the evidence
graph assembled in MB2/MB3 is preserved end to end.
"""

from __future__ import annotations

from app.orchestration.decision import _BAND_RANK, DecisionOutcome
from app.shared.confidence_service import ConfidenceService, signal
from app.shared.evidence_store import EvidenceStore
from app.shared.schemas import (
    Comparison,
    ComparisonRow,
    ComparativeReport,
    ConfidenceReport,
    Finding,
    FINDING_SEVERITY_ORDER,
    FindingSeverity,
    FindingType,
    Layer,
    MetricResult,
    OutputAudit,
    OutputType,
    PrioritizedRecommendation,
    Producer,
    RecommendationPriority,
    Severity,
    SourceMeta,
    VerdictBand,
)

__all__ = [
    "assemble_output_audit",
    "build_comparison",
    "build_comparative_report",
]

#: FindingSeverity → (recommendation priority, legacy source severity).
_REC_PRIORITY: dict[FindingSeverity, tuple[RecommendationPriority, Severity]] = {
    FindingSeverity.CRITICAL: (RecommendationPriority.CRITICAL, Severity.CRITICAL),
    FindingSeverity.MAJOR: (RecommendationPriority.HIGH, Severity.HIGH),
    FindingSeverity.MINOR: (RecommendationPriority.LOW, Severity.LOW),
}

#: FindingType → an action verb for the recommendation text.
_REC_ACTION: dict[FindingType, str] = {
    FindingType.CONTRADICTION: "Correct or remove the claim that contradicts the source",
    FindingType.INTRINSIC_HALLUCINATION: "Correct or remove the fabricated claim",
    FindingType.EXTRINSIC_HALLUCINATION: "Ground or remove the unsupported claim",
    FindingType.UNSUPPORTED_CLAIM: "Ground or remove the unsupported claim",
    FindingType.NUMERIC_ERROR: "Correct the inaccurate figure to match the source",
    FindingType.UNSUPPORTED_INFERENCE: "Support or qualify the ungrounded inference",
    FindingType.MISSING_CRITICAL_FACT: "Add the omitted high-salience fact",
    FindingType.MEANING_DISTORTION: "Restore the source's meaning",
    FindingType.CONTEXT_LOSS: "Restore the dropped essential context",
    FindingType.INTRODUCED_BIAS: "Neutralize the introduced loaded language",
    FindingType.REDUNDANCY: "Cut or merge the redundant passage",
    FindingType.READABILITY_ISSUE: "Improve the flagged readability issue",
    FindingType.STRUCTURE_ISSUE: "Improve the output's structure",
}


def assemble_output_audit(
    output_id: str,
    producer: Producer,
    output_type: OutputType,
    metric_results: list[MetricResult],
    faithfulness_id: str,
    attribution_entries: list,
    decision: DecisionOutcome,
    confidence_service: ConfidenceService,
    evidence_store: EvidenceStore,
    min_confidence: float,
) -> OutputAudit:
    """Project one output's results into an :class:`OutputAudit`.

    Args:
        output_id: The output's id.
        producer: Who produced it.
        output_type: The kind of output.
        metric_results: Every metric result for this output.
        faithfulness_id: The metric_id of the headline Faithfulness result.
        attribution_entries: The serializable attribution map
            (``AttributionResult.schema_entries``).
        decision: The verdict from the Decision Engine.
        confidence_service: Shared confidence estimator (reused for the overall).
        evidence_store: The run-scoped store, read to inline each metric's
            referenced evidence so the report resolves without it.
        min_confidence: Threshold below which a metric is flagged low-confidence.

    Returns:
        The fully populated ``OutputAudit``.
    """
    # Inline the evidence each metric's findings reference, so the report is
    # self-contained (the run-scoped store is discarded after assembly). This is
    # a pure projection — no finding's evidence_refs change.
    populated = [_attach_evidence(m, evidence_store) for m in metric_results]
    faithfulness = next(m for m in populated if m.metric_id == faithfulness_id)

    layer_results = _group_by_layer(populated)
    findings = _ordered_findings(populated)
    recommendations = _recommendations(findings)
    confidence = _confidence_report(
        populated, decision, confidence_service, min_confidence
    )

    return OutputAudit(
        output_id=output_id,
        producer=producer,
        output_type=output_type,
        verdict=decision.verdict,
        verdict_reason=decision.reason,
        layer_results=layer_results,
        faithfulness=faithfulness,
        confidence=confidence,
        findings=findings,
        recommendations=recommendations,
        attribution=attribution_entries,
    )


def _attach_evidence(metric: MetricResult, store: EvidenceStore) -> MetricResult:
    """Return a copy of ``metric`` with the evidence its findings reference.

    The evidence lives in the run-scoped store keyed by id; here it is resolved
    and carried on the ``MetricResult`` so every ``Finding.evidence_refs`` id
    resolves within the report itself. Missing ids are simply skipped — a
    dangling ref is a traceability note, never a crash.
    """
    ref_ids = {ref for finding in metric.findings for ref in finding.evidence_refs}
    if not ref_ids:
        return metric
    found, _missing = store.resolve(ref_ids)
    return metric.model_copy(update={"evidence": found})


def _group_by_layer(metric_results: list[MetricResult]):
    """Group metric results into the ``LayerResults`` structure."""
    from app.shared.schemas import LayerResults

    return LayerResults(
        layer_1=[m for m in metric_results if m.layer is Layer.L1_GROUNDING],
        layer_2=[m for m in metric_results if m.layer is Layer.L2_INFO],
        layer_3=[m for m in metric_results if m.layer is Layer.L3_PRESENTATION],
    )


def _ordered_findings(metric_results: list[MetricResult]) -> list[Finding]:
    """All findings across all metrics, most-severe first, evidence intact."""
    findings = [f for m in metric_results for f in m.findings]
    findings.sort(
        key=lambda f: (FINDING_SEVERITY_ORDER[f.severity], f.centrality or 0.0),
        reverse=True,
    )
    return findings


def _recommendations(findings: list[Finding]) -> list[PrioritizedRecommendation]:
    """Derive prioritized recommendations from findings, evidence preserved.

    One recommendation per finding, tied to that finding's evidence (Document 3
    §10 forbids an evidence-less recommendation, and every finding here carries
    evidence). Ordered Critical → High → Medium → Low.
    """
    recs: list[PrioritizedRecommendation] = []
    for index, finding in enumerate(findings, start=1):
        if not finding.evidence_refs:
            continue
        priority, source_severity = _REC_PRIORITY[finding.severity]
        action = _REC_ACTION.get(finding.type, "Address the finding")
        recs.append(
            PrioritizedRecommendation(
                priority=priority,
                dimension=finding.metric,
                text=f"{action}: {finding.note}",
                evidence_refs=list(finding.evidence_refs),
                source_severity=source_severity,
            )
        )
    order = {
        RecommendationPriority.CRITICAL: 0,
        RecommendationPriority.HIGH: 1,
        RecommendationPriority.MEDIUM: 2,
        RecommendationPriority.LOW: 3,
    }
    recs.sort(key=lambda r: order[r.priority])
    return recs


def _confidence_report(
    metric_results: list[MetricResult],
    decision: DecisionOutcome,
    confidence_service: ConfidenceService,
    min_confidence: float,
) -> ConfidenceReport:
    """Aggregate per-metric confidence into a :class:`ConfidenceReport`."""
    per_metric = {m.metric_id: m.confidence for m in metric_results}
    signals = [signal(m.metric_id, m.confidence, weight=1.0) for m in metric_results]
    overall = confidence_service.estimate(signals)
    low = sorted(mid for mid, conf in per_metric.items() if conf < min_confidence)
    rationale = (
        decision.reason if decision.verdict is VerdictBand.UNABLE_TO_VERIFY else None
    )
    return ConfidenceReport(
        overall=overall,
        per_dimension=per_metric,
        unable_to_verify_rationale=rationale,
        low_confidence_dimensions=low,
    )


def _metric_score(audit: OutputAudit, metric_id: str) -> float | None:
    """Look up one metric's score on an assembled audit."""
    for group in (audit.layer_results.layer_1, audit.layer_results.layer_2, audit.layer_results.layer_3):
        for metric in group:
            if metric.metric_id == metric_id:
                return metric.score
    return None


def build_comparison(output_audits: list[OutputAudit]) -> Comparison:
    """Build the side-by-side comparison across outputs (Framework §6).

    ``ranking`` is best-first — the first entry is the winner. Ordering is by
    verdict band, then Faithfulness, then Coverage, so a better-grounded output
    ranks above a merely more readable one.
    """
    rows = [
        ComparisonRow(
            output_id=audit.output_id,
            producer=audit.producer,
            verdict=audit.verdict,
            faithfulness_score=(audit.faithfulness.score if audit.faithfulness else None),
            coverage_score=_metric_score(audit, "Coverage"),
            meaning_score=_metric_score(audit, "Meaning Preservation"),
            gating_finding_count=sum(
                1
                for f in audit.findings
                if f.severity in (FindingSeverity.CRITICAL, FindingSeverity.MAJOR)
                and f.layer in (Layer.L1_GROUNDING, Layer.L2_INFO)
            ),
        )
        for audit in output_audits
    ]

    def rank_key(audit: OutputAudit) -> tuple:
        return (
            _BAND_RANK[audit.verdict],
            audit.faithfulness.score if audit.faithfulness and audit.faithfulness.score is not None else -1.0,
            _metric_score(audit, "Coverage") or -1.0,
        )

    ranked = sorted(output_audits, key=rank_key, reverse=True)
    return Comparison(rows=rows, ranking=[a.output_id for a in ranked])


def build_comparative_report(
    audit_id: str, source: SourceMeta, output_audits: list[OutputAudit]
) -> ComparativeReport:
    """Assemble the final :class:`ComparativeReport`."""
    return ComparativeReport(
        audit_id=audit_id,
        source=source,
        outputs=output_audits,
        comparison=build_comparison(output_audits),
    )
