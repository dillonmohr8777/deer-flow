"""Offline exact guard terminal envelopes through the real SDK error shape."""

from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage
from openai import OpenAI

from deerflow.agents.middlewares import llm_error_handling_middleware as errors
from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture(autouse=True)
def reset_limiter():
    prior = errors._PROCESS_LIMITER, errors._CAP_RESOLVED
    errors._PROCESS_LIMITER = None
    errors._CAP_RESOLVED = False
    yield
    errors._PROCESS_LIMITER, errors._CAP_RESOLVED = prior


def middleware():
    return errors.LLMErrorHandlingMiddleware(
        app_config=AppConfig(
            sandbox=SandboxConfig(use="offline-unused"),
            llm_call=LlmCallConfig(retry_max_attempts=3, retry_base_delay_ms=1, retry_cap_delay_ms=1),
        )
    )


def sdk_error(envelope):
    # Real SDK status-error construction unwraps body.error, while response.json()
    # retains the guard's top-level retry:false. Never send this synthetic request.
    client = OpenAI(api_key="offline-synthetic", base_url="http://127.0.0.1:2042/v1", max_retries=0)
    try:
        response = httpx.Response(429, json=envelope, request=httpx.Request("POST", "http://127.0.0.1:2042/v1/chat/completions"))
        return client._make_status_error("synthetic guard refusal", body=envelope, response=response)
    finally:
        client.close()


def guard_envelope(**extra):
    return {"error": {"type": "momo_guard_stopped", "message": "guard_stopped_after_uncertain_outcome", "request_id": "fixture"}, **extra}


def test_exact_guard_false_is_terminal_with_actual_unwrapped_sdk_body():
    exc = sdk_error(guard_envelope(retry=False))
    assert exc.body == guard_envelope()["error"]
    assert middleware()._classify_error(exc) == (False, "guard_stopped")


@pytest.mark.parametrize("flag", [True, 0, 1, "false", None, [], {}])
def test_nonboolean_false_guard_flag_preserves_normal_429_classification(flag):
    assert middleware()._classify_error(sdk_error(guard_envelope(retry=flag))) == (True, "transient")


def test_missing_guard_flag_preserves_normal_429_classification():
    assert middleware()._classify_error(sdk_error(guard_envelope())) == (True, "transient")


@pytest.mark.parametrize("error_type", ["rate_limit_exceeded", "other_guard_stopped", None, [], {}])
def test_nonexact_guard_type_preserves_provider_429(error_type):
    envelope = guard_envelope(retry=False)
    envelope["error"]["type"] = error_type
    assert middleware()._classify_error(sdk_error(envelope)) == (True, "transient")


def test_raw_complete_guard_envelope_is_terminal_without_response():
    exc = RuntimeError("synthetic")
    exc.body = guard_envelope(retry=False)
    exc.status_code = 429
    assert middleware()._classify_error(exc) == (False, "guard_stopped")


def test_unwrapped_guard_body_without_outer_flag_is_not_terminal():
    exc = sdk_error(guard_envelope())
    exc.response = None
    assert middleware()._classify_error(exc) == (True, "transient")


def test_unread_response_does_not_break_error_classification():
    exc = sdk_error(guard_envelope())
    exc.response = httpx.Response(429, stream=httpx.ByteStream(b"{}"))
    assert middleware()._classify_error(exc) == (True, "transient")


@pytest.mark.parametrize("response_body", [b"not-json", b"[]", b"null", b'{"retry":false}', b'{"retry":false,"error":null}'])
def test_malformed_or_incomplete_response_does_not_create_guard_terminal_status(response_body):
    exc = sdk_error(guard_envelope())
    exc.response = httpx.Response(429, content=response_body, request=httpx.Request("POST", "http://127.0.0.1:2042/v1/chat/completions"))
    assert middleware()._classify_error(exc) == (True, "transient")


def test_sync_guard_stop_calls_handler_once_without_backoff_or_retry_event(monkeypatch):
    instance = middleware()
    calls = 0

    def forbidden(*_args, **_kwargs):
        raise AssertionError("guard stop must not retry")

    monkeypatch.setattr(errors.time, "sleep", forbidden)
    monkeypatch.setattr(instance, "_emit_retry_event", forbidden)

    def handler(_request):
        nonlocal calls
        calls += 1
        raise sdk_error(guard_envelope(retry=False))

    result = instance.wrap_model_call(SimpleNamespace(), handler)
    assert calls == 1
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "guard_stopped"
    assert instance._circuit_failure_count == 0


@pytest.mark.asyncio
async def test_async_guard_stop_calls_handler_once_without_backoff_or_retry_event(monkeypatch):
    instance = middleware()
    calls = 0

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("guard stop must not retry")

    monkeypatch.setattr(errors.asyncio, "sleep", forbidden)
    monkeypatch.setattr(instance, "_aemit_retry_event", forbidden)

    async def handler(_request):
        nonlocal calls
        calls += 1
        raise sdk_error(guard_envelope(retry=False))

    result = await instance.awrap_model_call(SimpleNamespace(), handler)
    assert calls == 1
    assert result.additional_kwargs["deerflow_error_fallback"] is True
    assert result.additional_kwargs["error_reason"] == "guard_stopped"
    assert instance._circuit_failure_count == 0


@pytest.mark.parametrize("envelope", [guard_envelope(retry=True), {"error": {"type": "rate_limit_exceeded", "message": "synthetic"}, "retry": False}])
def test_sync_other_429_keeps_one_retry_then_success(monkeypatch, envelope):
    instance = middleware()
    calls = 0
    waits = []
    monkeypatch.setattr(errors.time, "sleep", waits.append)
    monkeypatch.setattr(instance, "_emit_retry_event", lambda *_args, **_kwargs: None)

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sdk_error(envelope)
        return ModelResponse(result=[AIMessage(content="synthetic recovered")])

    result = instance.wrap_model_call(SimpleNamespace(), handler)
    assert calls == 2
    assert len(waits) == 1
    assert result.result[0].content == "synthetic recovered"


@pytest.mark.parametrize("envelope", [guard_envelope(retry=True), {"error": {"type": "rate_limit_exceeded", "message": "synthetic"}, "retry": False}])
@pytest.mark.asyncio
async def test_async_other_429_keeps_one_retry_then_success(monkeypatch, envelope):
    instance = middleware()
    calls = 0
    waits = []

    async def sleep(delay):
        waits.append(delay)

    async def emit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(errors.asyncio, "sleep", sleep)
    monkeypatch.setattr(instance, "_aemit_retry_event", emit)

    async def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sdk_error(envelope)
        return ModelResponse(result=[AIMessage(content="synthetic recovered")])

    result = await instance.awrap_model_call(SimpleNamespace(), handler)
    assert calls == 2
    assert len(waits) == 1
    assert result.result[0].content == "synthetic recovered"
