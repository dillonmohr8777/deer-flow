"""Use the released SDK and an HTTP transport double; never call a provider."""

import json

import httpx2
import openai
import pytest

from app.gateway.openai_agent_service import OpenAIAgentService


@pytest.mark.asyncio
async def test_released_sdk_serializes_beta_sessions_and_streams_artifact(tmp_path):
    assert openai.__version__ == "3.22.1"
    requests = []
    remote = {}

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.openai.com"
        assert request.headers["OpenAI-Beta"] == "agents=v1"
        if request.method == "POST" and request.url.path == "/v1/agents/sessions":
            body = json.loads(request.content)
            assert body["agent"]["model"] == "gpt-6.1-sol"
            assert body["agent"]["multi_agent"] == {"enabled": True, "max_concurrent_subagents": 3}
            assert body["environment"]["network"] == {"access": "disabled"}
            assert body["agent"]["tools"] == []
            remote.update(id="sess_typed", status="idle", required_actions=[], metadata=body["metadata"], environment={"type": "openai_hosted", "id": "env_1"}, usage=None)
            return httpx2.Response(200, json=remote)
        if request.url.path == "/v1/agents/sessions/sess_typed":
            return httpx2.Response(200, json=remote)
        if request.url.path.endswith("/artifacts/artifact_1/content"):
            return httpx2.Response(200, content=b"actual artifact")
        if request.url.path.endswith("/artifacts/artifact_1"):
            return httpx2.Response(200, json={"id": "artifact_1", "size_bytes": 15, "path": "/workspace/outputs/result.txt", "turn_id": "turn_1", "session_id": "sess_typed"})
        if request.url.path.endswith(("/turns", "/items", "/artifacts")):
            return httpx2.Response(200, json={"object": "list", "data": [], "has_more": False})
        raise AssertionError(f"Unexpected offline path: {request.method} {request.url.path}")

    async with openai.AsyncOpenAI(api_key="offline-placeholder", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))) as client:
        service = OpenAIAgentService(tmp_path / "agents.sqlite", client_factory=lambda: client)
        result = await service.create("alice", "Bounded test", "Test", "c")
        assert result["turn"] is None
        assert await service.artifact("alice", result["id"], "artifact_1") == b"actual artifact"
    assert len(requests) == 7
