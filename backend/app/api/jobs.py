"""Async audit job store (Document 4, §3 and §7).

Auditing is asynchronous because a run makes many LLM calls: the ``POST /audit*``
endpoints create a job and return an ``audit_id``, and the report is fetched by
id. This module owns the job lifecycle that makes that work.

Document 4 §12 requires "async job store keyed by ``audit_id``; jobs isolated",
and §8 requires the progress the frontend polls to reflect *actual* engine
completion — hence :meth:`JobStore.record_engine_completed`, which the
orchestrator drives through its progress callback.

**In-memory and single-process, on purpose.** Persistent multi-tenant storage is
explicitly out of scope (Document 4, §14). Jobs expire after
``jobs.retention_seconds``. Running multiple workers would need a shared store —
a real constraint to remember before scaling out, not a bug.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.core.errors import NotFoundError
from app.core.logging import bind, get_logger
from app.shared.schemas import AuditReport, JobStatus

__all__ = ["AuditJob", "JobStore"]

logger = get_logger(__name__)

#: Engines per run. Fixed at eight by Document 2.
ENGINES_TOTAL = 8


@dataclass
class AuditJob:
    """One audit run's state.

    Attributes:
        audit_id: The job's id.
        status: Lifecycle state.
        engines_completed: Engines finished so far — real, not estimated.
        engines_total: Engines in the run.
        report: The Final Audit Report. Present once completed.
        error: Failure reason. Present once failed.
        created_at: Monotonic creation time, used for expiry.
    """

    audit_id: str
    status: JobStatus = JobStatus.QUEUED
    engines_completed: int = 0
    engines_total: int = ENGINES_TOTAL
    report: AuditReport | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)


class JobStore:
    """In-memory, asyncio-safe store of audit jobs, keyed by ``audit_id``.

    Args:
        retention_seconds: How long a job survives after creation. Expired jobs
            are swept lazily on access, so a long-lived process does not grow
            without bound.

    Note:
        Guarded by an ``asyncio.Lock``. The store is mutated from request
        handlers and from background audit tasks concurrently, so the
        read-modify-write in :meth:`record_engine_completed` genuinely needs it —
        without the lock, two engines finishing in the same tick could both read
        the same count and one completion would vanish from the progress the
        user sees.
    """

    def __init__(self, retention_seconds: float = 3600.0) -> None:
        self._jobs: dict[str, AuditJob] = {}
        self._retention = retention_seconds
        self._lock = asyncio.Lock()

    @staticmethod
    def _new_id() -> str:
        """Mint an ``aud_`` id (Document 4, §7 uses ``aud_01H…``)."""
        return f"aud_{uuid.uuid4().hex[:20]}"

    def _sweep(self) -> None:
        """Drop jobs past their retention. Caller must hold the lock."""
        cutoff = time.monotonic() - self._retention
        expired = [k for k, job in self._jobs.items() if job.created_at < cutoff]
        for key in expired:
            del self._jobs[key]
        if expired:
            logger.info("swept expired jobs", extra=bind(count=len(expired)))

    async def create(self) -> AuditJob:
        """Create a job in the ``queued`` state.

        Returns:
            The new job, carrying its minted ``audit_id``.
        """
        async with self._lock:
            self._sweep()
            job = AuditJob(audit_id=self._new_id())
            self._jobs[job.audit_id] = job
            return job

    async def get(self, audit_id: str) -> AuditJob:
        """Return a job by id.

        Args:
            audit_id: The job's id.

        Returns:
            The job.

        Raises:
            NotFoundError: If the id is unknown or the job has expired. The API
                renders this as a 404 in the frozen error contract.
        """
        async with self._lock:
            self._sweep()
            job = self._jobs.get(audit_id)
            if job is None:
                raise NotFoundError(
                    f"No audit found with id {audit_id!r}. It may have expired."
                )
            return job

    async def mark_processing(self, audit_id: str) -> None:
        """Move a job to ``processing``."""
        async with self._lock:
            job = self._jobs.get(audit_id)
            if job is not None:
                job.status = JobStatus.PROCESSING

    async def record_engine_completed(self, audit_id: str, dimension: str) -> None:
        """Increment real engine progress.

        Wired to the orchestrator's progress callback so ``GET /audit/{id}/status``
        reports what actually finished (Document 4, §8).

        Args:
            audit_id: The job's id.
            dimension: The dimension that just completed.
        """
        async with self._lock:
            job = self._jobs.get(audit_id)
            if job is None:
                return
            job.engines_completed = min(job.engines_completed + 1, job.engines_total)
            completed = job.engines_completed
        logger.info(
            "engine completed",
            extra=bind(
                audit_id=audit_id,
                dimension=dimension,
                engines_completed=completed,
                engines_total=ENGINES_TOTAL,
            ),
        )

    async def complete(self, audit_id: str, report: AuditReport) -> None:
        """Attach the finished report and mark the job ``completed``.

        Args:
            audit_id: The job's id.
            report: The Final Audit Report.
        """
        async with self._lock:
            job = self._jobs.get(audit_id)
            if job is None:
                return
            job.report = report
            job.status = JobStatus.COMPLETED
            job.engines_completed = job.engines_total
        logger.info(
            "audit completed",
            extra=bind(audit_id=audit_id, verdict=report.overall_verdict.value),
        )

    async def fail(self, audit_id: str, error: str) -> None:
        """Mark a job ``failed``.

        Reserved for failures that prevent an audit from producing a report at
        all — an unextractable URL, say. It is *not* the path for an engine or
        provider failure: those degrade into a low-confidence dimension and
        still yield a report, biased toward *Unable to Verify* (Document 3, §8;
        Document 4, §12). A failed job means there is no verdict; a degraded
        engine means the verdict is honest about what it could not check.

        Args:
            audit_id: The job's id.
            error: Human-readable reason, surfaced on the status endpoint.
        """
        async with self._lock:
            job = self._jobs.get(audit_id)
            if job is None:
                return
            job.status = JobStatus.FAILED
            job.error = error
        logger.error("audit failed", extra=bind(audit_id=audit_id, error=error))
