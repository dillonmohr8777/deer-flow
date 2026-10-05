"""Workflow HTTP boundaries with real session middleware and workspace membership."""

import asyncio
import functools
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workflow_native_runtime import SyntheticAdapter, drain, runtime

from app.gateway import authz, paid_run_entitlement
from app.gateway.auth.config import AuthConfig
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers.thread_runs import router as native_runs_router
from app.gateway.routers.threads import router as native_threads_router
from app.gateway.routers.workflows import router
from app.gateway.workflow_authority import workflow_actor_authorized
from app.gateway.workflow_service import WorkflowService
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.persistence.base import Base
from deerflow.persistence.models import RunChangeClockRow, RunEventRow, RunRow, ThreadMetaRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.workflows.catalog import get_workflow

pytestmark = pytest.mark.asyncio
ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"


def session_headers(actor="alice", organization="org-a"):
    return {"Cookie": f"access_token={actor}; deerflow_workspace={organization}; csrf_token=synthetic-csrf", "X-CSRF-Token": "synthetic-csrf"}


def payload():
    definition = get_workflow("personal-research-note")
    return {"workflow_id": definition.id, "inputs": definition.example_inputs, "framework": "langgraph"}


async def test_supervisor_http_admission_is_immutable_and_uses_existing_native_budget(api):
    headers = await scope_headers(api)
    created = await api.client.post("/api/workflows/runs", headers=headers, json={**payload(), "supervisor": True})
    assert created.status_code == 200 and created.json()["supervisor"] is True
    await drain(api.service)
    detail = (await api.client.get(f"/api/workflows/runs/{created.json()['id']}", headers=headers)).json()
    assert detail["accepted"] is True and detail["usage"]["model_calls"] == 4
    assert [call["role"] for call in api.adapter.calls][:2] == ["planner", "plan_reviewer"]
    assert any(step["name"] == "review_plan" for step in detail["steps"])
    replay = await api.client.post("/api/workflows/runs", headers=headers, json={**payload(), "supervisor": True})
    assert replay.status_code == 200 and replay.json()["id"] == created.json()["id"]
    changed = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    assert changed.status_code == 409
    assert len(api.adapter.calls) == 4


async def test_supervisor_mode_rejects_coerced_values_before_admission(api):
    headers = await scope_headers(api)
    for invalid in ("false", 1, None):
        response = await api.client.post("/api/workflows/runs", headers=headers, json={**payload(), "supervisor": invalid})
        assert response.status_code == 422
    assert not api.adapter.calls


