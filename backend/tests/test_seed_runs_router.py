"""Replay-only seeded history must satisfy the real ownership gate, without a checkpoint."""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from seed_runs_router import router

from app.gateway.app import create_app
from app.gateway.auth.config import AuthConfig, set_auth_config
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.feedback import FeedbackRepository
from deerflow.persistence.run import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager


def _body(thread_id="replay-history"):
    return {
        "thread_id": thread_id,
        "runs": [
            {"run_id": "run-older", "created_at": "2026-01-01T00:00:00+00:00", "messages": [{"role": "human", "content": "ALPHA", "id": "alpha"}]},
            {"run_id": "run-newer", "created_at": "2026-01-01T00:01:00+00:00", "messages": [{"role": "human", "content": "OMEGA", "id": "omega"}]},
        ],
    }


@pytest_asyncio.fixture
async def replay_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    set_auth_config(AuthConfig(jwt_secret="local-test-seed-secret-never-a-credential"))
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db")))
    sf = get_session_factory()
    assert sf is not None
    app = create_app()
    assert all(getattr(route, "path", None) != "/api/test-only/seed-runs" for route in app.routes)
    app.include_router(router)
    app.state.thread_store = ThreadMetaRepository(sf)
    app.state.run_store = RunRepository(sf)
    app.state.run_event_store = MemoryRunEventStore()
    app.state.run_manager = RunManager(store=app.state.run_store)
    app.state.feedback_repo = FeedbackRepository(sf)
    app.state.checkpointer = InMemorySaver()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield SimpleNamespace(app=app, client=client)
        finally:
            await close_engine()


@pytest.mark.asyncio
async def test_seed_registers_owned_thread_and_ordered_history_without_checkpoint(replay_app):
    response = await replay_app.client.post("/api/test-only/seed-runs", json=_body())
    assert response.status_code == 200, response.text
    record = await replay_app.app.state.thread_store.get("replay-history", user_id="default")
    assert record is not None
    assert record["user_id"] == "default"
    assert await replay_app.app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "replay-history", "checkpoint_ns": ""}}) is None

    history = await replay_app.client.get("/api/threads/replay-history/messages/page")
    assert history.status_code == 200, history.text
    assert [row["content"]["content"] for row in history.json()["data"]] == ["ALPHA", "OMEGA"]
    assert [row["seq"] for row in history.json()["data"]] == [1, 2]
    assert history.json()["has_more"] is False
    runs = await replay_app.app.state.run_store.list_by_thread("replay-history", user_id="default")
    assert [run["run_id"] for run in runs] == ["run-newer", "run-older"]


@pytest.mark.asyncio
async def test_seed_cannot_claim_another_owners_thread(replay_app):
    await replay_app.app.state.thread_store.create("foreign-thread", user_id="other-owner", metadata={"original": True})
    response = await replay_app.client.post("/api/test-only/seed-runs", json=_body("foreign-thread"))
    assert response.status_code == 404, response.text
    record = await replay_app.app.state.thread_store.get("foreign-thread", user_id="other-owner")
    assert record["metadata"] == {"original": True}
    assert await replay_app.app.state.run_store.list_by_thread("foreign-thread", user_id=None) == []
    assert (await replay_app.client.get("/api/threads/foreign-thread/messages/page")).status_code == 404


@pytest.mark.asyncio
async def test_seed_rejects_unsafe_thread_identity_before_writes(replay_app):
    response = await replay_app.client.post("/api/test-only/seed-runs", json=_body("bad.thread.id"))
    assert response.status_code == 422, response.text
    assert await replay_app.app.state.run_store.list_by_thread("bad.thread.id", user_id=None) == []
