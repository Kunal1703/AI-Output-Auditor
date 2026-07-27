"""AI Output Auditor endpoint (MB4).

``POST /audit/outputs`` — audit one or more outputs against a mandatory source
article and return the finalized :class:`ComparativeReport`.

This is the evaluation pipeline's entry point. This layer contains no audit or
decision logic — it normalizes the request, hands the contexts to the Audit
Orchestrator (the single owner of execution order), and returns the report.

Synchronous by design for MB4: the caller submits source + outputs and receives
the comparative report directly. Async job-based delivery for large multi-output
runs is a later concern.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.api.models import AuditOutputsRequest
from app.app import ServiceContainer
from app.core.logging import bind, get_logger
from app.shared.schemas import ComparativeReport

__all__ = ["router"]

logger = get_logger(__name__)

router = APIRouter(tags=["output-audit"])


@router.post(
    "/audit/outputs",
    response_model=ComparativeReport,
    summary="Audit outputs against a source and return the comparative report",
)
async def audit_outputs(
    request: AuditOutputsRequest,
    container: ServiceContainer = Depends(get_container),
) -> ComparativeReport:
    """Audit every supplied output against the source and return the report.

    Args:
        request: The source article and the outputs to audit against it.
        container: The injected service container.

    Returns:
        The ``ComparativeReport`` — one ``OutputAudit`` per output, each with its
        verdict, layered metric results, findings, evidence, recommendations, and
        the attribution map, plus the cross-output comparison and ranking.

    Raises:
        ValidationError: No outputs, or more than ``input.max_outputs``.
        ExtractionError: A URL source or output could not be extracted.
    """
    audit_id = f"aud_{uuid.uuid4().hex[:20]}"
    contexts = await container.input_router.from_audit_request(
        audit_id=audit_id,
        source=request.source,
        outputs=request.outputs,
        max_outputs=container.settings.input.max_outputs,
    )
    logger.info(
        "output audit requested",
        extra=bind(audit_id=audit_id, outputs=len(contexts.outputs)),
    )
    return await container.audit_orchestrator.run(contexts)
