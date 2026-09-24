"""HTTP-layer tests for POST/GET /api/clients/{client_id}/agents (fleet stamping).

Referenced by test_fleet_binding_repo.py's docstring as the home for
HTTP-layer stamping behavior: idempotent return, authorization (organization
admin / assigned member / neither), and scheduled task creation (paused,
non-interactive). The repository-level idempotency/organization-scoping
guarantee itself is covered by test_fleet_binding_repo.py; this file drives
the real router, real AuthMiddleware, and a real SQL agent store so the two
persistence layers (the personal ``agents`` table and the organization-scoped
``fleet_agent_bindings`` index) are proven to agree end to end.

Unlike ``org_isolation_fixtures.org_world`` (an in-memory async-only engine),
fleet stamping also needs the *synchronous* SQL agent store
(``deerflow.persistence.agents.sql.SqlAgentStore``), which opens its own
engine from ``DatabaseConfig.app_sync_sqlalchemy_url``. This module builds its
own on-disk SQLite world via the real ``init_engine_from_config`` bootstrap so
both engines point at the same file, the same way they do in production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from org_isolation_fixtures import USER_A, USER_B, USER_C, auth_headers  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import clients
from deerflow.config.agent_storage_config import AgentStorageConfig
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.persistence.agents import get_agent_store
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.fleet import FleetBindingRepository
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

STORAGE_S = "fleet-storage-s"
ORG_S = private_organization_id(STORAGE_S)


async def _user_from_access_token(request):
    from types import SimpleNamespace

    return SimpleNamespace(id=request.cookies["access_token"], system_role="user", email="fleet-stamping@example.com")


@pytest_asyncio.fixture()
async def fleet_stamping_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    # Real fleet/templates/ shipped in this repo, not a synthetic tmp_path one.
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))

    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    await init_engine_from_config(database)
    session_factory = get_session_factory()
    assert session_factory is not None

    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        for user in (USER_A, USER_B, USER_C, STORAGE_S):
            session.add(UserRow(id=user, email=f"{user}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        for user in (USER_A,):
            session.add(OrganizationRow(id=private_organization_id(user), slug=private_organization_slug(user), name="Private organization", status="active", created_at=now, updated_at=now))
        session.add(OrganizationRow(id=ORG_S, slug=private_organization_slug(STORAGE_S), name="Shared S", status="active", storage_user_id=STORAGE_S, created_at=now, updated_at=now))
        # S: A is owner (org admin path); B is a plain member with no client
        # assignment (must be denied); C is a plain member WITH a client
        # assignment (must be allowed); assignment is granted per-test.
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_A, role="owner", status="active", created_at=now, updated_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_B, role="member", status="active", created_at=now, updated_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_C, role="member", status="active", created_at=now, updated_at=now))

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _user_from_access_token)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())

    set_app_config(
        AppConfig(
            database=database,
            agent_storage=AgentStorageConfig(backend="db"),
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
    )
    try:
        yield session_factory
    finally:
        reset_app_config()
        await close_engine()


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.state.scheduled_task_repo = ScheduledTaskRepository(session_factory)
    app.include_router(clients.router)
    return app


def _http_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_client(client: httpx.AsyncClient, headers: dict[str, str], name: str = "Acme Corp") -> dict:
    response = await client.post("/api/clients", json={"display_name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_stamp_creates_agent_and_paused_task_for_org_admin(fleet_stamping_world) -> None:
    session_factory = fleet_stamping_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a)
        response = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "weekly-client-report"}, headers=headers_a)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["agent_name"] == "acme-corp-weekly-client-report"
    assert body["client_id"] == created["id"]
    assert body["template_id"] == "weekly-client-report"
    assert body["template_version"] == "1"
    assert body["scheduled_task_id"]

    # Explicit user_id=STORAGE_S, no ambient org/storage context needed: both
    # the store and repository scope by the explicit id / resolve_organization_id()
    # (None outside a request, which just skips the extra org filter).
    store = get_agent_store()
    agent_cfg = store.get("acme-corp-weekly-client-report", user_id=STORAGE_S)
    assert agent_cfg.client_id == created["id"]
    assert agent_cfg.template_id == "weekly-client-report"
    assert agent_cfg.template_version == "1"
    assert agent_cfg.model == "openrouter-sonnet-5"
    assert "Acme Corp" in (store.get_soul("acme-corp-weekly-client-report", user_id=STORAGE_S) or "")

    task_repo = ScheduledTaskRepository(session_factory)
    tasks = await task_repo.list_by_user(STORAGE_S)
    assert len(tasks) == 1
    assert tasks[0]["id"] == body["scheduled_task_id"]
    assert tasks[0]["status"] == "paused"
    assert tasks[0]["assistant_id"] == "acme-corp-weekly-client-report"
    assert tasks[0]["schedule_spec"]["cron"] == "0 8 * * 1"


async def test_stamp_is_idempotent(fleet_stamping_world) -> None:
    session_factory = fleet_stamping_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a, "Globex")
        first = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "review-replies"}, headers=headers_a)
        second = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "review-replies"}, headers=headers_a)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["agent_name"] == second.json()["agent_name"]

    binding_repo = FleetBindingRepository(session_factory)
    bindings = await binding_repo.list_by_client(created["id"])
    assert len(bindings) == 1

    task_repo = ScheduledTaskRepository(session_factory)
    assert len(await task_repo.list_by_user(STORAGE_S)) == 1


async def test_stamp_denies_unrelated_member(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_b = auth_headers(USER_B, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a)
        response = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "weekly-client-report"}, headers=headers_b)

    assert response.status_code == 403


async def test_stamp_allows_member_assigned_to_the_client(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a)
        assign = await client.post(f"/api/clients/{created['id']}/assignments", json={"user_id": USER_C, "role": "account_manager"}, headers=headers_a)
        assert assign.status_code == 201, assign.text

        response = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "content-drafts"}, headers=headers_c)

    assert response.status_code == 201, response.text


async def test_stamp_unknown_template_is_404(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a)
        response = await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "does-not-exist"}, headers=headers_a)

    assert response.status_code == 404


async def test_stamp_unknown_client_is_404(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _http_client(app) as client:
        response = await client.post("/api/clients/does-not-exist/agents", json={"template_id": "weekly-client-report"}, headers=headers_a)

    assert response.status_code == 404


async def test_list_client_agents_returns_stamped_agents(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _http_client(app) as client:
        created = await _create_client(client, headers_a)
        await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "weekly-client-report"}, headers=headers_a)
        await client.post(f"/api/clients/{created['id']}/agents", json={"template_id": "ai-search-visibility"}, headers=headers_a)

        listing = await client.get(f"/api/clients/{created['id']}/agents", headers=headers_a)

    assert listing.status_code == 200
    ids = {a["template_id"] for a in listing.json()["agents"]}
    assert ids == {"weekly-client-report", "ai-search-visibility"}


async def test_stamp_requires_auth(fleet_stamping_world) -> None:
    app = _build_app(fleet_stamping_world)
    async with _http_client(app) as client:
        response = await client.post("/api/clients/some-client/agents", json={"template_id": "weekly-client-report"})
    assert response.status_code == 401
