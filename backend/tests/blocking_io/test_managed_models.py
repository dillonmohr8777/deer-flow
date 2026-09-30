"""Managed model encryption, persistence and config merging stay off the loop."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from langchain_openai import ChatOpenAI

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel, ManagedModelStore
from deerflow.models.patched_deepseek import PatchedChatDeepSeek


@pytest.mark.asyncio
async def test_admin_catalog_round_trip_offloads_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    body = router.SaveModelRequest(config=ManagedModel(name="test", model="test", base_url="https://example.com/v1", api_key="secret"))
    result = await router.save_model(request, body)
    assert result["has_api_key"] is True
    catalog = await router.list_managed_models(request)
    assert catalog["models"][0]["name"] == "test"
    assert "secret" not in str(catalog)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_name", "base_url", "expected_client"),
    [("deepseek-flash", "https://api.deepseek.com", "PatchedChatDeepSeek"), ("sdk-compat-test", "https://openai-compatible.invalid/v1", "ChatOpenAI")],
    ids=["deepseek", "openai-compatible"],
)
async def test_deepseek_probe_offloads_credentials_and_client_construction(tmp_path, monkeypatch, model_name, base_url, expected_client):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    store = await asyncio.to_thread(ManagedModelStore)
    profile = ManagedModel(name="flash", model=model_name, base_url=base_url, api_key="test-secret")
    saved = await asyncio.to_thread(store.save, profile, expected_revision=None)
    original_catalog = await asyncio.to_thread(store.path.read_bytes)
    constructed = []
    intercepted = []

    def observe_constructor(original):
        def initialize(self, *args, **kwargs):
            with pytest.raises(RuntimeError, match="no running event loop"):
                asyncio.get_running_loop()
            original(self, *args, **kwargs)
            constructed.append(type(self).__name__)

        return initialize

    monkeypatch.setattr(ChatOpenAI, "__init__", observe_constructor(ChatOpenAI.__init__))
    monkeypatch.setattr(PatchedChatDeepSeek, "__init__", observe_constructor(PatchedChatDeepSeek.__init__))

    async def send(client, request, **kwargs):
        intercepted.append(type(request))
        assert request.headers["authorization"] == "Bearer test-secret"
        assert str(request.url) == f"{base_url}/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == model_name
        assert body.get("max_tokens", body.get("max_completion_tokens")) == 32
        if expected_client == "PatchedChatDeepSeek":
            assert body["thinking"] == {"type": "disabled"}
        else:
            assert "thinking" not in body
        chunk = {
            "id": "chat-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model_name,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": "call-test", "type": "function", "function": {"name": "connection_check", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}
            ],
        }
        response_type = httpx2.Response if isinstance(request, httpx2.Request) else httpx.Response
        return response_type(200, request=request, headers={"content-type": "text/event-stream"}, content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

    # Released OpenAI 3.22 uses HTTPX2 by default. Intercept the actual transport
    # while keeping a legacy guard so neither supported path can contact DNS.
    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    draft = ManagedModel(name="flash", model=model_name, base_url=base_url)
    result = await router.test_model(request, router.SaveModelRequest(config=draft, expected_revision=saved.revision))
    assert result == {"ok": True, "message": "success"}
    assert constructed == [expected_client]
    assert intercepted == [httpx2.Request]
    assert await asyncio.to_thread(store.path.read_bytes) == original_catalog
