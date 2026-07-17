"""Groq provider — the auditor's primary LLM backend.

Groq exposes an OpenAI-compatible ``/chat/completions`` endpoint and serves open
models on its own inference hardware. It suits this system for two reasons: a
free tier that makes the eight-engine fan-out affordable during development, and
latency low enough that a wave of six concurrent engines stays responsive.

This module is transport only, per the contract in ``base.py``. Retries, timeout
policy, and degradation live in the Shared LLM Service. A paid provider can be
added later as a sibling module plus a registry entry — see ``registry.py``,
where the OpenRouter wiring is present but commented out (Document 4, §2).

**Two Groq-specific details this provider handles.**

*Reasoning models.* The default model, ``qwen/qwen3-32b``, is a reasoning model:
left alone it emits a ``<think>`` block before its answer, which corrupts the
structured JSON the engine pipelines parse. Groq's ``reasoning_format``
parameter suppresses it. It is configuration (``llm.reasoning_format``) rather
than a hardcoded constant, because it is only valid on reasoning models — a
non-reasoning model rejects it.

*Structured output.* Groq's ``json_schema`` response format is supported on a
subset of models, while ``json_object`` is broadly available. This provider
therefore requests ``json_object`` whenever the caller supplies a schema, and
leaves schema conformance to the prompt (Prompt Manager) plus the LLM Service's
parsing. Requesting ``json_schema`` unconditionally would 400 on most Groq
models — including the default.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import ProviderError, ProviderTimeoutError
from app.core.logging import bind, get_logger
from app.shared.llm_providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
)

__all__ = ["GroqProvider"]

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(LLMProvider):
    """Talks to Groq's OpenAI-compatible chat completions API.

    The client is created once and reused so that a wave of concurrent engines
    shares a connection pool rather than opening a socket per call.

    Args:
        api_key: Groq API key. Sourced from ``GROQ_API_KEY``; absent in local
            runs that never call the provider, in which case :meth:`complete`
            raises a clear configuration error instead of a 401 from upstream.
        base_url: API root. Override to point at a compatible gateway.
        reasoning_format: Groq's reasoning-output mode — ``hidden``, ``parsed``,
            or ``raw``. ``hidden`` keeps a reasoning model's ``<think>`` block
            out of the response body. ``None`` omits the parameter entirely,
            which is required for non-reasoning models that reject it.
        client: Inject a client to test without network access.
    """

    name = "groq"

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        reasoning_format: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._reasoning_format = reasoning_format
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_client = client is None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        """Translate the neutral request into Groq's wire format."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if self._reasoning_format is not None:
            payload["reasoning_format"] = self._reasoning_format

        if request.json_schema is not None:
            # json_object, not json_schema: Groq supports the latter only on
            # select models and rejects it on the default. The schema still
            # reaches the model through the rendered prompt, and the LLM Service
            # parses and validates what comes back.
            payload["response_format"] = {"type": "json_object"}

        payload.update(request.extra)
        return payload

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Issue one chat completion against Groq.

        Args:
            request: The provider-neutral request.

        Returns:
            The provider-neutral response.

        Raises:
            ProviderError: The key is missing, the response was an error, or the
                payload did not match the expected shape.
            ProviderTimeoutError: The call exceeded ``request.timeout_seconds``.
        """
        if not self._api_key:
            # Permanent by construction: no number of retries conjures a key.
            raise ProviderError(
                "Groq API key is not configured. Set GROQ_API_KEY in "
                "backend/.env (see .env.example).",
                retryable=False,
            )
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._build_payload(request),
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Groq did not respond within {request.timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            # Transport-level: DNS, connection reset, TLS. Genuinely transient.
            raise ProviderError(f"Groq transport error: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Groq returned {response.status_code}: {_safe_error_text(response)}",
                retryable=_is_retryable(response.status_code),
                retry_after=_retry_after(response),
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("Groq returned a non-JSON body.") from exc

        return self._parse(body, request)

    def _parse(
        self, body: dict[str, Any], request: CompletionRequest
    ) -> CompletionResponse:
        """Translate a Groq payload into the neutral response."""
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(
                "Groq returned no choices; the request may have been filtered "
                "or the model may be unavailable."
            )
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            raise ProviderError("Groq response contained no text content.")

        usage = body.get("usage") or {}
        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            # Worth surfacing: a truncated completion is the usual cause of
            # structured output that fails to parse downstream. On a reasoning
            # model it often means the think block consumed the token budget.
            logger.warning(
                "completion truncated at max_tokens",
                extra=bind(model=request.model, max_tokens=request.max_tokens),
            )
        return CompletionResponse(
            text=text,
            model=body.get("model", request.model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=finish_reason,
            raw=body,
        )

    async def health(self) -> bool:
        """Report whether Groq looks reachable and configured.

        Queries the models list rather than generating a completion — a health
        probe should not cost tokens. Never raises; a probe that throws takes
        ``/health`` down with it.
        """
        if not self._api_key:
            return False
        try:
            response = await self._client.get(
                f"{self._base_url}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            return response.status_code < 400
        except httpx.HTTPError as exc:
            logger.warning("groq health probe failed", extra=bind(error=str(exc)))
            return False

    async def aclose(self) -> None:
        """Close the HTTP client, if this provider created it."""
        if self._owns_client:
            await self._client.aclose()


def _is_retryable(status_code: int) -> bool:
    """Whether another identical request could plausibly succeed.

    **429 is retryable and that is the important one.** Groq's free tier rate
    limits, and this auditor fans out to six concurrent engines in wave 1 — so a
    429 is not an exceptional case here, it is Tuesday. Treating it as permanent
    would degrade half the dimensions of a perfectly good audit.

    **4xx auth and request errors are not.** A rejected key, a forbidden model,
    or a malformed payload fails identically on every attempt; retrying only
    converts a clear error into a slow one. The default model rejecting
    ``reasoning_format`` would land here as a 400 — exactly the misconfiguration
    a first-time user hits, and exactly the one that must fail fast and say why.

    **5xx is retryable.** An upstream fault is the transient case retries exist
    for.
    """
    if status_code == 429:
        return True
    if 500 <= status_code < 600:
        return True
    return False


def _retry_after(response: httpx.Response) -> float | None:
    """Read the ``Retry-After`` header, when the provider set one.

    A rate limiter that names its own interval knows better than our exponential
    curve does. Only the delta-seconds form is parsed; the HTTP-date form is
    rare in practice and guessing at a clock skew would be worse than falling
    back to the configured backoff.
    """
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _safe_error_text(response: httpx.Response) -> str:
    """Extract a short error message without leaking a full response body."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message", error))[:200]
    return str(error or payload)[:200]
