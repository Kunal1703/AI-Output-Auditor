"""LLM Service + Groq provider (Document 4, §4/§12).

The split under test: the **provider** does transport and classifies its own
failures; the **service** owns retry, timeout, and JSON policy. Transport is
mocked with ``httpx.MockTransport`` so every failure mode is exercised
deterministically rather than hoped for.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.core.errors import ProviderError, ProviderTimeoutError
from app.shared.llm_providers.base import ChatMessage, LLMProvider
from app.shared.llm_providers.groq import GroqProvider
from app.shared.llm_providers.registry import build_provider
from app.shared.llm_service import DefaultLLMService

pytestmark = pytest.mark.unit


def ok_body(content: str = '{"ok": true}') -> dict:
    return {
        "model": "qwen/qwen3-32b",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }


def service(handler, settings):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DefaultLLMService(
        GroqProvider(
            api_key="gsk_test",
            reasoning_format=settings.llm.reasoning_format,
            client=client,
        ),
        settings,
    )


def responder(status: int, body: dict, headers=None, counter=None):
    def handle(request):
        if counter is not None:
            counter["n"] += 1
            counter["last"] = request
        return httpx.Response(status, json=body, headers=headers or {})

    return handle


async def call(svc):
    return await svc.complete_json(
        [ChatMessage(role="user", content="hi")], json_schema={}
    )


# --------------------------------------------------------------------------- #
# Configuration and initialization
# --------------------------------------------------------------------------- #


def test_provider_comes_from_configuration(settings):
    provider = build_provider(settings)
    assert provider.name == "groq"
    assert isinstance(provider, LLMProvider)


def test_no_hardcoded_api_key_anywhere():
    """A key in source is a key in git history, forever."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        str(p)
        for p in app.rglob("*.py")
        if re.search(r"gsk_[A-Za-z0-9]{8,}", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"hardcoded key material in {offenders}"


async def test_request_carries_configured_model_and_temperature(settings):
    counter = {"n": 0}
    await call(service(responder(200, ok_body(), counter=counter), settings))
    payload = json.loads(counter["last"].content)

    assert payload["model"] == settings.llm.model
    assert payload["temperature"] == 0.0  # reproducibility (Document 4, §11)
    assert counter["last"].headers["authorization"].startswith("Bearer ")
    assert counter["last"].url.path.endswith("/chat/completions")


# --------------------------------------------------------------------------- #
# Structured JSON — the Groq specifics
# --------------------------------------------------------------------------- #


async def test_requests_json_object_not_json_schema(settings):
    """Groq rejects json_schema on the default model (Document 4, §2)."""
    counter = {"n": 0}
    await call(service(responder(200, ok_body(), counter=counter), settings))
    payload = json.loads(counter["last"].content)
    assert payload["response_format"] == {"type": "json_object"}


async def test_reasoning_format_sent_when_configured(settings):
    counter = {"n": 0}
    await call(service(responder(200, ok_body(), counter=counter), settings))
    payload = json.loads(counter["last"].content)
    # qwen3-32b emits a <think> block without this, corrupting the JSON.
    assert payload.get("reasoning_format") == "hidden"


async def test_reasoning_format_omitted_when_unset(settings):
    """A non-reasoning model 400s on the parameter — it must not be sent."""
    counter = {"n": 0}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder(200, ok_body(), counter=counter))
    )
    svc = DefaultLLMService(
        GroqProvider(api_key="k", reasoning_format=None, client=client), settings
    )
    await call(svc)
    assert "reasoning_format" not in json.loads(counter["last"].content)


@pytest.mark.parametrize(
    "content",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here is the result:\n{"a": 1}',
    ],
    ids=["bare", "fenced", "preamble"],
)
async def test_parses_the_shapes_models_actually_return(settings, content):
    assert await call(service(responder(200, ok_body(content)), settings)) == {"a": 1}


async def test_unparseable_json_retries_once_then_raises(settings):
    counter = {"n": 0}
    with pytest.raises(ProviderError):
        await call(service(responder(200, ok_body("not json"), counter=counter), settings))
    assert counter["n"] == 2  # one parse-retry, then give up


# --------------------------------------------------------------------------- #
# Retry classification — transient retries, permanent does not
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status, headers",
    [(500, None), (503, None), (429, {"retry-after": "0.05"})],
    ids=["500", "503", "429-rate-limit"],
)
async def test_transient_failures_retry(settings, status, headers):
    """429 especially: Groq's free tier rate-limits a six-wide wave routinely."""
    counter = {"n": 0}
    with pytest.raises(ProviderError):
        await call(
            service(responder(status, {"error": {"message": "x"}}, headers, counter),
                    settings)
        )
    assert counter["n"] == settings.llm.max_retries + 1


@pytest.mark.parametrize(
    "status",
    [400, 401, 403, 404],
    ids=["bad-request", "invalid-key", "forbidden", "unknown-model"],
)
async def test_permanent_failures_do_not_retry(settings, status):
    """Retrying a rejected key cannot succeed; it only spends the backoff.

    Measured before this classification existed: a missing key cost 9.3s per
    call and ~19s through the parse-retry. Across eight engines that is minutes
    of silence on the most likely first-run misconfiguration.
    """
    counter = {"n": 0}
    started = time.perf_counter()
    with pytest.raises(ProviderError) as raised:
        await call(
            service(responder(status, {"error": {"message": "x"}}, counter=counter),
                    settings)
        )
    assert counter["n"] == 1
    assert raised.value.retryable is False
    assert raised.value.status_code == status
    assert time.perf_counter() - started < 1.0


async def test_retry_after_is_honoured_as_a_floor(settings):
    """A rate limiter naming its interval knows better than our curve."""
    started = time.perf_counter()
    with pytest.raises(ProviderError):
        await call(
            service(responder(429, {"error": {"message": "slow"}},
                              {"retry-after": "1.0"}), settings)
        )
    assert time.perf_counter() - started >= 3.0  # 3 retries at >= 1s each


# --------------------------------------------------------------------------- #
# Missing key, timeouts, error reporting
# --------------------------------------------------------------------------- #


async def test_missing_key_fails_fast_and_names_the_variable(settings):
    started = time.perf_counter()
    with pytest.raises(ProviderError) as raised:
        await call(DefaultLLMService(GroqProvider(api_key=None), settings))

    assert raised.value.retryable is False
    assert time.perf_counter() - started < 1.0
    assert "GROQ_API_KEY" in raised.value.message
    assert "gsk_" not in raised.value.message  # never echo key material


async def test_timeout_raises_the_specific_error_and_is_retryable(settings):
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ProviderTimeoutError) as raised:
        await call(service(timeout, settings))
    assert raised.value.retryable is True


async def test_error_text_is_truncated(settings):
    with pytest.raises(ProviderError) as raised:
        await call(service(responder(500, {"error": {"message": "x" * 5000}}), settings))
    assert len(raised.value.message) < 400


async def test_health_never_raises(settings):
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    # A health probe that throws takes GET /health down with it.
    assert await service(boom, settings).health() is False
    assert await DefaultLLMService(GroqProvider(api_key=None), settings).health() is False
