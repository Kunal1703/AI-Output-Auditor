"""Shared LLM Service — the only path from an engine to a language model.

Document 4 §4 states the rule this module exists to enforce:

    An engine never calls a provider SDK, an HTTP client, or a model directly.
    It calls a Shared Service.

The service owns *policy*; the provider owns *transport*. Policy here means
bounded retries with backoff, timeouts, structured-JSON parsing, and turning
vendor failures into one error type. Centralizing it means a new provider
inherits all of it for free, and means the retry behavior an engine sees does
not depend on which backend is configured.

What this service deliberately does **not** do: decide what a failure means. It
raises. The engine catches and degrades into a low-confidence ``AuditResult``,
which the Decision Engine reads as a verification gap and resolves toward
*Unable to Verify* (Document 3, §8; Document 4, §12). Swallowing an error here
would hide a verification gap behind a plausible-looking default — precisely
the unearned trust this system exists to prevent.
"""

from __future__ import annotations

import abc
import asyncio
import json
import random
import re
from typing import Any, Sequence

from app.core.config import Settings
from app.core.errors import ProviderError, ProviderTimeoutError
from app.core.logging import bind, get_logger
from app.shared.llm_providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
)

__all__ = ["LLMService", "BaseLLMService", "DefaultLLMService"]

logger = get_logger(__name__)

#: Matches a ```json fenced block. Models wrap JSON in fences even when asked
#: not to; stripping the fence is cheaper than failing the audit over it.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMService(abc.ABC):
    """The interface engines depend on for language-model access.

    Engines type against this, never against a concrete provider. Tests supply
    a fake implementation, which is what makes engine and Decision Engine suites
    deterministic and offline (Document 4, §10).
    """

    @abc.abstractmethod
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CompletionResponse:
        """Generate a free-text completion.

        Args:
            messages: The conversation, oldest first.
            model: Overrides the configured model. Leave unset unless a stage
                genuinely needs a different one.
            temperature: Overrides the configured temperature.
            max_tokens: Overrides the configured output ceiling.
            timeout_seconds: Overrides the configured per-call budget.

        Returns:
            The provider-neutral response.

        Raises:
            ProviderError: The provider failed and retries were exhausted.
            ProviderTimeoutError: The call exceeded its budget.
        """

    @abc.abstractmethod
    async def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Generate a completion and parse it as JSON.

        The workhorse for engine pipelines: claim extraction, per-unit verdicts,
        and ledger rows are all structured output, not prose.

        Args:
            messages: The conversation, oldest first.
            json_schema: A JSON Schema the provider should constrain output to.
            model: Overrides the configured model.
            temperature: Overrides the configured temperature.
            max_tokens: Overrides the configured output ceiling.
            timeout_seconds: Overrides the configured per-call budget.

        Returns:
            The parsed JSON value.

        Raises:
            ProviderError: The provider failed, or returned text that is not
                JSON after retries.
            ProviderTimeoutError: The call exceeded its budget.
        """

    @abc.abstractmethod
    async def health(self) -> bool:
        """Report whether the underlying provider looks usable."""

    async def aclose(self) -> None:
        """Release provider resources on shutdown."""
        return None


class BaseLLMService(LLMService):
    """Alias kept for readability at injection sites.

    Type annotations that want "any LLM service" should use :class:`LLMService`.
    """


class DefaultLLMService(LLMService):
    """The production LLM Service: retry, timeout, and JSON policy over a provider.

    Args:
        provider: The transport, resolved from configuration by the provider
            registry.
        settings: Loaded configuration supplying model, temperature, timeout,
            and retry budget.

    Note:
        Safe to share across concurrently running engines. It holds no
        per-request state, and the provider beneath it is required to be
        concurrency-safe too.
    """

    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    def _build_request(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: dict[str, Any] | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> CompletionRequest:
        cfg = self._settings.llm
        return CompletionRequest(
            messages=tuple(messages),
            model=model or cfg.model,
            temperature=cfg.temperature if temperature is None else temperature,
            max_tokens=max_tokens or cfg.max_tokens,
            json_schema=json_schema,
            timeout_seconds=timeout_seconds or cfg.timeout_seconds,
        )

    async def _complete_with_retries(
        self, request: CompletionRequest
    ) -> CompletionResponse:
        """Call the provider, retrying transient failures with backoff.

        Document 4 §12 mandates bounded retries with backoff and no infinite
        retries. The budget is ``llm.max_retries``; jitter avoids a wave of six
        parallel engines synchronizing their retries into a thundering herd.
        """
        cfg = self._settings.llm
        last_error: ProviderError | None = None

        for attempt in range(cfg.max_retries + 1):
            try:
                return await self._provider.complete(request)
            except ProviderError as exc:
                last_error = exc
                if attempt >= cfg.max_retries:
                    break
                delay = cfg.retry_backoff_seconds * (2**attempt)
                delay *= 0.5 + random.random()  # noqa: S311 — jitter, not crypto
                logger.warning(
                    "llm call failed; retrying",
                    extra=bind(
                        provider=self._provider.name,
                        model=request.model,
                        attempt=attempt + 1,
                        max_attempts=cfg.max_retries + 1,
                        retry_in_s=round(delay, 2),
                        error=type(exc).__name__,
                    ),
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # loop only exits via return or break
        logger.error(
            "llm call exhausted retries",
            extra=bind(
                provider=self._provider.name,
                model=request.model,
                attempts=cfg.max_retries + 1,
            ),
        )
        raise last_error

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CompletionResponse:
        """Generate a free-text completion. See :meth:`LLMService.complete`."""
        request = self._build_request(
            messages,
            json_schema=None,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        return await self._complete_with_retries(request)

    async def complete_json(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Generate a completion and parse it as JSON.

        See :meth:`LLMService.complete_json`. Unparseable output is retried once
        — models recover from a malformed emission surprisingly often, and one
        extra call is cheaper than degrading a trust dimension to low confidence
        over a stray token.
        """
        request = self._build_request(
            messages,
            json_schema=json_schema,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        response = await self._complete_with_retries(request)
        try:
            return _parse_json(response.text)
        except ValueError as exc:
            logger.warning(
                "llm returned unparseable json; retrying once",
                extra=bind(provider=self._provider.name, model=request.model),
            )
            retry = await self._complete_with_retries(request)
            try:
                return _parse_json(retry.text)
            except ValueError as retry_exc:
                raise ProviderError(
                    f"LLM did not return valid JSON after a retry: {retry_exc}"
                ) from exc

    async def health(self) -> bool:
        """Report whether the provider looks usable. Never raises."""
        try:
            return await self._provider.health()
        except Exception as exc:  # a health probe must not take /health down
            logger.warning(
                "llm health probe raised",
                extra=bind(provider=self._provider.name, error=str(exc)),
            )
            return False

    async def aclose(self) -> None:
        """Close the underlying provider."""
        await self._provider.aclose()


def _parse_json(text: str) -> Any:
    """Parse model output as JSON, tolerating code fences and preamble.

    Args:
        text: Raw completion text.

    Returns:
        The parsed value.

    Raises:
        ValueError: If no JSON value can be recovered.
    """
    candidate = text.strip()

    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Last resort: models sometimes prepend "Here is the result:". Take the
    # widest bracketed span and try that.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError("no JSON value found in completion text")