async def scope_headers(value, actor="alice", organization="org-a"):
    headers = session_headers(actor, organization)
    state = await value.client.get("/api/workflows/status", headers={**headers, "X-Expected-User-Id": value.users[actor].id})
    assert state.status_code == 200
    assert state.headers["cache-control"] == "private, no-store"
    return {**headers, "X-Expected-Workflow-Scope": state.json()["owner_scope"], "Idempotency-Key": "synthetic-http-task"}


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def api(tmp_path, monkeypatch, request):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    users = {"alice": SimpleNamespace(id=ALICE, system_role="admin"), "bob": SimpleNamespace(id=BOB, system_role="admin")}
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.sqlite'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda connection: Base.metadata.create_all(
                connection, tables=[OrganizationRow.__table__, OrganizationMemberRow.__table__, UserRow.__table__, ProjectRow.__table__, ThreadMetaRow.__table__, RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__]
            )
        )
    async with factory() as session:
        session.add_all([OrganizationRow(id=organization, slug=organization, name="Synthetic shared workspace", status="active", storage_user_id="shared-storage") for organization in ("org-a", "org-b")])
        session.add_all([OrganizationMemberRow(organization_id=organization, user_id=user.id, role="owner", status="active") for organization in ("org-a", "org-b") for user in users.values()])
        session.add_all([UserRow(id=user.id, email=f"{name}@synthetic.example", system_role="admin") for name, user in users.items()])
        await session.commit()

    async def credential(request):
        user = users.get(request.cookies.get("access_token"))
        if user is None:
            raise HTTPException(401, "Synthetic invalid session")
        return user

    async def get_user(actor):
        return next((user for user in users.values() if user.id == actor), None)

    async def pat(_app, _authorization):
        return users["alice"], frozenset(("runs:read", "runs:create", "runs:cancel")), "org-a"

    policy = AuthorizationConfig(
        enabled=True,
        provider=AuthorizationProviderConfig(
            use="deerflow.authz.rbac:RbacAuthorizationProvider",
            config={"roles": {"admin": {"routes": {"allow": ["threads:read", "runs:read", "runs:create", "runs:cancel"]}}, "user": {"routes": {"allow": ["runs:read"]}}, "creator": {"routes": {"allow": ["runs:create"]}}}},
        ),
    )
    monkeypatch.setattr(authz, "_get_route_authorization_config", lambda: policy)
    monkeypatch.setattr(authz, "_route_provider_cache", {})
    monkeypatch.setattr(authz, "_route_provider_config_id", None)
    monkeypatch.setattr(authz, "_route_provider_config_sig", None)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", credential)
    monkeypatch.setattr("app.gateway.auth.pat.authenticate_pat", pat)
    monkeypatch.setattr("app.gateway.csrf_middleware.get_auth_config", lambda: AuthConfig(jwt_secret="synthetic-test-signing-value"))
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.gateway.workflow_authority.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.gateway.workflow_authority.get_local_provider", lambda: SimpleNamespace(get_user=get_user))
    store, events, manager, threads = runtime()
    if request.param == "sqlite":
        store, events, threads = RunRepository(factory), DbRunEventStore(factory), ThreadMetaRepository(factory)
        manager = RunManager(store=store, event_store=events)
    adapter = SyntheticAdapter()
    service = WorkflowService(tmp_path / "workflow.sqlite", checkpointer=InMemorySaver(), adapter=adapter, run_manager=manager, thread_store=threads, event_store=events, authority=workflow_actor_authorized)
    app = FastAPI()
    app.state.workflow_service = service
    app.state.thread_store = threads
    app.state.run_manager = manager
    app.state.run_event_store = events
    app.state.checkpointer = service.checkpointer
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(router)
    app.include_router(native_runs_router)
    app.include_router(native_threads_router)
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
            yield SimpleNamespace(app=app, service=service, adapter=adapter, client=client, users=users, factory=factory, store=store, manager=manager)
    finally:
        await service.aclose()
        await engine.dispose()


async def test_session_creation_real_graph_readback_and_private_artifact(api):
    headers = await scope_headers(api)
    catalog = await api.client.get("/api/workflows/catalog", headers=headers)
    assert catalog.status_code == 200 and catalog.json()["total"] == 120
    assert catalog.headers["cache-control"] == "private, no-store"
    created = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    assert created.status_code == 200
    assert created.headers["cache-control"] == "private, no-store"
    await drain(api.service)
    item = await api.client.get(f"/api/workflows/runs/{created.json()['id']}", headers=headers)
    assert item.json()["status"] == "completed" and item.json()["accepted"] is True
    assert item.headers["cache-control"] == "private, no-store"
    listed = await api.client.get("/api/workflows/runs", headers=headers)
    assert listed.status_code == 200 and listed.headers["cache-control"] == "private, no-store"
    assert len(api.adapter.calls) == 3
    artifact = await api.client.get(f"/api/workflows/runs/{created.json()['id']}/artifact", headers=headers)
    assert artifact.status_code == 200 and artifact.json()["accepted"] is True
    assert artifact.headers["cache-control"] == "private, no-store"
    assert artifact.headers["x-content-type-options"] == "nosniff"
    assert artifact.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize(("actor", "organization"), [("alice", "org-a"), ("bob", "org-a"), ("alice", "org-b"), ("bob", "org-b")])
