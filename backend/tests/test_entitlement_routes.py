"""HTTP-level tests for the M4 entitlement gate wired onto real routes (task e6).

Covers design §6's acceptance bar: allowed / denied / missing entitlement on
three paid mutations -- ``runs.create`` (``POST .../runs``), ``runs.cancel``
(``POST .../runs/{run_id}/cancel``), and the ``projects.max`` limit key
(``POST /api/projects``) -- plus the snapshot endpoint returning the same
values the route-level evaluator used.

Entitlements default to disabled (``EntitlementConfig().enabled is False``),
so every other test in the suite that hits these routes is unaffected;
these tests explicitly flip it on via ``set_app_config``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import console, projects, runs, thread_runs
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.entitlement_config import EntitlementConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime import DisconnectMode, RunManager, RunRecord, RunStatus

ORG_A = "org-a"
THREAD_ID = "thread-1"


class _FakeEntitlementRepo:
    """In-memory stand-in for EntitlementRepository -- the evaluator itself
    is exercised against the real repository in test_entitlement_evaluator.py.
    """

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    async def list_for_org(self, organization_id: str) -> list[dict]:
        return [r for r in self._rows if r["organization_id"] == organization_id]


def _row(organization_id: str, key: str, *, status: str = "active", limit_value: int | None = None) -> dict:
    return {"organization_id": organization_id, "key": key, "status": status, "limit_value": limit_value}


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamps an AuthContext with a controllable organization_id."""

    def __init__(self, app, *, organization_id: str | None, permissions: list[str]) -> None:
        super().__init__(app)
        self._organization_id = organization_id
        self._permissions = permissions

    async def dispatch(self, request, call_next):
        user = User(email="router-test@example.com", password_hash="x", system_role="user", id=uuid4())
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=list(self._permissions), organization_id=self._organization_id)
        return await call_next(request)


@pytest.fixture(autouse=True)
def _default_app_config():
    # Every test in this file needs a loaded AppConfig (no config.yaml is
    # guaranteed to exist in the test sandbox), with entitlements off unless
    # a test opts in via _enable_entitlements().
    set_app_config(AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")))
    yield
    reset_app_config()


def _enable_entitlements() -> None:
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    config.entitlements = EntitlementConfig(enabled=True, grace_period_seconds=60)
    set_app_config(config)


# ---------------------------------------------------------------------------
# runs.create — POST /api/threads/{thread_id}/runs
# ---------------------------------------------------------------------------


def _run_record(run_id: str) -> RunRecord:
    return RunRecord(run_id=run_id, thread_id=THREAD_ID, assistant_id=None, status=RunStatus.pending, on_disconnect=DisconnectMode.continue_)


async def _fake_sse_consumer(bridge, record, request, run_mgr, **kwargs):
    del bridge, record, request, run_mgr, kwargs
    yield "data: {}\n\n"


def _make_create_run_app(monkeypatch, *, organization_id: str | None, entitlement_rows: list[dict], module=thread_runs, router=None) -> TestClient:
    """Builds an app around a run-creation router (thread_runs.router or the
    stateless runs.router), with start_run/sse_consumer faked so the same
    helper covers create_run, stream_run, wait_run and their stateless
    counterparts without needing a real agent/bridge/checkpointer."""
    started = {"called": False}

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, request, require_existing_thread, idempotency_key
        started["called"] = True
        return _run_record("run-1")

    monkeypatch.setattr(module, "start_run", fake_start_run)
    if hasattr(module, "sse_consumer"):
        monkeypatch.setattr(module, "sse_consumer", _fake_sse_consumer)

    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id, permissions=[Permissions.RUNS_CREATE, Permissions.RUNS_CANCEL, Permissions.THREADS_READ, Permissions.THREADS_WRITE])
    thread_store = MagicMock()
    thread_store.check_access = AsyncMock(return_value=True)
    app.state.thread_store = thread_store
    app.state.stream_bridge = MagicMock(stream_exists=AsyncMock(return_value=False))
    app.state.run_manager = MagicMock()
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(router or module.router)
    client = TestClient(app, raise_server_exceptions=False)
    client._started = started  # type: ignore[attr-defined]
    return client


def test_runs_create_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs", json={})
    assert resp.status_code == 200, resp.text
    assert client._started["called"] is True


def test_runs_create_denied_with_suspended_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create", status="suspended")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert client._started["called"] is False


def test_runs_create_denied_with_missing_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["reason"] == "no_row"
    assert client._started["called"] is False


