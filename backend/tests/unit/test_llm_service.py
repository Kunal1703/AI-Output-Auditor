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
    # Explicit "hidden" rather than settings.llm.reasoning_format: the deployed
    # model is non-reasoning (llama-3.3-70b rejects the parameter), but the
    # provider's job of forwarding it when a reasoning model *is* configured is
    # what this asserts.
    counter = {"n": 0}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder(200, ok_body(), counter=counter))
    )
    svc = DefaultLLMService(
        GroqProvider(api_key="k", reasoning_format="hidden", client=client), settings
    )
    await call(svc)
    payload = json.loads(counter["last"].content)
    # A reasoning model emits a <think> block without this, corrupting the JSON.
    assert payload.get("reasoning_format") == "hidden"


async def test_reasoning_effort_sent_when_configured(settings):
    """Symmetric to reasoning_format: forwarded when set, for a reasoning model."""
    counter = {"n": 0}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder(200, ok_body(), counter=counter))
    )
    svc = DefaultLLMService(
        GroqProvider(api_key="k", reasoning_effort="none", client=client), settings
    )
    await call(svc)
    assert json.loads(counter["last"].content).get("reasoning_effort") == "none"


async def test_reasoning_params_omitted_by_default(settings):
    """llama-3.3-70b 400s on either param; unset means the key is absent."""
    counter = {"n": 0}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder(200, ok_body(), counter=counter))
    )
    await call(DefaultLLMService(GroqProvider(api_key="k", client=client), settings))
    payload = json.loads(counter["last"].content)
    assert "reasoning_format" not in payload
    assert "reasoning_effort" not in payload


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


# --------------------------------------------------------------------------- #
# Model availability — startup validation catches a retired/unavailable model
# --------------------------------------------------------------------------- #


def models_body(*ids: str) -> dict:
    return {"data": [{"id": i} for i in ids]}


async def test_available_models_lists_served_ids():
    def handle(request):
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json=models_body("llama-3.3-70b-versatile", "x"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    models = await GroqProvider(api_key="k", client=client).available_models()
    assert models == {"llama-3.3-70b-versatile", "x"}


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_available_models_is_none_on_error_status(status):
    """'Cannot check' (None) must be distinct from 'nothing available' (set())."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder(status, {"error": {"message": "x"}}))
    )
    assert await GroqProvider(api_key="k", client=client).available_models() is None


async def test_available_models_is_none_on_transport_error():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await GroqProvider(api_key="k", client=client).available_models() is None


async def test_available_models_is_none_without_key():
    assert await GroqProvider(api_key=None).available_models() is None


def _container_stub(model: str, models):
    """A minimal stand-in exposing only what verify_model reads."""
    from types import SimpleNamespace

    class _LLM:
        async def available_models(self):
            return models

    return SimpleNamespace(
        settings=SimpleNamespace(llm=SimpleNamespace(model=model, provider="groq")),
        llm=_LLM(),
    )


async def test_verify_model_raises_when_model_unavailable():
    """The M7.1 guarantee: a retired model fails startup, not eight audits."""
    from app.app import ServiceContainer
    from app.core.errors import ConfigurationError

    stub = _container_stub("qwen/qwen3-32b", {"llama-3.3-70b-versatile"})
    with pytest.raises(ConfigurationError) as raised:
        await ServiceContainer.verify_model(stub)
    # The message names both the bad id and the real options.
    assert "qwen/qwen3-32b" in raised.value.message
    assert "llama-3.3-70b-versatile" in raised.value.message


async def test_verify_model_passes_when_model_available():
    from app.app import ServiceContainer

    stub = _container_stub("llama-3.3-70b-versatile", {"llama-3.3-70b-versatile", "x"})
    await ServiceContainer.verify_model(stub)  # does not raise


async def test_verify_model_skips_when_availability_unknown():
    """Offline / unenumerable provider must not harden into a false failure."""
    from app.app import ServiceContainer

    stub = _container_stub("anything", None)
    await ServiceContainer.verify_model(stub)  # does not raise
