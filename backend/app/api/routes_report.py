"""Report retrieval endpoint (Document 4, §7).

``GET /report/{id}`` returns the Final Audit Report (Document 3, §12), reusing
the frozen ``AuditResult`` schema for each dimension.

This route is intentionally trivial. The report was fully assembled by the
Decision Engine when the job completed; there is nothing to compute here, and
computing anything would put decision logic in the API layer, which Document 4
§5 forbids.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_job_store
from app.api.jobs import JobStore
from app.core.errors import NotFoundError
from app.shared.schemas import AuditReport, JobStatus

__all__ = ["router"]

router = APIRouter(tags=["report"])


@router.get(
    "/report/{audit_id}",
    response_model=AuditReport,
    summary="Retrieve the Final Audit Report",
)
async def get_report(
    audit_id: str, jobs: JobStore = Depends(get_job_store)
) -> AuditReport:
    """Return the Final Audit Report for a completed audit.

    Args:
        audit_id: The id returned when the audit was created.
        jobs: The injected job store.

    Returns:
        The Final Audit Report — Trust Verdict, Quality Verdict, Overall
        Verdict, per-dimension results, evidence, findings, recommendations,
        and confidence.

    Raises:
        NotFoundError: The id is unknown, the job has expired, the audit failed,
            or it is still running. The message distinguishes these, since
            "still running" and "never existed" call for very different client
            behavior.
    """
    job = await jobs.get(audit_id)

    if job.status is JobStatus.FAILED:
        raise NotFoundError(
            f"Audit {audit_id!r} failed and has no report: "
            f"{job.error or 'unknown error'}"
        )
    if job.report is None:
        raise NotFoundError(
            f"Audit {audit_id!r} is not finished ({job.status.value}; "
            f"{job.engines_completed}/{job.engines_total} engines complete). "
            f"Poll GET /audit/{audit_id}/status."
        )
    return job.report