def test_runs_create_denied_with_unresolved_organization(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=None, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["reason"] == "no_organization"
    assert client._started["called"] is False


def test_runs_create_unaffected_when_entitlements_disabled(monkeypatch):
    # No _enable_entitlements() call -- default config (disabled).
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs", json={})
    assert resp.status_code == 200, resp.text
    assert client._started["called"] is True


# ---------------------------------------------------------------------------
# runs.create bypass routes (review finding, high): every route that calls
# start_run() must carry the same gate as POST /runs, or entitlements are
# trivially bypassed by hitting /stream or /wait instead.
# ---------------------------------------------------------------------------


def test_runs_stream_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/stream", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert client._started["called"] is False


def test_runs_stream_route_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/stream", json={})
    assert resp.status_code == 200, resp.text
    assert client._started["called"] is True


def test_runs_wait_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/wait", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert client._started["called"] is False


def test_runs_wait_route_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/wait", json={})
    assert resp.status_code == 200, resp.text
    assert client._started["called"] is True


def test_stateless_runs_stream_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[], module=runs, router=runs.router)
    resp = client.post("/api/runs/stream", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert client._started["called"] is False


def test_stateless_runs_stream_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")], module=runs, router=runs.router)
    resp = client.post("/api/runs/stream", json={})
    assert resp.status_code == 200, resp.text
    assert client._started["called"] is True


def test_stateless_runs_wait_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_create_run_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[], module=runs, router=runs.router)
    resp = client.post("/api/runs/wait", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert client._started["called"] is False


# ---------------------------------------------------------------------------
# runs.cancel — POST /api/threads/{thread_id}/runs/{run_id}/cancel
# ---------------------------------------------------------------------------


def _make_cancel_app(mgr: RunManager, *, organization_id: str | None, entitlement_rows: list[dict]) -> TestClient:
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id, permissions=[Permissions.RUNS_CREATE, Permissions.RUNS_CANCEL, Permissions.THREADS_READ, Permissions.THREADS_WRITE])
    thread_store = MagicMock()
    thread_store.check_access = AsyncMock(return_value=True)
    app.state.thread_store = thread_store
    app.state.run_manager = mgr
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(thread_runs.router)
    return TestClient(app, raise_server_exceptions=False)


def _create_running_run(mgr: RunManager) -> str:
    async def _setup():
        record = await mgr.create(THREAD_ID)
        await mgr.set_status(record.run_id, RunStatus.running)
        return record.run_id

    return asyncio.run(_setup())


def test_runs_cancel_allowed_with_active_row():
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_cancel_app(mgr, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.cancel")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 202, resp.text


def test_runs_cancel_denied_with_suspended_row():
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_cancel_app(mgr, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.cancel", status="suspended")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"

    # The run must still be running -- the entitlement denial happened
    # before any cancel logic ran.
    async def _status():
        record = await mgr.get(run_id)
        return record.status

    assert asyncio.run(_status()) == RunStatus.running


def test_runs_cancel_denied_with_missing_row():
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_cancel_app(mgr, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["reason"] == "no_row"


# ---------------------------------------------------------------------------
# runs.cancel bypass via POST .../stream?action=interrupt|rollback (review
# finding f65, low): the dedicated /cancel route is gated, but the join-stream
# route's own cancel-then-stream branch was not.
# ---------------------------------------------------------------------------


def _make_stream_cancel_app(monkeypatch, mgr: RunManager, *, organization_id: str | None, entitlement_rows: list[dict]) -> TestClient:
    monkeypatch.setattr(thread_runs, "sse_consumer", _fake_sse_consumer)
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id, permissions=[Permissions.RUNS_CREATE, Permissions.RUNS_CANCEL, Permissions.RUNS_READ, Permissions.THREADS_READ, Permissions.THREADS_WRITE])
    thread_store = MagicMock()
    thread_store.check_access = AsyncMock(return_value=True)
    app.state.thread_store = thread_store
    app.state.run_manager = mgr
    app.state.stream_bridge = MagicMock(stream_exists=AsyncMock(return_value=False), supports_cross_process=False)
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(thread_runs.router)
    return TestClient(app, raise_server_exceptions=False)


def test_stream_route_cancel_action_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_stream_cancel_app(monkeypatch, mgr, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream", params={"action": "interrupt"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert resp.json()["detail"]["key"] == "runs.cancel"

    async def _status():
        record = await mgr.get(run_id)
        return record.status

    assert asyncio.run(_status()) == RunStatus.running  # denial happened before any cancel logic ran


def test_stream_route_cancel_action_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_stream_cancel_app(monkeypatch, mgr, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.cancel")])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream", params={"action": "interrupt"})
    assert resp.status_code == 200, resp.text

    async def _status():
        record = await mgr.get(run_id)
        return record.status

    assert asyncio.run(_status()) != RunStatus.running  # the cancel actually ran


def test_stream_route_plain_join_is_unaffected_by_runs_cancel_entitlement(monkeypatch):
    """An action-less join is read-only observation, never a cancel -- it
    must not require the runs.cancel entitlement at all."""
    _enable_entitlements()
    mgr = RunManager()
    run_id = _create_running_run(mgr)
    client = _make_stream_cancel_app(monkeypatch, mgr, organization_id=ORG_A, entitlement_rows=[])
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# projects.max — POST /api/projects (limit key, inline check)
# ---------------------------------------------------------------------------


def _make_projects_app(*, organization_id: str | None, entitlement_rows: list[dict], existing_project_count: int = 0) -> TestClient:
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id, permissions=[Permissions.PROJECTS_READ, Permissions.PROJECTS_WRITE])

    project_repo = MagicMock()
    project_repo.list = AsyncMock(return_value=[{"id": f"p{i}"} for i in range(existing_project_count)])
    created = {"id": "new-project", "name": "x", "instructions": "", "presentation": {}, "status": "active", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
    project_repo.create = AsyncMock(return_value=created)
    app.state.project_repo = project_repo
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(projects.router)
    return TestClient(app, raise_server_exceptions=False)


def test_projects_max_allowed_under_limit():
    _enable_entitlements()
    client = _make_projects_app(organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "projects.max", limit_value=25)], existing_project_count=4)
    resp = client.post("/api/projects", json={"name": "New project"})
    assert resp.status_code == 201, resp.text


def test_projects_max_denied_at_limit():
    _enable_entitlements()
    client = _make_projects_app(organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "projects.max", limit_value=5)], existing_project_count=5)
    resp = client.post("/api/projects", json={"name": "New project"})
    assert resp.status_code == 403, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "entitlement_exceeded"
    assert body["key"] == "projects.max"
    assert body["limit"] == 5
    assert body["used"] == 5


