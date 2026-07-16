"""Report Builder — assembles the Final Audit Report (Document 3, §12).

Turns a ``DecisionResult`` into the ``AuditReport`` the API returns and the
frontend renders. The report is the Decision Engine's sole deliverable, and it
carries three guarantees:

* **Two-axis clarity.** Trust and Quality are always presented separately and
  are never fused into a single number.
* **Traceability.** Every claim links to an ``AuditResult`` field — ``ledger``,
  ``evidence``, or ``critical_findings`` — which is why the full per-dimension
  results are carried through verbatim rather than flattened to scores.
* **Honest uncertainty.** Where confidence is insufficient, the report says so
  explicitly rather than presenting an unearned verdict.

**Milestone 1 also owns the placeholder report** that ``POST /audit`` returns
until the engines exist. Read the note on :func:`build_placeholder_report`
before changing what it returns — the verdict it reports is a safety property,
not a filler value.
"""

from __future__ import annotations

from app.core.constants import DIMENSION_SPECS
from app.shared.schemas import (
    AuditReport,
    AuditResult,
    AuditResultMetadata,
    ConfidenceReport,
    DecisionResult,
    InputType,
    OverallVerdict,
    QualityBand,
    QualityVerdict,
    TrustOutcome,
    TrustVerdict,
)

__all__ = ["build_report", "build_placeholder_report"]

_PLACEHOLDER_REASON = (
    "This is a Milestone 1 scaffold response. The eight Audit Engines are not "
    "yet implemented, so no dimension has actually been measured and no "
    "evidence has been collected."
)


def build_report(
    audit_id: str,
    decision: DecisionResult,
    dimension_results: list[AuditResult],
    input_type: InputType = InputType.TEXT,
    source_uri: str | None = None,
) -> AuditReport:
    """Assemble the Final Audit Report from a decision outcome.

    Args:
        audit_id: The id the report is retrieved by.
        decision: The Decision Engine's cross-dimensional outcome.
        dimension_results: The eight ``AuditResult`` objects, carried into the
            report verbatim so the frontend can drill from any verdict into the
            ledger and evidence that produced it.
        input_type: How the content arrived.
        source_uri: The original URL or filename, when applicable.

    Returns:
        The Final Audit Report.

    Raises:
        NotImplementedError: Until Milestone 2, with the decision workflow that
            produces the ``DecisionResult`` it consumes.
    """
    raise NotImplementedError(
        "build_report is implemented in Milestone 2, alongside the Decision "
        "Engine workflow (Document 3, §4 and §12)."
    )


def _placeholder_dimension_result(dimension: str) -> AuditResult:
    """Build an unmeasured, zero-confidence result for one dimension.

    Confidence is what carries the meaning here. ``0.0`` states plainly that
    this dimension supports no conclusion whatsoever, so the accompanying
    ``0.0`` score can never be misread as a real failing measurement — the same
    score/confidence separation the Decision Engine relies on in Document 3 §8.
    """
    spec = DIMENSION_SPECS[dimension]
    return AuditResult(
        score=0.0,
        confidence=0.0,
        ledger=[],
        evidence=[],
        recommendations=[],
        critical_findings=[],
        metadata=AuditResultMetadata(
            dimension=spec.dimension,
            engine_id=spec.engine_id,
            dimension_type=spec.dimension_type,
            critical_finding_capability=spec.critical_finding_capability,
            supports_na=spec.supports_na,
            applicable=True,
            applicability_reason="",
        ),
    )


def build_placeholder_report(
    audit_id: str,
    input_type: InputType = InputType.TEXT,
    source_uri: str | None = None,
) -> AuditReport:
    """Build the scaffold ``AuditReport`` that ``POST /audit`` returns today.

    This exists so the API contract is live and the frontend can be built
    against a real report shape before the engines land (Document 4, §9: "Build
    against a stable report contract; no rework from shifting response shapes").

    **The verdict is Unable to Verify, and that is a safety property — do not
    "fix" it to something friendlier.** Document 3 §13 and Document 4 §12 both
    require the system to fail safe toward caution rather than toward unearned
    trust. Nothing has been measured here, so trust is genuinely undetermined,
    and *Unable to Verify* is the honest answer — it is the verdict for "cannot
    confirm or deny on the available evidence", which is exactly the situation.
    A placeholder reporting *Trusted* would be a scaffold that lies, and the one
    failure mode this entire system exists to prevent.

    Every dimension is reported at zero confidence with no evidence, so the
    report is internally consistent: it asserts nothing it cannot support.

    Args:
        audit_id: The id assigned to this request.
        input_type: How the content arrived.
        source_uri: The original URL or filename, when applicable.

    Returns:
        A schema-valid Final Audit Report carrying no unearned conclusions.
    """
    dimensions = list(DIMENSION_SPECS)
    return AuditReport(
        audit_id=audit_id,
        overall_verdict=OverallVerdict.UNABLE_TO_VERIFY,
        trust_verdict=TrustVerdict(
            verdict=TrustOutcome.UNABLE_TO_VERIFY,
            reason=_PLACEHOLDER_REASON,
            evidence_refs=[],
            gating_finding_ids=[],
        ),
        quality_verdict=QualityVerdict(
            band=QualityBand.LOW,
            score=None,
            drivers=[],
            excluded_dimensions=[],
        ),
        summary=(
            "No audit was performed. The backend scaffold is running and the "
            "report contract is live, but the audit engines that measure the "
            "eight dimensions arrive in Milestone 2. Trust is undetermined "
            "rather than failed."
        ),
        confidence=ConfidenceReport(
            overall=0.0,
            per_dimension={d: 0.0 for d in dimensions},
            unable_to_verify_rationale=_PLACEHOLDER_REASON,
            low_confidence_dimensions=list(dimensions),
        ),
        critical_findings=[],
        dimension_results=[_placeholder_dimension_result(d) for d in dimensions],
        recommendations=[],
        input_type=input_type,
        source_uri=source_uri,
    )
