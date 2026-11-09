"""Tests for deerflow.models.momo_fallback.CodexWithFallback.

No network: the Codex call (_call_codex_api) and the fallback model factory
(deerflow.models.factory.create_chat_model) are monkeypatched.

Covers:
- 429 / quota errors fall back, with the bound tools preserved
- non-quota errors are raised unchanged and never reach the fallback
- a normal Codex success is returned untouched
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.credential_loader import CodexCliCredential

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Look something up.",
        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
    },
}


def _make_model(**kwargs):
    from deerflow.models.momo_fallback import CodexWithFallback

    cred = CodexCliCredential(access_token="tok-test", account_id="acc-test")
    with patch("deerflow.models.openai_codex_provider.load_codex_cli_credential", return_value=cred):
        return CodexWithFallback(model="gpt-6.1-terra", reasoning_effort="high", **kwargs)


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
    return httpx.HTTPStatusError(f"status {status}", request=request, response=httpx.Response(status, request=request))


class _FakeFallback:
    """Stands in for the model create_chat_model builds; records bind_tools and invoke."""

    def __init__(self):
        self.bound_tools = None
        self.invoked_with = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages, stop=None):
        self.invoked_with = messages
        return AIMessage(content="from fallback", tool_calls=[{"name": "lookup", "args": {"q": "x"}, "id": "call-1", "type": "tool_call"}])


@pytest.fixture
def factory(monkeypatch):
    """Patch create_chat_model; yields (fake_model, calls) where calls collects factory kwargs."""
    fake = _FakeFallback()
    calls: list[dict] = []

    def _create(**kwargs):
        calls.append(kwargs)
        return fake

    monkeypatch.setattr("deerflow.models.factory.create_chat_model", _create)
    return fake, calls


def _raise(exc):
    def _call(self, messages, tools=None):
        raise exc

    return _call


def test_http_429_falls_back_with_tools_preserved(monkeypatch, factory):
    fake, calls = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _raise(_http_error(429)))
    model = _make_model(fallback_model="openrouter-haiku-5-5-max")

    result = model.bind_tools([TOOL]).invoke([HumanMessage(content="hi")])

    assert result.content == "from fallback"
    assert result.tool_calls[0]["name"] == "lookup"
    assert calls == [{"name": "openrouter-haiku-5-5-max", "thinking_enabled": True}]
    assert [t["function"]["name"] for t in fake.bound_tools] == ["lookup"]
    assert fake.invoked_with[0].content == "hi"
    assert result.response_metadata["momo_fallback_from"] == "gpt-6.1-terra"
    assert result.response_metadata["momo_fallback_reason"] == "HTTPStatusError"


def test_quota_error_text_falls_back_without_tools(monkeypatch, factory):
    fake, calls = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _raise(RuntimeError("You have hit your usage limit")))
    model = _make_model()

    result = model._generate([HumanMessage(content="hi")])

    assert result.generations[0].message.content == "from fallback"
    assert len(calls) == 1
    assert fake.bound_tools is None  # no tools bound, so bind_tools is skipped


def test_flat_codex_tool_format_is_converted_for_the_fallback(monkeypatch, factory):
    fake, _ = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _raise(_http_error(429)))
    flat_tool = {"type": "function", "name": "lookup", "description": "Look something up.", "parameters": {"type": "object", "properties": {}}}

    _make_model()._generate([HumanMessage(content="hi")], tools=[flat_tool])

    assert fake.bound_tools == [{"type": "function", "function": {"name": "lookup", "description": "Look something up.", "parameters": {"type": "object", "properties": {}}}}]


@pytest.mark.parametrize("error", [ValueError("malformed request payload"), _http_error(400), _http_error(404)])
def test_non_quota_error_is_raised_unchanged(monkeypatch, factory, error):
    _, calls = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _raise(error))

    with pytest.raises(type(error)) as excinfo:
        _make_model()._generate([HumanMessage(content="hi")])

    assert excinfo.value is error
    assert calls == []  # the fallback model was never built


def test_empty_fallback_model_reraises_even_on_429(monkeypatch, factory):
    _, calls = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    error = _http_error(429)
    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _raise(error))

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _make_model(fallback_model="")._generate([HumanMessage(content="hi")])

    assert excinfo.value is error
    assert calls == []


def test_success_is_untouched_and_never_builds_the_fallback(monkeypatch, factory):
    _, calls = factory
    from deerflow.models.openai_codex_provider import CodexChatModel

    seen: dict = {}

    def _ok(self, messages, tools=None):
        seen["tools"] = tools
        return {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "from codex"}]}],
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            "model": "gpt-6.1-terra",
        }

    monkeypatch.setattr(CodexChatModel, "_call_codex_api", _ok)

    result = _make_model().bind_tools([TOOL]).invoke([HumanMessage(content="hi")])

    assert result.content == "from codex"
    assert "momo_fallback_from" not in result.response_metadata
    assert result.response_metadata["model"] == "gpt-6.1-terra"
    assert seen["tools"][0]["name"] == "lookup"  # tools reach Codex in its flat format
    assert calls == []
