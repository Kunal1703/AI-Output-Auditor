"""Health endpoint (Document 4, §7).

``GET /health`` → ``{ "status": "ok", "llm_provider": "groq", "version": "1.0", … }``

Document 4 §12 lists a health endpoint under production readiness. This one
reports both liveness and readiness facts — whether the LLM provider is
configured and whether it answers — because a backend that is up but cannot
reach its provider will degrade every trust dimension to zero confidence and
return *Unable to Verify* for everything. That is the correct behavior, but it
should be diagnosable from ``/health`` rather than from eight confusing reports.

**Liveness never depends on the provider.** The endpoint returns 200 with
``llm_reachable: false`` when the provider is down. A 503 here would take the
service out of rotation over an upstream outage it is already designed to
survive gracefully.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_container
from app.api.models import HealthResponse
from app.app import ServiceContainer

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and readiness")
async def health(container: ServiceContainer = Depends(get_container)) -> HealthResponse:
    """Report service and provider health.

    Args:
        container: The injected service container.

    Returns:
        Status, provider identity, configuration state, and reachability.
        Always 200 while the process is serving.
    """
    facts = await container.health()
    return HealthResponse(
        status="ok",
        version=container.settings.version,
        llm_provider=str(facts["llm_provider"]),
        llm_model=str(facts["llm_model"]),
        llm_configured=bool(facts["llm_configured"]),
        llm_reachable=bool(facts["llm_reachable"]),
        llm_model_available=facts["llm_model_available"],  # type: ignore[arg-type]
        engines_registered=int(facts["engines_registered"]),  # type: ignore[arg-type]
        embedding_model=str(facts["embedding_model"]),
        embedding_cache_enabled=bool(facts["embedding_cache_enabled"]),
        embedding_cache_hit_rate=float(facts["embedding_cache_hit_rate"]),  # type: ignore[arg-type]
        prompt_templates=int(facts["prompt_templates"]),  # type: ignore[arg-type]
        nli_model=str(facts["nli_model"]),
        nli_ready=bool(facts["nli_ready"]),
    )
