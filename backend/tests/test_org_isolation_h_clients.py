"""M3 lane H: organization isolation for the client roster (Momentum Phase 2
item 2). Drives the real ``clients`` router behind the real ``AuthMiddleware``
and the shared ``org_isolation_fixtures`` world, mirroring
test_org_isolation_a_projects.py's shape: a cross-organization 404 sweep, list
excludes, and shared-workspace visibility.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import clients
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.fleet import FleetBindingRepository

pytestmark = pytest.mark.asyncio


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.include_router(clients.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_client(client: httpx.AsyncClient, headers: dict[str, str], name: str = "Acme") -> dict[str, Any]:
    response = await client.post("/api/clients", json={"display_name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_client_routes_404_across_organizations(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A)
    headers_b = auth_headers(USER_B)

    async with _client(app) as client:
        created = await _create_client(client, headers_a, "A's client")
        cid = created["id"]
        assignment = await client.post(f"/api/clients/{cid}/assignments", json={"user_id": USER_A, "role": "account_manager"}, headers=headers_a)
        assert assignment.status_code == 201

        # List excludes: B never sees A's client.
        listing = await client.get("/api/clients", headers=headers_b)
        assert listing.status_code == 200
        assert cid not in [c["id"] for c in listing.json()["clients"]]

        # get / patch / archive / assignments: a foreign id is indistinguishable
        # from a missing one.
        assert (await client.get(f"/api/clients/{cid}", headers=headers_b)).status_code == 404
        assert (await client.patch(f"/api/clients/{cid}", json={"notes": "hijacked"}, headers=headers_b)).status_code == 404
        assert (await client.post(f"/api/clients/{cid}/archive", headers=headers_b)).status_code == 404
        assert (await client.post(f"/api/clients/{cid}/assignments", json={"user_id": USER_B, "role": "contributor"}, headers=headers_b)).status_code == 404
        assert (await client.delete(f"/api/clients/{cid}/assignments/{USER_A}", headers=headers_b)).status_code == 404

        # Fleet template stamping's client-scoped agent index: reading another
        # organization's stamped agents is indistinguishable from a missing
        # client, same as every other route above.
        assert (await client.get(f"/api/clients/{cid}/agents", headers=headers_b)).status_code == 404

        # A's own view is untouched by B's attempts.
        still_there = await client.get(f"/api/clients/{cid}", headers=headers_a)
        assert still_there.status_code == 200
        assert still_there.json()["assignments"][0]["user_id"] == USER_A

        # A can read its own (empty) stamped-agent index.
        own_agents = await client.get(f"/api/clients/{cid}/agents", headers=headers_a)
        assert own_agents.status_code == 200
        assert own_agents.json()["agents"] == []


async def test_shared_workspace_co_member_sees_clients(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        created = await _create_client(client, auth_headers(USER_A, ORG_S), "S's client")

        # c is an active admin of S: sees and can open the client a created.
        as_c = auth_headers(USER_C, ORG_S)
        listing = await client.get("/api/clients", headers=as_c)
        assert listing.status_code == 200
        assert created["id"] in [c["id"] for c in listing.json()["clients"]]
        assert (await client.get(f"/api/clients/{created['id']}", headers=as_c)).status_code == 200

        # b has no membership in S at all: AuthMiddleware fails closed before
        # any clients route is even reached.
        assert (await client.get("/api/clients", headers=auth_headers(USER_B, ORG_S))).status_code == 403


async def test_switching_active_organization_flips_client_visibility(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        # The same human (a) owns both org A and is a member of S.
        private_client = await _create_client(client, auth_headers(USER_A), "A private")
        shared_client = await _create_client(client, auth_headers(USER_A, ORG_S), "A in S")

        as_private = auth_headers(USER_A)
        as_shared = auth_headers(USER_A, ORG_S)

        private_ids = {c["id"] for c in (await client.get("/api/clients", headers=as_private)).json()["clients"]}
        assert private_ids == {private_client["id"]}

        shared_ids = {c["id"] for c in (await client.get("/api/clients", headers=as_shared)).json()["clients"]}
        assert shared_ids == {shared_client["id"]}

        assert (await client.get(f"/api/clients/{shared_client['id']}", headers=as_private)).status_code == 404
        assert (await client.get(f"/api/clients/{private_client['id']}", headers=as_shared)).status_code == 404


async def test_mine_lists_only_the_callers_assignments(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A)

    async with _client(app) as client:
        assigned = await _create_client(client, headers_a, "Assigned to A")
        unassigned = await _create_client(client, headers_a, "Not assigned")
        await client.post(f"/api/clients/{assigned['id']}/assignments", json={"user_id": USER_A, "role": "account_manager"}, headers=headers_a)

        mine = await client.get("/api/clients/mine", headers=headers_a)
        assert mine.status_code == 200
        ids = [c["id"] for c in mine.json()["clients"]]
        assert ids == [assigned["id"]]
        assert unassigned["id"] not in ids
