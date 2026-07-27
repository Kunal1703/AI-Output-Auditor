"""FastAPI dependency providers.

Bridges the service container (``app.app``) to route handlers. The container is
built once by the lifespan handler and stored on ``app.state``; these providers
hand it to handlers.

Routes depend on these functions rather than importing the container, which is
what lets a test override a single dependency — swapping the LLM for a fake, say
— without rebuilding the app (Document 4, §10).
"""

from __future__ import annotations

from fastapi import Request

from app.app import ServiceContainer
from app.core.config import Settings

__all__ = ["get_container", "get_settings_dep"]


def get_container(request: Request) -> ServiceContainer:
    """Return the application-scoped service container."""
    return request.app.state.container  # type: ignore[no-any-return]


def get_settings_dep(request: Request) -> Settings:
    """Return the loaded configuration."""
    return request.app.state.container.settings  # type: ignore[no-any-return]
