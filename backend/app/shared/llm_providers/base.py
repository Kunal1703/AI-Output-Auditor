"""The LLM provider contract.

Document 4 §2 requires "a single provider-agnostic interface [that] lets the
team switch providers via config with no engine changes", and §4 forbids an
engine from ever touching a provider SDK directly. This module defines that
interface; concrete providers implement it, and the Shared LLM Service
(``shared/llm_service.py``) is the only thing that calls them.

The resulting layering::

    Audit Engine  →  LLM Service  →  LLMProvider  →  Groq / OpenRouter / …
                     (retries,        (transport
                      timeouts,        only)
                      degradation)

Keep transport concerns here and policy concerns in the LLM Service. A provider
should issue one request and translate one response. It must not retry, must
not implement fallback, and must not decide what a failure means — those are
cross-provider policy and belong in the service, or the next provider added
would have to reimplement them.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ChatMessage", "CompletionRequest", "CompletionResponse", "LLMProvider"]

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    """One turn in a chat exchange.

    Attributes:
        role: ``system``, ``user``, or ``assistant``.
        content: The message text.
    """

    role: Role
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    """A provider-neutral completion request.

    Attributes:
        messages: The conversation, oldest first.
        model: Provider-qualified model id. The service resolves this from
            configuration; a provider should not substitute its own default.
        temperature: Sampling temperature. The auditor defaults to 0.0 for
            reproducibility (Document 4, §11).
        max_tokens: Output ceiling.
        json_schema: When set, the provider requests structured JSON conforming
            to this schema. Document 4 §4 makes structured-JSON output part of
            the LLM Service's remit — engine pipelines parse ledgers and
            verdicts, not prose.
        timeout_seconds: Per-call budget for this request.
        extra: Escape hatch for provider-specific parameters. Anything that
            becomes common across providers should be promoted to a real field.
    """

    messages: tuple[ChatMessage, ...]
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
    json_schema: dict[str, Any] | None = None
    timeout_seconds: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResponse:
    """A provider-neutral completion response.

    Attributes:
        text: The generated content.
        model: The model the provider reports actually serving the request.
            May differ from the requested id — some gateways reroute — which is
            worth logging when a verdict looks surprising.
        prompt_tokens: Input tokens consumed, when reported.
        completion_tokens: Output tokens produced, when reported.
        finish_reason: Why generation stopped, e.g. ``stop`` or ``length``. A
            truncated response is a real source of malformed structured output,
            so callers should check this rather than assume completeness.
        raw: The unmodified provider payload, for debugging.
    """

    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Abstract transport to one LLM backend.

    Implement this to add a provider. Register the class in
    ``shared/llm_providers/registry.py`` and it becomes selectable by config key
    with no change to any engine, to the LLM Service, or to the Decision Engine.

    Implementations must:

    * translate :class:`CompletionRequest` into the provider's wire format and
      the response back into :class:`CompletionResponse`;
    * raise :class:`app.core.errors.ProviderError` (or
      :class:`~app.core.errors.ProviderTimeoutError`) on failure, so callers
      never have to catch a vendor-specific exception type;
    * honor ``request.timeout_seconds``;
    * be safe to share across concurrent tasks — the orchestrator runs six
      engines at once (Document 4, §12), all through one provider instance.

    Implementations must not retry, fall back to another provider, or mutate
    the request. That is the LLM Service's job.
    """

    #: Config key that selects this provider, e.g. ``"openrouter"``.
    name: str = "abstract"

    @abc.abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Issue one completion request.

        Args:
            request: The provider-neutral request.

        Returns:
            The provider-neutral response.

        Raises:
            ProviderTimeoutError: The call exceeded ``timeout_seconds``.
            ProviderError: Any other provider or transport failure.
        """

    @abc.abstractmethod
    async def health(self) -> bool:
        """Report whether the provider looks usable.

        Backs the readiness half of ``GET /health`` (Document 4, §7). Should be
        cheap and must not raise — a health probe that throws is a health probe
        that takes the service down with it.

        Returns:
            True if the provider appears reachable and configured.
        """

    async def available_models(self) -> set[str] | None:
        """Return the set of model ids this key may currently use, if knowable.

        Backs startup model validation (``ServiceContainer.verify_model``): a
        provider that retires or renames a model turns every audit into
        *Unable to Verify*, and the honest place to catch that is before the
        first audit, not inside eight degraded dimensions.

        Returns:
            The available model ids, or ``None`` when the provider cannot
            enumerate them (no such endpoint, or the probe failed). ``None`` is
            deliberately distinct from an empty set: "could not check" must not
            be mistaken for "nothing is available", so the caller skips
            validation rather than blocking a run over a transient network
            error. Must not raise — like :meth:`health`, this is a readiness
            probe.
        """
        return None

    async def aclose(self) -> None:
        """Release transport resources.

        Called on application shutdown. The default is a no-op for providers
        holding no connection pool.
        """
        return None
