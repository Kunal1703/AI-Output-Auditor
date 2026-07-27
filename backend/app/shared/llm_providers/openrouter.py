"""OpenRouter provider — the paid backend, present but not wired.

**Status: inactive.** Groq is the active provider (see ``groq.py``). This module
is complete and ready, but nothing imports it: its wiring in ``registry.py``
ships commented out under the ``PAID PROVIDER`` markers. Uncomment those blocks,
set ``OPENROUTER_API_KEY`` and ``LLM_PROVIDER=openrouter``, and it takes over
with no engine changes — which is the provider seam of Document 4 §2 doing its
job.

OpenRouter exposes an OpenAI-compatible ``/chat/completions`` endpoint that
fronts many model vendors. That suits this system when budget allows: the eight
engines call a range of judge and extraction models, and routing them through
one gateway keeps credentials and rate limits in one place.

This module is transport only, per the contract in ``base.py``. Retries,
timeout policy, and degradation live in the Shared LLM Service.

Note:
    Unlike Groq, OpenRouter supports the ``json_schema`` response format on most
    models, so this provider requests it directly rather than falling back to
    ``json_object``.
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

__all__ = ["OpenRouterProvider"]

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """Talks to OpenRouter's OpenAI-compatible chat completions API.

    The client is created once and reused so that a wave of concurrent engines
    shares a connection pool rather than opening a socket per call.

    Args:
        api_key: OpenRouter API key. Sourced from ``AUDITOR_LLM__API_KEY``;
            absent in local runs that never call the provider, in which case
            :meth:`complete` raises a clear configuration error instead of a
            401 from upstream.
        base_url: API root. Override to point at a compatible gateway.
        app_url: Sent as ``HTTP-Referer``. OpenRouter uses it for attribution.
        app_title: Sent as ``X-Title``, likewise.
        client: Inject a client to test without network access.
    """

    name = "openrouter"

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        app_url: str = "https://github.com/ai-output-auditor",
        app_title: str = "AI Output Auditor",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._app_url = app_url
        self._app_title = app_title
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_client = client is None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._app_url,
            "X-Title": self._app_title,
        }

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        """Translate the neutral request into OpenRouter's wire format."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_schema is not None:
            # Engine pipelines consume structured ledgers and verdicts, so ask
            # for schema-constrained JSON rather than parsing prose.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "audit_stage_output",
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        payload.update(request.extra)
        return payload

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Issue one chat completion against OpenRouter.

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
            raise ProviderError(
                "OpenRouter API key is not configured. Set AUDITOR_LLM__API_KEY "
                "in backend/.env (see .env.example)."
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
                f"OpenRouter did not respond within {request.timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenRouter transport error: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"OpenRouter returned {response.status_code}: "
                f"{_safe_error_text(response)}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("OpenRouter returned a non-JSON body.") from exc

        return self._parse(body, request)

    def _parse(
        self, body: dict[str, Any], request: CompletionRequest
    ) -> CompletionResponse:
        """Translate an OpenRouter payload into the neutral response."""
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(
                "OpenRouter returned no choices; the request may have been "
                "filtered or the model may be unavailable."
            )
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            raise ProviderError("OpenRouter response contained no text content.")

        usage = body.get("usage") or {}
        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            # Worth surfacing: a truncated completion is the usual cause of
            # structured output that fails to parse downstream.
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
        """Report whether OpenRouter looks reachable and configured.

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
            logger.warning("openrouter health probe failed", extra=bind(error=str(exc)))
            return False

    async def aclose(self) -> None:
        """Close the HTTP client, if this provider created it."""
        if self._owns_client:
            await self._client.aclose()


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
