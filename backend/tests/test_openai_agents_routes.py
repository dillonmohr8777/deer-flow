"""HTTP authorization and validation for the standalone managed agent surface."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.authz import AuthContext
from app.gateway.openai_agent_service import OpenAIAgentService
from app.gateway.routers.openai_agents import router


def _app(tmp_path):
    app = FastAPI()
    app.state.openai_agent_service = OpenAIAgentService(tmp_path / "agents.sqlite")

    @app.middleware("http")
    async def identity(request, call_next):
        actor = request.headers.get("test-actor")
        user = SimpleNamespace(id=actor) if actor else None
        request.state.auth = AuthContext(
            user=user, permissions=request.headers.get("test-permissions", "runs:read,runs:create,runs:cancel").split(","), organization_id=request.headers.get("test-org", "org"), actor_user_id=actor, storage_user_id="shared-storage"
        )
        return await call_next(request)

    app.include_router(router)
    return app


def _headers(client, actor, org="org"):
    headers = {"test-actor": actor, "test-org": org}
    result = client.get("/api/openai-agents/status", headers={**headers, "X-Expected-User-Id": actor})
    assert result.status_code == 200
    return {**headers, "X-Expected-Agent-Scope": result.json()["owner_scope"]}


def test_anonymous_and_permission_fail_closed(tmp_path):
    app = _app(tmp_path)
    app.state.openai_agent_service.snapshot = AsyncMock()
    with TestClient(app) as client:
        assert client.get("/api/openai-agents/status").status_code == 401
        assert client.get("/api/openai-agents/sessions", headers={"test-actor": "alice", "test-permissions": "runs:create"}).status_code == 403
        assert client.post("/api/openai-agents/sessions/known/cancel", headers={"test-actor": "alice", "test-permissions": "runs:read"}).status_code == 403
    app.state.openai_agent_service.snapshot.assert_not_awaited()


def test_actor_and_organization_both_bound_despite_shared_storage(tmp_path):
    app = _app(tmp_path)
    owners = []

    async def list_sessions(owner):
        owners.append(owner)
        return []

    app.state.openai_agent_service.list_sessions = list_sessions
    with TestClient(app) as client:
        for actor, org in (("alice", "org"), ("bob", "org"), ("alice", "other")):
            assert client.get("/api/openai-agents/sessions", headers=_headers(client, actor, org)).status_code == 200
    assert len(set(owners)) == 3


def test_idempotency_required_and_runtime_configuration_cannot_be_injected(tmp_path):
    app = _app(tmp_path)
    app.state.openai_agent_service.create = AsyncMock()
    headers = {"test-actor": "alice"}
    with TestClient(app) as client:
        assert client.post("/api/openai-agents/sessions", headers=headers, json={"input": "Task"}).status_code == 422
        headers["Idempotency-Key"] = "one"
        for field in ("owner", "tools", "environment", "model"):
            assert client.post("/api/openai-agents/sessions", headers=headers, json={"input": "Task", field: "forged"}).status_code == 422
        assert client.post("/api/openai-agents/sessions", headers=headers, json={"input": "   "}).status_code == 422
    app.state.openai_agent_service.create.assert_not_awaited()


def test_other_owner_artifact_and_disabled_browser_are_not_oracles(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        headers = _headers(client, "bob")
        assert client.get("/api/openai-agents/sessions/not-owned/artifacts/x/content", headers=headers).status_code == 404
        assert client.post("/api/openai-agents/sessions/not-owned/browser-approval", headers=headers).status_code == 404


def test_artifact_is_download_only_with_private_cache(tmp_path):
    app = _app(tmp_path)
    app.state.openai_agent_service.artifact = AsyncMock(return_value=b"<script>never inline</script>")
    with TestClient(app) as client:
        result = client.get("/api/openai-agents/sessions/local/artifacts/x/content", headers=_headers(client, "alice"))
    assert result.status_code == 200
    assert result.headers["content-type"] == "application/octet-stream"
    assert result.headers["content-disposition"].startswith("attachment;")
    assert result.headers["cache-control"] == "private, no-store"


def test_stale_actor_and_workspace_fences_precede_all_provider_access(tmp_path):
    app = _app(tmp_path)
    service = app.state.openai_agent_service
    for method in ("list_sessions", "snapshot", "create", "message", "cancel", "artifact", "_storage"):
        setattr(service, method, AsyncMock())
    with TestClient(app) as client:
        alice = _headers(client, "alice")
        assert client.get("/api/openai-agents/status", headers={"test-actor": "bob", "X-Expected-User-Id": "alice"}).status_code == 409
        for changes in ({"test-actor": "bob"}, {"test-org": "other"}, {"X-Expected-Agent-Scope": "forged"}):
            headers = {**alice, **changes, "Idempotency-Key": "receipt"}
            for path in ("/sessions", "/sessions/local", "/sessions/local/artifacts/file/content"):
                assert client.get(f"/api/openai-agents{path}", headers=headers).status_code == 409
            for path in ("/sessions", "/sessions/local/messages", "/sessions/local/cancel", "/sessions/local/browser-approval"):
                result = client.post(f"/api/openai-agents{path}", headers=headers, json={"input": "Task"})
                assert result.status_code == 409
    for method in ("list_sessions", "snapshot", "create", "message", "cancel", "artifact", "_storage"):
        getattr(service, method).assert_not_awaited()
