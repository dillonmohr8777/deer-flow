"""Tests for the M4 entitlement gate on delegated (non-HTTP-decorated) run
launches (review finding f59, high, on PR #66).

Scheduled-task triggers, cron ticks, and MCP task-notification runs all reach
``start_run`` through ``app.gateway.services._start_delegated_run`` rather
than a FastAPI route, so a ``@require_entitlement`` decorator on
``create_run``/``stream_run``/etc. never runs for them. Covers both halves of
the fix:

1. ``_require_delegated_run_entitlement`` -- the one place all three
   delegated-launch paths funnel through.
2. The scheduled-task HTTP routes (create/update/resume/trigger) additionally
   carry ``@require_entitlement("runs.create")`` so an HTTP caller gets an
   immediate 403 instead of a wrapped internal failure.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import scheduled_tasks
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.entitlement_config import EntitlementConfig
from deerflow.config.sandbox_config import SandboxConfig

ORG_A = "org-a"


class _FakeEntitlementRepo:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    async def list_for_org(self, organization_id: str) -> list[dict]:
        return [r for r in self._rows if r["organization_id"] == organization_id]


def _row(organization_id: str, key: str, *, status: str = "active") -> dict:
    return {"organization_id": organization_id, "key": key, "status": status, "limit_value": None}


@pytest.fixture(autouse=True)
def _default_app_config():
    set_app_config(AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")))
    yield
    reset_app_config()


def _enable_entitlements() -> None:
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    config.entitlements = EntitlementConfig(enabled=True, grace_period_seconds=60)
    set_app_config(config)


# ---------------------------------------------------------------------------
# _require_delegated_run_entitlement / _start_delegated_run
# ---------------------------------------------------------------------------


def _delegated_request(*, organization_id: str | None, entitlement_rows: list[dict]) -> SimpleNamespace:
    app = FastAPI()
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    return SimpleNamespace(
        app=app,
        state=SimpleNamespace(
            actor_user_id="owner-1",
            organization_id=organization_id,
            storage_user_id="storage-1",
            organization_role="owner",
        ),
    )


@pytest.mark.asyncio
async def test_delegated_run_denied_with_missing_runs_create_row(monkeypatch):
    _enable_entitlements()
    started = {"called": False}

    async def fake_start_run(*args, **kwargs):
        started["called"] = True
        raise AssertionError("start_run must not be reached")

    monkeypatch.setattr(services, "start_run", fake_start_run)
    request = _delegated_request(organization_id=ORG_A, entitlement_rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await services._start_delegated_run(SimpleNamespace(), "thread-1", request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["key"] == "runs.create"
    assert exc_info.value.detail["reason"] == "no_row"
    assert started["called"] is False


@pytest.mark.asyncio
async def test_delegated_run_denied_with_suspended_row(monkeypatch):
    _enable_entitlements()

    async def fake_start_run(*args, **kwargs):
        raise AssertionError("start_run must not be reached")

    monkeypatch.setattr(services, "start_run", fake_start_run)
    request = _delegated_request(organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create", status="suspended")])

    with pytest.raises(HTTPException) as exc_info:
        await services._start_delegated_run(SimpleNamespace(), "thread-1", request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delegated_run_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    started = {"called": False}

    async def fake_start_run(body, thread_id, request, **kwargs):
        started["called"] = True
        return "fake-record"

    monkeypatch.setattr(services, "start_run", fake_start_run)
    request = _delegated_request(organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")])

    result = await services._start_delegated_run(SimpleNamespace(), "thread-1", request)

    assert result == "fake-record"
    assert started["called"] is True


@pytest.mark.asyncio
async def test_delegated_run_unaffected_when_entitlements_disabled(monkeypatch):
    # No _enable_entitlements() call -- default config (disabled).
    started = {"called": False}

    async def fake_start_run(body, thread_id, request, **kwargs):
        started["called"] = True
        return "fake-record"

    monkeypatch.setattr(services, "start_run", fake_start_run)
    request = _delegated_request(organization_id=ORG_A, entitlement_rows=[])

    result = await services._start_delegated_run(SimpleNamespace(), "thread-1", request)

    assert result == "fake-record"
    assert started["called"] is True


# ---------------------------------------------------------------------------
# HTTP route: POST /api/scheduled-tasks/{task_id}/trigger
# ---------------------------------------------------------------------------


class _StubAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, organization_id: str | None) -> None:
        super().__init__(app)
        self._organization_id = organization_id

    async def dispatch(self, request, call_next):
        from uuid import uuid4

        user = User(email="scheduler-test@example.com", password_hash="x", system_role="user", id=uuid4())
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=[Permissions.THREADS_WRITE, Permissions.RUNS_CREATE], organization_id=self._organization_id)
        return await call_next(request)


class _FakeTaskRepo:
    def __init__(self, task: dict) -> None:
        self._task = task

    async def get(self, task_id: str, *, user_id: str):
        del user_id
        return self._task if task_id == self._task["id"] else None


class _FakeTaskService:
    def __init__(self) -> None:
        self.dispatched = False

    async def dispatch_task(self, task, *, now, trigger):
        del task, now, trigger
        self.dispatched = True
        return {"outcome": "launched"}


def _make_trigger_app(monkeypatch, *, organization_id: str | None, entitlement_rows: list[dict], task_repo: _FakeTaskRepo, service: _FakeTaskService) -> TestClient:
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _request: task_repo)
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_service", lambda _request: service)
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1")))

    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id)
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(scheduled_tasks.router)
    return TestClient(app, raise_server_exceptions=False)


def test_trigger_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    task = {"id": "task-1", "user_id": "user-1"}
    service = _FakeTaskService()
    client = _make_trigger_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[], task_repo=_FakeTaskRepo(task), service=service)

    resp = client.post("/api/scheduled-tasks/task-1/trigger")

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
    assert service.dispatched is False


def test_trigger_route_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    task = {"id": "task-1", "user_id": "user-1"}
    service = _FakeTaskService()
    client = _make_trigger_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[_row(ORG_A, "runs.create")], task_repo=_FakeTaskRepo(task), service=service)

    resp = client.post("/api/scheduled-tasks/task-1/trigger")

    assert resp.status_code == 200, resp.text
    assert service.dispatched is True


def test_trigger_route_unaffected_when_entitlements_disabled(monkeypatch):
    task = {"id": "task-1", "user_id": "user-1"}
    service = _FakeTaskService()
    client = _make_trigger_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[], task_repo=_FakeTaskRepo(task), service=service)

    resp = client.post("/api/scheduled-tasks/task-1/trigger")

    assert resp.status_code == 200, resp.text
    assert service.dispatched is True


# ---------------------------------------------------------------------------
# HTTP routes: create / update / resume (review test gap f82 -- only trigger
# was covered, so removing @require_entitlement from any of these three
# left every test green)
# ---------------------------------------------------------------------------


def _make_gated_app(monkeypatch, *, organization_id: str | None, entitlement_rows: list[dict]) -> TestClient:
    """A bare app for denied-case tests: the entitlement check 403s before
    the handler ever touches get_config/get_scheduled_task_repo/thread_store,
    so none of those need to be wired for this case."""
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1")))
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=organization_id)
    app.state.entitlement_repo = _FakeEntitlementRepo(entitlement_rows)
    app.include_router(scheduled_tasks.router)
    return TestClient(app, raise_server_exceptions=False)


def test_create_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_gated_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])

    resp = client.post(
        "/api/scheduled-tasks",
        json={"title": "T", "prompt": "P", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "UTC"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"


def test_create_route_allowed_with_active_row(monkeypatch):
    _enable_entitlements()
    task_repo = _FakeTaskRepo({"id": "task-1", "user_id": "user-1"})
    task_repo.create = AsyncMock(return_value={"id": "task-1"})
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _request: task_repo)
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1")))
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, organization_id=ORG_A)
    app.state.entitlement_repo = _FakeEntitlementRepo([_row(ORG_A, "runs.create")])
    app.state.thread_store = MagicMock()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/scheduled-tasks",
        json={"title": "T", "prompt": "P", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "UTC"},
    )

    assert resp.status_code == 200, resp.text
    assert task_repo.create.await_count == 1


def test_update_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_gated_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])

    resp = client.patch("/api/scheduled-tasks/task-1", json={})

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"


def test_resume_route_is_gated_when_denied(monkeypatch):
    _enable_entitlements()
    client = _make_gated_app(monkeypatch, organization_id=ORG_A, entitlement_rows=[])

    resp = client.post("/api/scheduled-tasks/task-1/resume")

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "entitlement_exceeded"
