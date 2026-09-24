"""M3 isolation gate: personal access tokens (migration 0037_pat_organization).

Drives the real ``/pats`` router (session-authenticated CRUD) and the real
``AuthMiddleware`` PAT-Bearer authentication path behind the shared
``org_isolation_fixtures`` world, mirroring test_org_isolation_h_clients.py's
shape. Covers the four risk statements from the M3 isolation gate:

1. org B cannot list, read, or revoke org A's PATs.
2. a PAT minted in one organization gets 404 on another organization's
   resources.
3. revoking the owner's membership in the PAT's organization stops the PAT
   from authenticating (fail closed).
4. switching/forging the active-organization workspace cookie does not let
   a PAT act in a different organization than the one it was minted in.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_B, _user_from_access_token, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import auth as auth_router
from app.gateway.routers import clients as clients_router
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.personal_access_tokens import PersonalAccessTokenRepository
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio


class _FakeLocalProvider:
    """Resolves a PAT's owning user straight from the org_world database,
    the same lookup ``LocalAuthProvider.get_user`` performs in production."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def get_user(self, user_id: str) -> Any:
        async with self._sf() as session:
            row = await session.get(UserRow, user_id)
        if row is None:
            return None
        return SimpleNamespace(id=row.id, email=row.email, system_role=row.system_role, disabled_at=row.disabled_at)


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pat_repo = PersonalAccessTokenRepository(session_factory)
    app.state.client_repo = ClientRepository(session_factory)
    app.include_router(auth_router.router)
    app.include_router(clients_router.router)

    @app.get("/api/probe")
    async def probe(request: Request):
        return {"organization_id": getattr(request.state, "organization_id", None)}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture()
async def pat_world(org_world, monkeypatch):  # noqa: F811
    session_factory = org_world
    # auth.py binds ``get_current_user_from_request`` at import time (``from
    # app.gateway.deps import ...``), a separate name from the one
    # ``org_world`` already patches on ``app.gateway.deps`` itself (which
    # AuthMiddleware re-imports dynamically per request and therefore does
    # pick up). The /pats handlers need their own patch of the same fake.
    monkeypatch.setattr("app.gateway.routers.auth.get_current_user_from_request", _user_from_access_token)
    monkeypatch.setattr("app.gateway.deps.get_local_provider", lambda: _FakeLocalProvider(session_factory))
    # This test drives PAT Bearer auth against ``/api/probe`` and the real
    # clients router, neither of which is on the production PAT route
    # allowlist (a separate, already-covered concern) -- allow every route so
    # only organization scoping is under test here.
    monkeypatch.setattr("app.gateway.auth.pat.is_pat_allowed_route", lambda method, path: True)
    return session_factory


async def _create_pat(client: httpx.AsyncClient, headers: dict[str, str], name: str, scopes: list[str]) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/pats", json={"name": name, "scopes": scopes}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_pat_list_and_revoke_scoped_by_owner_and_active_organization(pat_world):
    session_factory = pat_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        # Same human (a) mints one PAT per active organization.
        pat_private = await _create_pat(client, auth_headers(USER_A), "private", ["runs:read"])
        pat_shared = await _create_pat(client, auth_headers(USER_A, ORG_S), "shared", ["runs:read"])
        pat_b = await _create_pat(client, auth_headers(USER_B), "b-own", ["runs:read"])

        # b never sees or can revoke a's tokens (owner filter -- pre-existing).
        listing_b = await client.get("/api/v1/auth/pats", headers=auth_headers(USER_B))
        assert listing_b.status_code == 200
        assert pat_private["id"] not in [p["id"] for p in listing_b.json()]
        assert (await client.delete(f"/api/v1/auth/pats/{pat_private['id']}", headers=auth_headers(USER_B))).status_code == 404

        # a's own listing is scoped by *active organization*, not just owner:
        # switching active org changes which of a's own tokens are visible.
        listing_private = await client.get("/api/v1/auth/pats", headers=auth_headers(USER_A))
        assert [p["id"] for p in listing_private.json()] == [pat_private["id"]]

        listing_shared = await client.get("/api/v1/auth/pats", headers=auth_headers(USER_A, ORG_S))
        assert [p["id"] for p in listing_shared.json()] == [pat_shared["id"]]

        # a cannot revoke the org-S token while active in the private org,
        # even though it is a's own token by user_id.
        assert (await client.delete(f"/api/v1/auth/pats/{pat_shared['id']}", headers=auth_headers(USER_A))).status_code == 404
        # ...but can while active in org S.
        revoked = await client.delete(f"/api/v1/auth/pats/{pat_shared['id']}", headers=auth_headers(USER_A, ORG_S))
        assert revoked.status_code == 200

        assert pat_b["id"] not in [p["id"] for p in listing_private.json()]


async def test_pat_authentication_pins_to_minted_organization_ignoring_workspace_cookie(pat_world):
    session_factory = pat_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        created = await _create_pat(client, auth_headers(USER_A, ORG_S), "shared-automation", ["threads:read"])
        token = created["token"]

        probe = await client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})
        assert probe.status_code == 200
        assert probe.json()["organization_id"] == ORG_S

        # Smuggling a workspace-selection cookie alongside the Bearer token
        # must not move the PAT to a different organization: cookie-based
        # workspace selection only ever applies to interactive sessions.
        probe_with_cookie = await client.get(
            "/api/probe",
            headers={"Authorization": f"Bearer {token}", "Cookie": f"deerflow_workspace={ORG_A}"},
        )
        assert probe_with_cookie.status_code == 200
        assert probe_with_cookie.json()["organization_id"] == ORG_S


async def test_revoking_organization_membership_fails_closed_for_its_pat(pat_world):
    session_factory = pat_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        created = await _create_pat(client, auth_headers(USER_A, ORG_S), "shared-automation", ["threads:read"])
        token = created["token"]

        assert (await client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})).status_code == 200

        async with session_factory() as session, session.begin():
            membership = await session.get(OrganizationMemberRow, (ORG_S, USER_A))
            assert membership is not None
            membership.status = "removed"

        denied = await client.get("/api/probe", headers={"Authorization": f"Bearer {token}"})
        assert denied.status_code == 403
        assert denied.json() == {"detail": "Active organization membership required"}


async def test_pat_minted_in_one_organization_gets_404_on_another_organizations_resources(pat_world):
    session_factory = pat_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        shared_client = await client.post("/api/clients", json={"display_name": "S's client"}, headers=auth_headers(USER_A, ORG_S))
        assert shared_client.status_code == 201, shared_client.text
        shared_client_id = shared_client.json()["id"]

        private_client = await client.post("/api/clients", json={"display_name": "A's private client"}, headers=auth_headers(USER_A))
        assert private_client.status_code == 201, private_client.text
        private_client_id = private_client.json()["id"]

        pat = await _create_pat(client, auth_headers(USER_A, ORG_S), "shared-automation", ["clients:read"])
        pat_headers = {"Authorization": f"Bearer {pat['token']}"}

        listing = await client.get("/api/clients", headers=pat_headers)
        assert listing.status_code == 200
        ids = [c["id"] for c in listing.json()["clients"]]
        assert shared_client_id in ids
        assert private_client_id not in ids

        assert (await client.get(f"/api/clients/{shared_client_id}", headers=pat_headers)).status_code == 200
        assert (await client.get(f"/api/clients/{private_client_id}", headers=pat_headers)).status_code == 404