async def test_private_workflow_native_journal_is_invisible_to_ordinary_shared_routes(api, actor, organization):
    headers = await scope_headers(api)
    created = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    await drain(api.service)
    detail = (await api.client.get(f"/api/workflows/runs/{created.json()['id']}", headers=headers)).json()
    ordinary = session_headers(actor, organization)
    thread = f"/api/threads/{detail['thread_id']}"
    run = f"{thread}/runs/{detail['native_run_id']}"
    for path in (thread, f"{thread}/state", f"{thread}/messages", f"{thread}/runs", run, f"{run}/messages", f"{run}/events"):
        assert (await api.client.get(path, headers=ordinary)).status_code == 404
    assert (await api.client.post(f"{thread}/history", headers=ordinary, json={})).status_code == 404
    search = await api.client.post("/api/threads/search", headers=ordinary, json={})
    assert search.status_code == 200 and search.json() == []
    artifact = await api.client.get(f"/api/workflows/runs/{detail['id']}/artifact", headers=headers)
    assert artifact.status_code == 200 and artifact.json()["accepted"] is True
    assert len(api.adapter.calls) == 3


@pytest.mark.parametrize("actor", ["alice", "bob"])
async def test_ordinary_cancel_cannot_abort_private_workflow_but_owner_workflow_cancel_can(api, monkeypatch, actor):
    arrived, release = asyncio.Event(), asyncio.Event()
    original = api.service._event

    async def before_model(data, name, status, **details):
        await original(data, name, status, **details)
        if name == "plan" and status == "running":
            arrived.set()
            await release.wait()

    monkeypatch.setattr(api.service, "_event", before_model)
    owner = await scope_headers(api)
    created = await api.client.post("/api/workflows/runs", headers=owner, json=payload())
    await asyncio.wait_for(arrived.wait(), 5)
    detail = (await api.client.get(f"/api/workflows/runs/{created.json()['id']}", headers=owner)).json()
    path = f"/api/threads/{detail['thread_id']}/runs/{detail['native_run_id']}/cancel"
    denied = await api.client.post(path, headers=session_headers(actor))
    assert denied.status_code == 404
    assert (await api.client.get(f"/api/workflows/runs/{detail['id']}", headers=owner)).json()["status"] == "running"
    cancelled = await api.client.post(f"/api/workflows/runs/{detail['id']}/cancel", headers=owner)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    await drain(api.service)
    assert not api.adapter.calls


@pytest.mark.parametrize(("actor", "organization"), [("bob", "org-a"), ("alice", "org-b")])
async def test_account_or_workspace_switch_cannot_read_cancel_resume_or_download_prior_job(api, actor, organization):
    original = await scope_headers(api)
    created = await api.client.post("/api/workflows/runs", headers=original, json=payload())
    await drain(api.service)
    run_id = created.json()["id"]
    stale = {**original, **session_headers(actor, organization)}
    for path in ("/catalog", "/runs", f"/runs/{run_id}", f"/runs/{run_id}/artifact"):
        assert (await api.client.get(f"/api/workflows{path}", headers=stale)).status_code == 409
    for path in (f"/runs/{run_id}/cancel", f"/runs/{run_id}/resume", "/runs"):
        assert (await api.client.post(f"/api/workflows{path}", headers=stale, json=payload())).status_code == 409
    fresh = await scope_headers(api, actor, organization)
    assert (await api.client.get("/api/workflows/runs", headers=fresh)).json() == {"runs": []}
    for path in (f"/runs/{run_id}", f"/runs/{run_id}/artifact"):
        assert (await api.client.get(f"/api/workflows{path}", headers=fresh)).status_code == 404
    for path in (f"/runs/{run_id}/cancel", f"/runs/{run_id}/resume"):
        assert (await api.client.post(f"/api/workflows{path}", headers=fresh)).status_code == 404
    assert len(api.adapter.calls) == 3


async def test_anonymous_stale_actor_and_nonmember_workspace_fail_before_admission(api):
    assert (await api.client.get("/api/workflows/status")).status_code == 401
    stale = await api.client.get("/api/workflows/status", headers={**session_headers("bob"), "X-Expected-User-Id": ALICE})
    assert stale.status_code == 409
    nonmember = await api.client.get("/api/workflows/status", headers={**session_headers(organization="not-a-member"), "X-Expected-User-Id": ALICE})
    assert nonmember.status_code == 403
    assert not api.adapter.calls


