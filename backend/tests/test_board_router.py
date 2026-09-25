"""Momo Board API (Workspace Phase 4 item b2): CRUD plus per-client isolation.

Drives the real ``board`` router behind the real ``AuthMiddleware`` and the
shared ``org_isolation_fixtures`` world, mirroring
``test_org_isolation_h_clients.py``'s shape. Beyond the organization boundary
that lane already covers for ``clients``, this file adds the board's own
per-client access rule: an org owner/admin sees every thread, a plain member
sees only threads for clients they hold a ``client_assignments`` row for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import board, clients
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository
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
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(board.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id* for this test only.

    Doesn't touch ``org_isolation_fixtures.MEMBERSHIPS`` -- inserted directly
    into the shared ``org_world`` database, the same way
    ``test_org_isolation_phase2.py`` mutates membership rows in-test.
    """
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


async def _create_client(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    response = await client.post("/api/clients", json={"display_name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_board_thread_crud_and_messages(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme")
        cid = acme["id"]

        created = await client.post("/api/board/threads", json={"client_id": cid, "kind": "ticket", "subject": "Broken widget"}, headers=headers_a)
        assert created.status_code == 201, created.text
        thread = created.json()
        assert thread["status"] == "new"
        assert thread["kind"] == "ticket"
        tid = thread["id"]

        listing = await client.get("/api/board/threads", headers=headers_a)
        assert listing.status_code == 200
        assert [t["id"] for t in listing.json()["threads"]] == [tid]

        fetched = await client.get(f"/api/board/threads/{tid}", headers=headers_a)
        assert fetched.status_code == 200
        assert fetched.json()["subject"] == "Broken widget"

        patched = await client.patch(f"/api/board/threads/{tid}", json={"status": "triaged"}, headers=headers_a)
        assert patched.status_code == 200
        assert patched.json()["status"] == "triaged"

        posted = await client.post(f"/api/board/threads/{tid}/messages", json={"author_kind": "client", "body": "It's smoking."}, headers=headers_a)
        assert posted.status_code == 201, posted.text
        assert posted.json()["author_user_id"] == USER_A

        messages = await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)
        assert messages.status_code == 200
        assert [m["body"] for m in messages.json()["messages"]] == ["It's smoking."]

        # An unknown thread id is a plain 404, not a 500.
        assert (await client.get("/api/board/threads/does-not-exist", headers=headers_a)).status_code == 404
        # Creating a thread for an unknown client is a 404, never a phantom thread.
        assert (await client.post("/api/board/threads", json={"client_id": "does-not-exist", "subject": "x"}, headers=headers_a)).status_code == 404


async def test_client_member_sees_only_assigned_client_owner_sees_all(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        client1 = await _create_client(client, headers_a, "Client One")
        client2 = await _create_client(client, headers_a, "Client Two")

        assign = await client.post(f"/api/clients/{client1['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201

        thread1 = (await client.post("/api/board/threads", json={"client_id": client1["id"], "subject": "T1"}, headers=headers_a)).json()
        thread2 = (await client.post("/api/board/threads", json={"client_id": client2["id"], "subject": "T2"}, headers=headers_a)).json()

        # D is only assigned to client1: the cross-client 404 probe.
        d_list = await client.get("/api/board/threads", headers=headers_d)
        assert d_list.status_code == 200
        assert [t["id"] for t in d_list.json()["threads"]] == [thread1["id"]]
        assert (await client.get(f"/api/board/threads/{thread2['id']}", headers=headers_d)).status_code == 404
        assert (await client.patch(f"/api/board/threads/{thread2['id']}", json={"status": "closed"}, headers=headers_d)).status_code == 404
        assert (await client.get(f"/api/board/threads/{thread2['id']}/messages", headers=headers_d)).status_code == 404
        assert (await client.post(f"/api/board/threads/{thread2['id']}/messages", json={"body": "hi"}, headers=headers_d)).status_code == 404
        # D cannot even create a thread for a client it isn't assigned to.
        assert (await client.post("/api/board/threads", json={"client_id": client2["id"], "subject": "sneaky"}, headers=headers_d)).status_code == 404
        # D's own client's thread works normally.
        assert (await client.get(f"/api/board/threads/{thread1['id']}", headers=headers_d)).status_code == 200

        # C is an active admin of S: sees and can act on both clients' threads.
        c_list = await client.get("/api/board/threads", headers=headers_c)
        assert c_list.status_code == 200
        assert {t["id"] for t in c_list.json()["threads"]} == {thread1["id"], thread2["id"]}
        assert (await client.get(f"/api/board/threads/{thread2['id']}", headers=headers_c)).status_code == 200
        assert (await client.get("/api/board/threads", params={"client_id": client2["id"]}, headers=headers_c)).status_code == 200


async def test_board_routes_404_across_organizations(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A)
    headers_b = auth_headers(USER_B)

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme private")
        thread = (await client.post("/api/board/threads", json={"client_id": acme["id"], "subject": "T"}, headers=headers_a)).json()

        assert (await client.get(f"/api/board/threads/{thread['id']}", headers=headers_b)).status_code == 404
        listing = await client.get("/api/board/threads", headers=headers_b)
        assert listing.status_code == 200
        assert thread["id"] not in [t["id"] for t in listing.json()["threads"]]


async def test_draft_approve_reply_lifecycle(org_world):  # noqa: F811
    """b4: Momo drafts into ``drafted``; only an owner/admin approves or replies."""
    session_factory = org_world
    app = _build_app(session_factory)
    audit_repo = app.state.audit_repo
    headers_a = auth_headers(USER_A, ORG_S)  # owner
    headers_c = auth_headers(USER_C, ORG_S)  # admin

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme")
        thread = (await client.post("/api/board/threads", json={"client_id": acme["id"], "subject": "T"}, headers=headers_a)).json()
        tid = thread["id"]
        assert thread["status"] == "new"

        # Reply and approve are both unreachable before a draft exists.
        assert (await client.post(f"/api/board/threads/{tid}/approve", headers=headers_a)).status_code == 409
        assert (await client.post(f"/api/board/threads/{tid}/reply", json={"body": "too soon"}, headers=headers_a)).status_code == 409

        drafted = await client.post(f"/api/board/threads/{tid}/draft", json={"body": "Here's a fix for that."}, headers=headers_a)
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["status"] == "drafted"

        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert any(m["author_kind"] == "momo" and m["body"] == "Here's a fix for that." for m in messages)

        # Drafting again while already drafted is not a valid transition.
        assert (await client.post(f"/api/board/threads/{tid}/draft", json={"body": "again"}, headers=headers_a)).status_code == 409

        # Sending the reply before approval is rejected.
        assert (await client.post(f"/api/board/threads/{tid}/reply", json={"body": "jumping the gun"}, headers=headers_a)).status_code == 409

        approved = await client.post(f"/api/board/threads/{tid}/approve", headers=headers_c)
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        replied = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "Fixed — thanks for flagging it!"}, headers=headers_a)
        assert replied.status_code == 200, replied.text
        assert replied.json()["status"] == "replied"

        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert any(m["author_kind"] == "owner" and m["body"] == "Fixed — thanks for flagging it!" for m in messages)

        events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="board.thread.")
        actions = [e["action"] for e in events]
        assert "board.thread.drafted" in actions
        assert "board.thread.approved" in actions
        assert "board.thread.replied" in actions
        assert all(e["outcome"] == "success" for e in events)


