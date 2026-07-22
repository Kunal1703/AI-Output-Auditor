"""Provider registry — resolves a config key to an :class:`LLMProvider`.

This is the indirection that makes Document 4 §2's promise real: switching the
LLM backend is a change to ``LLM_PROVIDER`` in the environment (or
``llm.provider`` in ``config/settings.yaml``), not a change to any engine.

Adding a provider is two steps:

1. Implement :class:`~app.shared.llm_providers.base.LLMProvider` in a sibling
   module.
2. Add a builder here under its config key.

Nothing else in the system needs to know it exists. Engines call the LLM
Service; the LLM Service asks this registry for whatever the configuration
named.

Builders are lazy — a provider is constructed only when selected — so an
optional dependency for an unused provider never has to be installed.

---

**Enabling the paid provider (OpenRouter).**

Groq is the active provider. The OpenRouter wiring below is complete and
commented out, ready for when a paid provider is needed. To enable it:

1. Uncomment the two blocks marked ``PAID PROVIDER`` in this file.
2. Set ``OPENROUTER_API_KEY`` and ``LLM_PROVIDER=openrouter`` in ``backend/.env``.
3. Set ``LLM_MODEL`` to an OpenRouter-qualified id, e.g.
   ``anthropic/claude-sonnet-4.5``, and clear ``llm.reasoning_format`` in
   ``config/settings.yaml`` (it is Groq-specific).

No engine, service, or Decision Engine code changes. That is the whole point of
this seam.
"""

from __future__ import annotations

from typing import Callable

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.shared.llm_providers.base import LLMProvider
from app.shared.llm_providers.groq import GroqProvider

# --- PAID PROVIDER (OpenRouter) — uncomment to enable -----------------------
# from app.shared.llm_providers.openrouter import OpenRouterProvider
# ---------------------------------------------------------------------------

__all__ = ["build_provider", "available_providers", "register_provider"]

ProviderBuilder = Callable[[Settings], LLMProvider]


def _build_groq(settings: Settings) -> LLMProvider:
    """Construct the Groq provider from settings."""
    key = settings.llm.api_key
    return GroqProvider(
        api_key=key.get_secret_value() if key else None,
        base_url=settings.llm.base_url,
        reasoning_format=settings.llm.reasoning_format,
        reasoning_effort=settings.llm.reasoning_effort,
    )


# --- PAID PROVIDER (OpenRouter) — uncomment to enable -----------------------
# def _build_openrouter(settings: Settings) -> LLMProvider:
#     """Construct the OpenRouter provider from settings."""
#     key = settings.llm.api_key
#     return OpenRouterProvider(
#         api_key=key.get_secret_value() if key else None,
#         base_url=settings.llm.base_url,
#         app_title=settings.app_name,
#     )
# ---------------------------------------------------------------------------


_BUILDERS: dict[str, ProviderBuilder] = {
    "groq": _build_groq,
    # --- PAID PROVIDER (OpenRouter) — uncomment to enable ------------------
    # "openrouter": _build_openrouter,
    # ----------------------------------------------------------------------
}


def register_provider(name: str, builder: ProviderBuilder) -> None:
    """Register a provider builder under ``name``.

    Args:
        name: The config key that will select this provider.
        builder: Callable taking :class:`Settings` and returning a provider.

    Raises:
        ConfigurationError: If ``name`` is already registered. Silently
            replacing a provider would make the active backend depend on import
            order — a debugging nightmare when verdicts differ between runs.
    """
    if name in _BUILDERS:
        raise ConfigurationError(f"LLM provider {name!r} is already registered.")
    _BUILDERS[name] = builder


def available_providers() -> tuple[str, ...]:
    """Return the registered provider keys, sorted."""
    return tuple(sorted(_BUILDERS))


def build_provider(settings: Settings) -> LLMProvider:
    """Construct the provider named by ``settings.llm.provider``.

    Args:
        settings: The loaded configuration.

    Returns:
        A ready :class:`LLMProvider`.

    Raises:
        ConfigurationError: If the configured provider is not registered. This
            fails at startup by design — a typo in the provider key should stop
            the boot, not surface as a failed audit later.
    """
    builder = _BUILDERS.get(settings.llm.provider)
    if builder is None:
        raise ConfigurationError(
            f"Unknown LLM provider {settings.llm.provider!r}. "
            f"Registered providers: {', '.join(available_providers())}. "
            "(OpenRouter ships commented out in llm_providers/registry.py — "
            "uncomment the PAID PROVIDER blocks to enable it.)"
        )
    return builder(settings)