def test_projects_max_denied_with_missing_limit_row():
    _enable_entitlements()
    client = _make_projects_app(organization_id=ORG_A, entitlement_rows=[], existing_project_count=0)
    resp = client.post("/api/projects", json={"name": "New project"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["limit"] == 0


def test_projects_max_unaffected_when_entitlements_disabled():
    client = _make_projects_app(organization_id=ORG_A, entitlement_rows=[], existing_project_count=999)
    resp = client.post("/api/projects", json={"name": "New project"})
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Snapshot endpoint — GET /api/console/entitlements matches the evaluator
# ---------------------------------------------------------------------------


def _make_console_app(*, organization_id: str | None, entitlement_rows: list[dict], project_count: int = 0) -> TestClient:
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id, permissions=[Permissions.RUNS_READ])
    project_repo = MagicMock()
    project_repo.list = AsyncMock(return_value=[{"id": f"p{i}"} for i in range(project_count)])
    app.state.project_repo = project_repo
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(console.router)
    return TestClient(app, raise_server_exceptions=False)


def test_snapshot_matches_the_route_level_evaluator(monkeypatch):
    """Same values the create_run/cancel_run/create_project checks would see."""
    _enable_entitlements()
    rows = [
        _row(ORG_A, "console.read"),
        _row(ORG_A, "runs.create"),
        _row(ORG_A, "runs.cancel", status="suspended"),
        _row(ORG_A, "projects.max", limit_value=10),
    ]
    client = _make_console_app(organization_id=ORG_A, entitlement_rows=rows, project_count=3)
    resp = client.get("/api/console/entitlements")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["organization_id"] == ORG_A
    assert body["degraded"] is False
    assert body["entitlements"]["console.read"]["allowed"] is True
    assert body["entitlements"]["runs.create"]["allowed"] is True
    assert body["entitlements"]["runs.cancel"]["allowed"] is False
    assert body["entitlements"]["agents.manage"]["allowed"] is False  # no row -- missing entitlement
    assert body["entitlements"]["projects.max"] == {"limit": 10, "used": 3}


def test_snapshot_requires_console_read_entitlement():
    _enable_entitlements()
    client = _make_console_app(organization_id=ORG_A, entitlement_rows=[], project_count=0)
    resp = client.get("/api/console/entitlements")
    assert resp.status_code == 403, resp.text


def test_snapshot_limit_is_null_when_entitlements_disabled_not_zero():
    """Review finding: a disabled gate must not read the same as an enabled,
    exhausted one. POST /api/projects still succeeds while disabled (see
    test_projects_max_unaffected_when_entitlements_disabled), so the
    snapshot's `limit: 0` for the same state was actively misleading."""
    # No _enable_entitlements() call -- default config (disabled).
    client = _make_console_app(organization_id=ORG_A, entitlement_rows=[], project_count=7)
    resp = client.get("/api/console/entitlements")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entitlements"]["projects.max"]["limit"] is None
    assert body["entitlements"]["projects.max"]["used"] == 7  # live count is still real