async def test_real_route_permissions_deny_read_create_cancel_and_resume(api):
    headers = await scope_headers(api)
    api.users["alice"].system_role = "user"
    for path in ("/runs", "/runs/unknown/cancel", "/runs/unknown/resume"):
        assert (await api.client.post(f"/api/workflows{path}", headers=headers, json=payload())).status_code == 403
    api.users["alice"].system_role = "creator"
    for path in ("/status", "/catalog", "/runs", "/runs/unknown", "/runs/unknown/artifact"):
        assert (await api.client.get(f"/api/workflows{path}", headers={**headers, "X-Expected-User-Id": ALICE})).status_code == 403
    assert not api.adapter.calls


async def test_csrf_missing_or_wrong_token_blocks_paid_admission(api):
    headers = await scope_headers(api)
    for token in (None, "forged"):
        request_headers = {key: value for key, value in headers.items() if key != "X-CSRF-Token"}
        if token:
            request_headers["X-CSRF-Token"] = token
        assert (await api.client.post("/api/workflows/runs", headers=request_headers, json=payload())).status_code == 403
    assert not api.adapter.calls
    assert await api.service.list_runs(headers["X-Expected-Workflow-Scope"]) == []


async def test_invalid_payload_and_extra_runtime_controls_never_admit(api):
    headers = await scope_headers(api)
    missing_key = {key: value for key, value in headers.items() if key != "Idempotency-Key"}
    assert (await api.client.post("/api/workflows/runs", headers=missing_key, json=payload())).status_code == 422
    for field in ("model", "tools", "owner", "max_output_tokens", "storage_user", "worker_id"):
        assert (await api.client.post("/api/workflows/runs", headers=headers, json={**payload(), field: "forged"})).status_code == 422
    for invalid in (
        {**payload(), "framework": "unbounded"},
        {**payload(), "workflow_id": "../arbitrary"},
        {**payload(), "workflow_id": "unknown"},
        {**payload(), "inputs": {}},
        {**payload(), "inputs": {**payload()["inputs"], "unexpected": "forged"}},
    ):
        assert (await api.client.post("/api/workflows/runs", headers=headers, json=invalid)).status_code == 422
    assert not api.adapter.calls
    assert await api.service.list_runs(headers["X-Expected-Workflow-Scope"]) == []


async def test_idempotent_http_creation_reuses_result_and_changed_inputs_conflict(api):
    headers = await scope_headers(api)
    first = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    await drain(api.service)
    replay = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    changed = payload()
    changed["inputs"]["brief"] += " Different requested emphasis."
    assert (await api.client.post("/api/workflows/runs", headers=headers, json=changed)).status_code == 409
    assert len(api.adapter.calls) == 3


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/status"), ("GET", "/catalog"), ("GET", "/runs"), ("POST", "/runs"), ("GET", "/runs/known"), ("GET", "/runs/known/artifact"), ("POST", "/runs/known/cancel"), ("POST", "/runs/known/resume")]
)
async def test_all_scope_pat_remains_default_denied_even_with_session_cookie(api, method, path):
    headers = {**await scope_headers(api), "Authorization": "Bearer synthetic-pat", "X-Expected-User-Id": ALICE}
    result = await api.client.request(method, f"/api/workflows{path}", headers=headers, json=payload() if method == "POST" else None)
    assert result.status_code == 403
    assert result.json()["detail"] == "PAT credentials are not permitted on this route"
    assert not api.adapter.calls


async def test_membership_revocation_before_execution_denies_real_background_authority(api):
    await drain(api.service)
    api.service.limits["max_running"] = 0
    headers = await scope_headers(api)
    admitted = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    await drain(api.service)
    async with api.factory() as session:
        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == ALICE, OrganizationMemberRow.organization_id == "org-a").values(status="inactive"))
        await session.commit()
    api.service.limits["max_running"] = 3
    api.service._wake()
    await drain(api.service)
    result = await api.service.snapshot(headers["X-Expected-Workflow-Scope"], admitted.json()["id"])
    assert result["status"] == "failed" and result["error"] == "owner_authorization_changed"
    assert result["accepted"] is False and result["artifact"] is None
    assert not api.adapter.calls