async def test_non_owner_cannot_approve_or_reply(org_world):  # noqa: F811
    """A plain member with client access can draft-adjacent actions but never approve/reply."""
    session_factory = org_world
    app = _build_app(session_factory)
    audit_repo = app.state.audit_repo
    headers_a = auth_headers(USER_A, ORG_S)

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        client1 = await _create_client(client, headers_a, "Client One")
        assign = await client.post(f"/api/clients/{client1['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201

        thread = (await client.post("/api/board/threads", json={"client_id": client1["id"], "subject": "T1"}, headers=headers_a)).json()
        tid = thread["id"]

        drafted = await client.post(f"/api/board/threads/{tid}/draft", json={"body": "draft"}, headers=headers_a)
        assert drafted.status_code == 200
        assert drafted.json()["status"] == "drafted"

        # D has client access to thread1 but is neither owner nor admin: rejected, not merely a status conflict.
        denied = await client.post(f"/api/board/threads/{tid}/approve", headers=headers_d)
        assert denied.status_code == 403

        # The thread is untouched -- D's rejected attempt did not sneak the transition through.
        still_drafted = await client.get(f"/api/board/threads/{tid}", headers=headers_a)
        assert still_drafted.json()["status"] == "drafted"

        approved = await client.post(f"/api/board/threads/{tid}/approve", headers=headers_a)
        assert approved.status_code == 200

        denied_reply = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "sneaky"}, headers=headers_d)
        assert denied_reply.status_code == 403

        events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="board.thread.approve")
        assert any(e["outcome"] == "denied" and e["actor_user_id"] == USER_D for e in events)
