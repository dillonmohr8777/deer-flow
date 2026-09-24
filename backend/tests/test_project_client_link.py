"""Tests for linking projects to clients via ``client_id`` (Momentum welcome lane).

Non-organization-scoped coverage reuses ``test_projects_router.py``'s stub auth
harness (``_StubAuthMiddleware``, ``_as_user``), extended with a real
``ClientRepository`` alongside the project repo. Cross-organization rejection
reuses the shared M3 ``org_isolation_fixtures`` world (real ``AuthMiddleware``)
so that check runs against the same server-resolved organization context
production requests get, mirroring ``test_org_isolation_a_projects.py``.
"""

from __future__ import annotations

import anyio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from org_isolation_fixtures import USER_A, USER_B, acting_as, auth_headers, org_world  # noqa: F401
from test_projects_router import _PERMISSIONS_HEADER, _STUB_PERMISSIONS, _as_user, _StubAuthMiddleware  # noqa: E402

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import Permissions
from app.gateway.routers import clients, projects
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository


async def _init_db(tmp_path) -> None:
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'project_client_link.db'}", sqlite_dir=str(tmp_path))


def _build_app(tmp_path) -> FastAPI:
    """Stub-authed app (no organization scoping) with real project + client repos."""
    anyio.run(_init_db, tmp_path)
    sf = get_session_factory()
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware)
    app.state.project_repo = ProjectRepository(sf)
    app.state.client_repo = ClientRepository(sf)
    app.state.thread_store = ThreadMetaRepository(sf)
    app.include_router(projects.router)
    app.include_router(clients.router)
    return app


@pytest.fixture(autouse=True)
def _close_engine_after_test():
    yield
    anyio.run(close_engine)


#: The stub harness's default permission set omits clients:*; extend it so
#: ``_create_client`` (a test fixture step, not the behavior under test) can
#: seed a client without every test having to pass its own header.
_WITH_CLIENTS_PERMISSIONS = {_PERMISSIONS_HEADER: ",".join([*_STUB_PERMISSIONS, Permissions.CLIENTS_READ, Permissions.CLIENTS_WRITE])}


def _create_client(client: TestClient, name: str = "Deborah Mara") -> dict:
    response = client.post("/api/clients", json={"display_name": name}, headers=_WITH_CLIENTS_PERMISSIONS)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_project_with_client_id_links_and_returns_it(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        c = _create_client(client)
        created = client.post("/api/projects", json={"name": "Deborah Mara", "client_id": c["id"]})
        assert created.status_code == 201, created.text
        assert created.json()["client_id"] == c["id"]

        fetched = client.get(f"/api/projects/{created.json()['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["client_id"] == c["id"]


def test_create_project_without_client_id_leaves_it_null(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/projects", json={"name": "no client"})
        assert created.status_code == 201
        assert created.json()["client_id"] is None


def test_create_project_rejects_unknown_client_id(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        rejected = client.post("/api/projects", json={"name": "p", "client_id": "nope"})
        assert rejected.status_code == 422
        # Rejected outright: no half-created project left behind.
        assert client.get("/api/projects", headers=_as_user("user-a")).json()["projects"] == []


def test_patch_project_links_client_id(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        c = _create_client(client)
        project = client.post("/api/projects", json={"name": "p"}).json()
        assert project["client_id"] is None

        patched = client.patch(f"/api/projects/{project['id']}", json={"client_id": c["id"]})
        assert patched.status_code == 200
        assert patched.json()["client_id"] == c["id"]


def test_patch_project_rejects_unknown_client_id(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        rejected = client.patch(f"/api/projects/{project['id']}", json={"client_id": "nope"})
        assert rejected.status_code == 422
        assert client.get(f"/api/projects/{project['id']}").json()["client_id"] is None


def test_patch_project_omitting_client_id_leaves_it_unchanged(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        c = _create_client(client)
        project = client.post("/api/projects", json={"name": "p", "client_id": c["id"]}).json()

        patched = client.patch(f"/api/projects/{project['id']}", json={"name": "renamed"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "renamed"
        assert patched.json()["client_id"] == c["id"]


@pytest.mark.asyncio
async def test_create_project_rejects_another_organizations_client(org_world):  # noqa: F811
    """A client from a foreign organization is indistinguishable from unknown (422)."""
    session_factory = org_world
    client_repo = ClientRepository(session_factory)
    with acting_as(USER_B):
        foreign_client = await client_repo.create(display_name="B's client")
    with acting_as(USER_A):
        own_client = await client_repo.create(display_name="A's client")

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.project_repo = ProjectRepository(session_factory)
    app.state.client_repo = client_repo
    app.state.thread_store = ThreadMetaRepository(session_factory)
    app.include_router(projects.router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.post("/api/projects", json={"name": "p", "client_id": foreign_client["id"]}, headers=auth_headers(USER_A))
        assert rejected.status_code == 422

        accepted = await client.post("/api/projects", json={"name": "p", "client_id": own_client["id"]}, headers=auth_headers(USER_A))
        assert accepted.status_code == 201
        assert accepted.json()["client_id"] == own_client["id"]
