"""FastAPI application factory (Document 4, §3 and §7).

Builds the app: lifespan-managed service container, CORS for the Vite dev
server, exception handlers implementing the frozen error contract, and the
route table.

The factory pattern matters for testability — a test builds an app with its own
settings instead of mutating a global. ``app.main`` calls this once to expose the
ASGI callable that ``uvicorn app.main:app`` needs.

**All error responses use the frozen contract** (Document 4, §7)::

    { "error": { "code": "...", "message": "..." } }

The handlers below are what guarantee that, including for FastAPI's own
validation errors — which would otherwise return FastAPI's default shape and
quietly break the contract for exactly the requests most likely to hit it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    routes_audit,
    routes_health,
    routes_output_audit,
    routes_report,
)
from app.api.jobs import JobStore
from app.app import build_container
from app.core.config import Settings
from app.core.errors import AuditorError
from app.core.logging import bind, get_logger

__all__ = ["create_app"]

logger = get_logger(__name__)

DESCRIPTION = """
Evaluates AI-generated content and returns a complete, evidence-backed audit:
**what** the verdict is, **what evidence** supports it, **how confident** the
auditor is, and **what to fix**.

Trust and Quality are reported on two separate axes and are never fused into a
single number. Trust is non-compensatory — one qualifying critical finding, such
as a fabricated citation, gates the trust verdict regardless of how well the
content scores elsewhere. Where evidence is insufficient the auditor returns
*Unable to Verify* rather than guessing.
"""


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Render the frozen error contract."""
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the service container at startup; release it at shutdown.

    Constructing here rather than at import time means configuration errors
    surface as a failed startup with a readable message, and means the
    connection pools are created on the running event loop that will use them.
    """
    settings: Settings | None = getattr(app.state, "settings_override", None)
    container = build_container(settings)
    # Fail fast on a retired/unavailable model, before serving a single audit:
    # a wrong model id degrades every dimension to Unable to Verify, and that is
    # a startup misconfiguration, not a content verdict. Skips itself when
    # availability cannot be checked (offline), so it never blocks on a blip.
    await container.verify_model()
    # Load the local NLI model ahead of first use so /health reports nli_ready
    # (AI Output Auditor, MB1). Non-fatal: a failed load leaves the app bootable
    # with nli_ready=false, and no metric consumes NLI until MB2.
    await container.warm_nli()
    app.state.container = container
    app.state.jobs = JobStore(retention_seconds=container.settings.jobs.retention_seconds)
    logger.info(
        "auditor api started",
        extra=bind(
            version=container.settings.version,
            environment=container.settings.environment,
        ),
    )
    try:
        yield
    finally:
        await container.aclose()
        logger.info("auditor api stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Configuration override. Loaded from ``config/settings.yaml``
            plus the environment when omitted. Tests pass their own.

    Returns:
        The configured ASGI application.
    """
    app = FastAPI(
        title="AI Trust & Quality Auditor",
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=_lifespan,
    )
    if settings is not None:
        app.state.settings_override = settings

    origins = settings.cors_origins if settings else Settings().cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AuditorError)
    async def _auditor_error(_: Request, exc: AuditorError) -> JSONResponse:
        """Render a deliberate auditor error in the frozen contract."""
        return _error_response(exc.http_status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Render request-validation failures in the frozen contract.

        Without this, FastAPI's default handler returns its own ``{"detail": …}``
        shape — breaking the contract for precisely the requests a client is
        most likely to get wrong.
        """
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in exc.errors()
        )
        return _error_response(
            422, "validation_error", detail or "The request payload is invalid."
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Render framework HTTP errors (404s, 405s) in the frozen contract."""
        return _error_response(
            exc.status_code, f"http_{exc.status_code}", str(exc.detail)
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        """Catch-all: log with a traceback, return the contract shape.

        The exception type is deliberately not echoed to the client — an
        unhandled error is a bug, and its internals are for the log, not the
        response body.
        """
        logger.error(
            "unhandled exception", extra=bind(error=type(exc).__name__), exc_info=True
        )
        return _error_response(
            500, "internal_error", "The auditor encountered an unexpected error."
        )

    app.include_router(routes_health.router)
    app.include_router(routes_audit.router)
    app.include_router(routes_output_audit.router)
    app.include_router(routes_report.router)
    return app
