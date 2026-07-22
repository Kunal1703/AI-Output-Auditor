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
import time
from typing import Any, Sequence

from app.core.config import Settings
from app.core.errors import ProviderError
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

    async def available_models(self) -> set[str] | None:
        """Return the model ids the provider will currently serve, if knowable.

        Delegates to the provider. Returns ``None`` when the set cannot be
        determined — no enumeration endpoint, or the probe failed — so the
        caller distinguishes "cannot check" from a real empty list and does not
        block a run over a transient failure. The default suits fakes and any
        service whose provider cannot enumerate; the production service
        overrides it.
        """
        return None

    async def aclose(self) -> None:
        """Release provider resources on shutdown."""
        return None


class BaseLLMService(LLMService):
    """Alias kept for readability at injection sites.

    Type annotations that want "any LLM service" should use :class:`LLMService`.
    """


class _TokenRateLimiter:
    """Paces provider calls to stay under a tokens-per-minute ceiling.

    **Why this lives in the service, not the engines.** Groq — like most hosted
    providers — admits a request against ``prompt_tokens + max_tokens`` and rate
    limits on a rolling per-minute window. The orchestrator fires six engines
    concurrently in wave 1 (Document 2, §8), and each fires several stage calls,
    so the instant a run starts the demand spikes far above a free-tier TPM. The
    provider answers with 429s, and the engines — correctly — read a provider
    failure as a verification gap and degrade (Document 4, §12). The result is a
    report where a semi-random subset of trust dimensions reads *Unable to
    Verify* for no reason but a rate limit. Pacing is the missing integration
    piece: it turns the burst into orderly waiting so the calls actually land.

    A continuously-refilling bucket holds ``capacity`` tokens and refills at
    ``capacity / 60`` tokens per second. Each call reserves an estimate of the
    tokens it will cost — ``prompt_tokens + max_tokens``, matching the provider's
    own admission accounting — and waits when the bucket is short. The
    reservation is deliberately conservative: it is never smaller than the
    request's actual usage, so the client bucket drains at least as fast as the
    provider's window fills and a run paced under ``capacity`` does not 429.

    Shared across every engine because it is constructed once with the
    application-scoped LLM Service; the budget it guards is the one shared
    provider account, so one limiter per process is exactly right.

    Note:
        Not thread-safe by design — engines run as asyncio tasks on one event
        loop. The lock serializes only the bucket read-modify-write, which never
        awaits, so it cannot become a bottleneck of its own.
    """

    def __init__(self, tokens_per_minute: int) -> None:
        self._capacity = float(tokens_per_minute)
        self._rate = tokens_per_minute / 60.0
        self._available = float(tokens_per_minute)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        """Wait until ``tokens`` of budget are available, then consume them.

        A single request larger than the whole per-minute budget cannot be
        satisfied outright; it waits for a full bucket and proceeds rather than
        deadlocking, since refusing it would strand a legitimate call forever.
        """
        need = min(float(tokens), self._capacity)
        while True:
            async with self._lock:
                now = time.monotonic()
                self._available = min(
                    self._capacity,
                    self._available + (now - self._updated) * self._rate,
                )
                self._updated = now
                if self._available >= need:
                    self._available -= need
                    return
                wait = (need - self._available) / self._rate
            await asyncio.sleep(wait)


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
        tpm = settings.llm.tokens_per_minute
        # None when pacing is disabled (tpm <= 0), so the common paid-tier path
        # pays nothing — no lock, no bookkeeping, calls go straight through.
        self._rate_limiter = _TokenRateLimiter(tpm) if tpm > 0 else None

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

    @staticmethod
    def _estimate_tokens(request: CompletionRequest) -> int:
        """Estimate a request's token cost for pacing.

        Matches the provider's admission accounting: ``prompt_tokens +
        max_tokens``. The prompt half is estimated at ~4 characters per token —
        the standard rough factor for English — which is imprecise but only ever
        needs to be good enough to keep the wave under the ceiling; the limiter's
        budget already sits below the true limit to absorb the slack. A small
        constant covers per-message role overhead.
        """
        chars = sum(len(message.content) for message in request.messages)
        prompt_estimate = chars // 4 + 16
        return prompt_estimate + request.max_tokens

    async def _complete_with_retries(
        self, request: CompletionRequest
    ) -> CompletionResponse:
        """Call the provider, retrying *transient* failures with backoff.

        Document 4 §12 mandates bounded retries with backoff and no infinite
        retries. The budget is ``llm.max_retries``; jitter avoids a wave of six
        parallel engines synchronizing their retries into a thundering herd.

        **A permanent failure is not retried at all.** The provider classifies
        its own errors (``ProviderError.retryable``), because it is the layer
        that knows a 401 from a 503. Retrying a rejected key or a malformed
        request cannot succeed — it only spends the backoff and turns a clear
        error into a slow one. Measured before this check existed: a missing key
        cost **9.3s per call** and, through ``complete_json``'s parse-retry,
        ~19s; across eight engines that is minutes of silence on the single most
        likely first-run misconfiguration.

        A provider that sets ``retry_after`` is obeyed as a floor: a rate
        limiter naming its own interval knows better than our curve does.
        """
        cfg = self._settings.llm
        last_error: ProviderError | None = None

        for attempt in range(cfg.max_retries + 1):
            try:
                # Pace before every attempt: a retry is a fresh call that costs
                # the provider tokens too, so it must wait its turn like any
                # other. No-op when pacing is disabled.
                if self._rate_limiter is not None:
                    await self._rate_limiter.acquire(self._estimate_tokens(request))
                return await self._provider.complete(request)
            except ProviderError as exc:
                last_error = exc

                if not exc.retryable:
                    logger.error(
                        "llm call failed permanently; not retrying",
                        extra=bind(
                            provider=self._provider.name,
                            model=request.model,
                            status_code=exc.status_code,
                            error=type(exc).__name__,
                        ),
                    )
                    raise

                if attempt >= cfg.max_retries:
                    break

                delay = cfg.retry_backoff_seconds * (2**attempt)
                delay *= 0.5 + random.random()  # noqa: S311 — jitter, not crypto
                if exc.retry_after is not None:
                    # Honor Retry-After as a floor, but cap it: under a burst a
                    # provider can name a wait longer than the engine's whole
                    # budget for a limit that resets within a minute, which would
                    # turn a transient 429 into a guaranteed timeout+degrade.
                    retry_after = exc.retry_after
                    if cfg.retry_after_cap_seconds > 0:
                        retry_after = min(retry_after, cfg.retry_after_cap_seconds)
                    delay = max(delay, retry_after)
                logger.warning(
                    "llm call failed; retrying",
                    extra=bind(
                        provider=self._provider.name,
                        model=request.model,
                        attempt=attempt + 1,
                        max_attempts=cfg.max_retries + 1,
                        retry_in_s=round(delay, 2),
                        status_code=exc.status_code,
                        error=type(exc).__name__,
                    ),
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # loop only exits via return, raise, or break
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

        The parse-retry only happens after a call that *succeeded* and returned
        text, so a permanent provider failure raises out of the first
        :meth:`_complete_with_retries` and never reaches it.
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

    async def available_models(self) -> set[str] | None:
        """Return the provider's currently-served model ids, or None. Never raises."""
        try:
            return await self._provider.available_models()
        except Exception as exc:  # a readiness probe must not take startup down
            logger.warning(
                "llm models probe raised",
                extra=bind(provider=self._provider.name, error=str(exc)),
            )
            return None

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