async def test_role_downgrade_removing_runs_create_before_execution_denies_real_background_authority(api):
    await drain(api.service)
    api.service.limits["max_running"] = 0
    headers = await scope_headers(api)
    admitted = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    await drain(api.service)
    api.users["alice"].system_role = "user"
    api.service.limits["max_running"] = 3
    api.service._wake()
    await drain(api.service)
    result = await api.service.snapshot(headers["X-Expected-Workflow-Scope"], admitted.json()["id"])
    assert result["status"] == "failed" and result["error"] == "owner_authorization_changed"
    assert result["accepted"] is False and result["artifact"] is None
    assert not api.adapter.calls


async def test_storage_user_mismatch_before_execution_denies_real_background_authority(api):
    await drain(api.service)
    api.service.limits["max_running"] = 0
    headers = await scope_headers(api)
    admitted = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    await drain(api.service)
    async with api.factory() as session:
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == "org-a").values(storage_user_id="rotated-storage"))
        await session.commit()
    api.service.limits["max_running"] = 3
    api.service._wake()
    await drain(api.service)
    result = await api.service.snapshot(headers["X-Expected-Workflow-Scope"], admitted.json()["id"])
    assert result["status"] == "failed" and result["error"] == "owner_authorization_changed"
    assert result["accepted"] is False and result["artifact"] is None
    assert not api.adapter.calls


@pytest.mark.parametrize("reason", ["missing", "suspended"])
@pytest.mark.parametrize("path", ["/runs", "/runs/unknown/resume"])
async def test_modern_paid_entitlement_bridge_denies_before_real_service_admission(api, monkeypatch, reason, path):
    calls = []

    def require_entitlement(key):
        assert key == "runs.create"

        def decorate(function):
            @functools.wraps(function)
            async def gate(*args, **kwargs):
                auth = kwargs["request"].state.auth
                calls.append((auth.actor_user_id, auth.organization_id))
                raise HTTPException(403, {"error": "entitlement_exceeded", "reason": reason})

            return gate

        return decorate

    monkeypatch.setattr(authz, "require_entitlement", require_entitlement, raising=False)
    source = Path(__file__).parents[1] / "app/gateway/routers/workflows.py"
    name = "synthetic_workflow_entitlement_router"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    # A fresh decorator chain reflects a modern integration lane without
    # replacing the collected production router or its real service.
    api.app.router.routes.clear()
    api.app.include_router(module.router)
    headers = await scope_headers(api)
    api.users["alice"].system_role = "user"
    assert (await api.client.post(f"/api/workflows{path}", headers=headers, json=payload())).status_code == 403
    assert calls == []
    api.users["alice"].system_role = "admin"
    denied = await api.client.post(f"/api/workflows{path}", headers=headers, json=payload())
    assert denied.status_code == 403 and denied.json()["detail"]["reason"] == reason
    assert calls == [(ALICE, "org-a")]
    assert not api.adapter.calls
    assert await api.service.list_runs(headers["X-Expected-Workflow-Scope"]) == []


async def test_absent_disabled_service_exposes_catalog_without_admitting_work(api):
    headers = await scope_headers(api)
    await api.service.aclose()
    del api.app.state.workflow_service
    state = await api.client.get("/api/workflows/status", headers={**headers, "X-Expected-User-Id": ALICE})
    assert state.status_code == 503 and state.json()["detail"] == "not_enabled"
    catalog = await api.client.get("/api/workflows/catalog", headers=headers)
    assert catalog.status_code == 200 and catalog.json()["total"] == 120
    admitted = await api.client.post("/api/workflows/runs", headers=headers, json=payload())
    assert admitted.status_code == 503 and admitted.json()["detail"] == "not_enabled"
    assert not api.adapter.calls


async def test_old_base_entitlement_absence_keeps_scope_and_permission_guards(api, monkeypatch):
    monkeypatch.delattr(authz, "require_entitlement", raising=False)
    monkeypatch.setattr(paid_run_entitlement.importlib.util, "find_spec", lambda name: None)
    headers = await scope_headers(api)
    assert (await api.client.post("/api/workflows/runs", headers={**headers, "X-Expected-Workflow-Scope": "stale"}, json=payload())).status_code == 409
    api.users["alice"].system_role = "user"
    assert (await api.client.post("/api/workflows/runs", headers=headers, json=payload())).status_code == 403
    assert not api.adapter.calls
