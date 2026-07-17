"""Audit endpoints (Document 4, §7).

| Method | Path | Purpose |
|---|---|---|
| ``POST`` | ``/audit`` | Unified entry point; audits text or a URL. |
| ``POST`` | ``/audit/text`` | Audit raw AI-generated text. |
| ``POST`` | ``/audit/url`` | Fetch a URL, extract content, audit it. |
| ``POST`` | ``/audit/file`` | Upload a file (txt/md/pdf), extract, audit. |
| ``GET`` | ``/audit/{id}/status`` | Poll job status/progress. |

Document 4 §5 constrains this layer sharply: the API accepts requests, tracks
async jobs, and returns the report. It contains **no audit or decision logic**.
Everything here delegates.

**Two shapes, deliberately.** ``POST /audit`` returns the report directly — it is
the simple path for a caller who just wants an answer. The type-specific
endpoints are asynchronous: they create a job, return an ``audit_id``, and let
the client poll, because a real run makes many LLM calls and would otherwise
hold a connection open for minutes. Both exist in the frozen design; neither
replaces the other.

**Milestone status.** Complete. :func:`_run_audit` runs the eight engines
through the orchestrator, hands the results to the Decision Engine, and stores
the Final Audit Report. Progress reflects real engine completion.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from app.api.dependencies import get_container, get_job_store
from app.api.jobs import JobStore
from app.api.models import (
    AuditCreatedResponse,
    AuditOptions,
    AuditRequest,
    AuditStatusResponse,
    AuditTextRequest,
    AuditUrlRequest,
)
from app.app import ServiceContainer
from app.core.errors import AuditorError
from app.core.logging import bind, get_logger
from app.decision_engine.report_builder import build_report
from app.shared.context import SharedContext
from app.shared.schemas import AuditReport

__all__ = ["router"]

logger = get_logger(__name__)

router = APIRouter(tags=["audit"])


async def _run_audit(
    audit_id: str,
    context: SharedContext,
    container: ServiceContainer,
    jobs: JobStore,
) -> None:
    """Execute one audit in the background and store its report.

    Measure, decide, present — the three layers of Document 1 §3, in the only
    place they meet. The orchestrator runs the eight engines in their frozen
    waves; the Decision Engine interprets the eight results; the report builder
    projects the outcome. **This function contains no audit or decision logic
    of its own** (Document 4, §5) — it wires three calls together and owns the
    job lifecycle.

    Progress is reported from the orchestrator's own callback as each engine
    finishes, so ``GET /audit/{id}/status`` reflects what actually completed
    rather than a timer (Document 4, §8).

    Args:
        audit_id: The job's id.
        context: The run's normalized content and shared derivation store.
        container: The service container.
        jobs: The job store.
    """
    await jobs.mark_processing(audit_id)
    try:
        orchestrator = container.orchestrator(audit_id)

        def on_progress(completed: int, total: int, dimension: str) -> None:
            # The orchestrator's callback is synchronous and must never fail an
            # audit, so the async store update is scheduled rather than awaited.
            # EngineOrchestrator._report already swallows anything this raises.
            asyncio.create_task(jobs.record_engine_completed(audit_id, dimension))

        results = await orchestrator.run(context, on_progress=on_progress)
        ordered = list(results.values())

        decision = container.decision_engine.decide(ordered)
        report = build_report(
            audit_id=audit_id,
            decision=decision,
            dimension_results=ordered,
            input_type=context.input_type,
            source_uri=context.source_uri,
        )
        await jobs.complete(audit_id, report)
    except AuditorError as exc:
        await jobs.fail(audit_id, exc.message)
    except Exception as exc:
        # A background task's exception is invisible — nothing awaits it. If it
        # escaped here the job would sit in 'processing' forever and the client
        # would poll until it gave up. Record it as a real failure instead.
        logger.error(
            "audit run raised unexpectedly",
            extra=bind(audit_id=audit_id, error=type(exc).__name__),
            exc_info=True,
        )
        await jobs.fail(audit_id, f"Audit failed unexpectedly: {type(exc).__name__}.")


@router.post(
    "/audit",
    response_model=AuditReport,
    summary="Audit text or a URL and return the report",
)
async def audit(
    request: AuditRequest,
    container: ServiceContainer = Depends(get_container),
    jobs: JobStore = Depends(get_job_store),
) -> AuditReport:
    """Audit content and return the Final Audit Report directly.

    The unified entry point. Accepts exactly one of ``text`` or ``url``.

    Args:
        request: The audit request.
        container: The injected service container.
        jobs: The injected job store, used to mint the ``audit_id`` so a
            synchronous report carries the same id space as an async one.

    Returns:
        The Final Audit Report — a real audit: eight engines measured, the
        Decision Engine interpreted, every verdict traceable to evidence.

    Note:
        Synchronous, so it holds the connection for the length of a full run.
        Prefer ``POST /audit/text`` and polling for anything interactive.
    """
    job = await jobs.create()
    if request.text:
        context = await container.input_router.from_text(
            audit_id=job.audit_id,
            text=request.text,
            prompt=request.prompt,
            reference_source=request.reference_source,
            options=request.options.model_dump(),
        )
    else:
        context = await container.input_router.from_url(
            audit_id=job.audit_id,
            url=request.url or "",
            prompt=request.prompt,
            reference_source=request.reference_source,
            options=request.options.model_dump(),
        )

    logger.info("audit requested", extra=bind(**context.describe()))
    await _run_audit(job.audit_id, context, container, jobs)
    completed = await jobs.get(job.audit_id)
    if completed.report is None:
        raise AuditorError(completed.error or "The audit produced no report.")
    return completed.report


@router.post(
    "/audit/text",
    response_model=AuditCreatedResponse,
    status_code=202,
    summary="Audit raw text (async)",
)
async def audit_text(
    request: AuditTextRequest,
    background: BackgroundTasks,
    container: ServiceContainer = Depends(get_container),
    jobs: JobStore = Depends(get_job_store),
) -> AuditCreatedResponse:
    """Create an async audit job for raw text.

    Args:
        request: The text audit request.
        background: FastAPI's background task runner.
        container: The injected service container.
        jobs: The injected job store.

    Returns:
        The ``audit_id`` to poll and retrieve by.
    """
    job = await jobs.create()
    context = await container.input_router.from_text(
        audit_id=job.audit_id,
        text=request.text,
        prompt=request.prompt,
        reference_source=request.reference_source,
        options=request.options.model_dump(),
    )
    background.add_task(_run_audit, job.audit_id, context, container, jobs)
    return AuditCreatedResponse(audit_id=job.audit_id, status=job.status)


@router.post(
    "/audit/url",
    response_model=AuditCreatedResponse,
    status_code=202,
    summary="Audit a URL (async)",
)
async def audit_url(
    request: AuditUrlRequest,
    background: BackgroundTasks,
    container: ServiceContainer = Depends(get_container),
    jobs: JobStore = Depends(get_job_store),
) -> AuditCreatedResponse:
    """Create an async audit job for a URL.

    Extraction runs inline, before the job is handed to the background, so an
    unfetchable URL surfaces as an immediate error to the caller rather than as
    a job that fails a second later.

    Args:
        request: The URL audit request.
        background: FastAPI's background task runner.
        container: The injected service container.
        jobs: The injected job store.

    Returns:
        The ``audit_id`` to poll and retrieve by.

    Raises:
        ExtractionError: The page could not be fetched or extracted.
    """
    job = await jobs.create()
    context = await container.input_router.from_url(
        audit_id=job.audit_id,
        url=request.url,
        prompt=request.prompt,
        reference_source=request.reference_source,
        options=request.options.model_dump(),
    )
    background.add_task(_run_audit, job.audit_id, context, container, jobs)
    return AuditCreatedResponse(audit_id=job.audit_id, status=job.status)


@router.post(
    "/audit/file",
    response_model=AuditCreatedResponse,
    status_code=202,
    summary="Audit an uploaded file (async)",
)
async def audit_file(
    background: BackgroundTasks,
    file: UploadFile = File(description="A txt, md, or pdf file to audit."),
    prompt: str | None = Form(default=None),
    reference_source: str | None = Form(default=None),
    external_retrieval: bool = Form(default=False),
    container: ServiceContainer = Depends(get_container),
    jobs: JobStore = Depends(get_job_store),
) -> AuditCreatedResponse:
    """Create an async audit job for an uploaded file.

    Args:
        background: FastAPI's background task runner.
        file: The uploaded txt/md/pdf.
        prompt: The original instruction, optional.
        reference_source: Ground truth, optional.
        external_retrieval: Allow Accuracy's optional external retrieval step.
        container: The injected service container.
        jobs: The injected job store.

    Returns:
        The ``audit_id`` to poll and retrieve by.

    Raises:
        UnsupportedInputError: The file format is not supported.
        ExtractionError: The file yielded no usable text.
    """
    job = await jobs.create()
    data = await file.read()
    context = await container.input_router.from_file(
        audit_id=job.audit_id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type,
        prompt=prompt,
        reference_source=reference_source,
        options=AuditOptions(external_retrieval=external_retrieval).model_dump(),
    )
    background.add_task(_run_audit, job.audit_id, context, container, jobs)
    return AuditCreatedResponse(audit_id=job.audit_id, status=job.status)


@router.get(
    "/audit/{audit_id}/status",
    response_model=AuditStatusResponse,
    summary="Poll audit job status",
)
async def audit_status(
    audit_id: str, jobs: JobStore = Depends(get_job_store)
) -> AuditStatusResponse:
    """Report a job's status and real engine progress.

    Args:
        audit_id: The job's id.
        jobs: The injected job store.

    Returns:
        Status, engines completed, and engines total.

    Raises:
        NotFoundError: The id is unknown or the job has expired.
    """
    job = await jobs.get(audit_id)
    return AuditStatusResponse(
        audit_id=job.audit_id,
        status=job.status,
        engines_completed=job.engines_completed,
        engines_total=job.engines_total,
        error=job.error,
    )
