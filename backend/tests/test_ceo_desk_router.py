"""CEO Desk API (queue item e14, backend slice 1): the owner/admin "needs my
yes" queue and agent-seat roster.

Drives the real ``ceo_desk`` router behind the real ``AuthMiddleware`` and the
shared ``org_isolation_fixtures`` world, mirroring ``test_board_router.py``'s
shape. Unlike the Board, every route here is owner/admin only: a plain
member and a client-role member both get a flat 403, never a 200 with an
empty or filtered list.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_C, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import board, ceo_desk, clients
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.fleet import FleetBindingRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

USER_D = "user-d"


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.board_repo = BoardRepository(session_factory)
    app.state.agent_seat_repo = AgentSeatRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(board.router)
    app.include_router(ceo_desk.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id*. Mirrors ``test_board_router.py``."""
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


async def test_needs_my_yes_and_seats_visible_to_owner_and_admin(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    async with _client(app) as client:
        created = await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)
        assert created.status_code == 201, created.text
        client_id = created.json()["id"]

        thread = await client.post("/api/board/threads", json={"client_id": client_id, "kind": "ticket", "subject": "Broken widget"}, headers=headers_a)
        assert thread.status_code == 201, thread.text
        thread_id = thread.json()["id"]

        drafted = await client.post(f"/api/board/threads/{thread_id}/draft", json={"body": "Here's a proposed reply."}, headers=headers_a)
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["status"] == "drafted"

        with acting_as(USER_A, ORG_S):
            seat_repo = AgentSeatRepository(session_factory)
            claimed = await seat_repo.claim_seat(seat="cmo", agent_name="cmo-agent", kpi="pipeline", weekly_token_budget=0, claimed_by_user_id=USER_A)

        for headers in (headers_a, headers_c):
            needs_yes = await client.get("/api/ceo/needs-my-yes", headers=headers)
            assert needs_yes.status_code == 200, needs_yes.text
            body = needs_yes.json()
            assert [d["thread_id"] for d in body["board_drafts"]] == [thread_id]
            assert [s["seat_id"] for s in body["seat_ratifications"]] == [claimed["id"]]

            roster = await client.get("/api/ceo/seats", headers=headers)
            assert roster.status_code == 200, roster.text
            seats = roster.json()["seats"]
            assert [s["seat"] for s in seats] == ["cmo"]
            assert seats[0]["status"] == "claimed"
            assert seats[0]["burn_this_week"] == 0
            assert seats[0]["paused"] is False


async def test_member_and_client_get_403(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_member = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        acme = await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)
        assert acme.status_code == 201

        # D is a plain member, no client assignment: gets 403 on both routes.
        assert (await client.get("/api/ceo/needs-my-yes", headers=headers_member)).status_code == 403
        assert (await client.get("/api/ceo/seats", headers=headers_member)).status_code == 403

        # Assigning D as a client contact doesn't change that: the CEO Desk
        # is owner/admin only, not "anyone with any access to the org".
        assign = await client.post(f"/api/clients/{acme.json()['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201
        assert (await client.get("/api/ceo/needs-my-yes", headers=headers_member)).status_code == 403
        assert (await client.get("/api/ceo/seats", headers=headers_member)).status_code == 403
