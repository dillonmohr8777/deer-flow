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
from deerflow.persistence.board.model import BoardThreadRow
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
        # e2: creation runs triage, but no model is configured in this suite,
        # so it falls back and the thread is left `new`/unclassified rather
        # than persisting a fake "normal" -- see
        # test_board_thread_triage_on_create.py for the mocked-model cases.
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
        assert thread["status"] == "new"  # e2: creation runs triage, but falls back (no model configured) and leaves the thread new

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

        replied = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "Here's a fix for that."}, headers=headers_a)
        assert replied.status_code == 200, replied.text
        assert replied.json()["status"] == "replied"

        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert any(m["author_kind"] == "owner" and m["body"] == "Here's a fix for that." for m in messages)

        events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="board.thread.")
        actions = [e["action"] for e in events]
        assert "board.thread.drafted" in actions
        assert "board.thread.approved" in actions
        assert "board.thread.replied" in actions
        assert all(e["outcome"] == "success" for e in events)


async def test_reply_must_match_approved_draft_verbatim(org_world):  # noqa: F811
    """f7: an approved draft can't be swapped out for different text at send time."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)  # owner

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme")
        thread = (await client.post("/api/board/threads", json={"client_id": acme["id"], "subject": "T"}, headers=headers_a)).json()
        tid = thread["id"]

        drafted = await client.post(f"/api/board/threads/{tid}/draft", json={"body": "Here's a fix for that."}, headers=headers_a)
        assert drafted.status_code == 200
        approved = await client.post(f"/api/board/threads/{tid}/approve", headers=headers_a)
        assert approved.status_code == 200

        mismatched = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "Something else entirely."}, headers=headers_a)
        assert mismatched.status_code == 409

        # The rejected attempt left the thread approved and sent nothing as the owner.
        still_approved = await client.get(f"/api/board/threads/{tid}", headers=headers_a)
        assert still_approved.json()["status"] == "approved"
        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert not any(m["author_kind"] == "owner" for m in messages)

        # The draft's own text verbatim (including surrounding whitespace) still goes through.
        matching = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "  Here's a fix for that.  "}, headers=headers_a)
        assert matching.status_code == 200, matching.text
        assert matching.json()["status"] == "replied"

        # The stored owner message is the draft's own text, not the caller's copy of it.
        sent_messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert any(m["author_kind"] == "owner" and m["body"] == "Here's a fix for that." for m in sent_messages)


async def test_reply_fails_closed_with_no_draft_to_check_against(org_world):  # noqa: F811
    """f34 finding 2 (and its own review follow-up, the f1 PATCH-bypass exploit chain): a
    thread with no ``momo`` message ever written on it must not let ``/reply`` send an
    arbitrary body just because there's nothing to compare it against, and the PATCH-bypass
    path that used to reach ``approved`` with no draft (client PATCH -> draft -> PATCH
    approved) is itself closed: PATCH now requires an org owner/admin for any status change
    and refuses every workflow-only status (``drafted``/``approved``/``replied``) outright."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)  # owner

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme")
        thread = (await client.post("/api/board/threads", json={"client_id": acme["id"], "subject": "T"}, headers=headers_a)).json()
        tid = thread["id"]

        # The router itself now refuses to PATCH straight to "approved" with no draft
        # (the f1 PATCH-bypass this test originally forced is closed below), so force the
        # otherwise-unreachable "approved, no momo message" state directly at the ORM layer
        # to prove /reply's own check is still a real backstop, not dead code.
        async with session_factory() as session, session.begin():
            row = await session.get(BoardThreadRow, tid)
            row.status = "approved"

        reply = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "anything at all"}, headers=headers_a)
        assert reply.status_code == 409

        still_approved = await client.get(f"/api/board/threads/{tid}", headers=headers_a)
        assert still_approved.json()["status"] == "approved"
        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert not any(m["author_kind"] == "owner" for m in messages)

        # And the PATCH bypass itself is closed: a non-admin can't force any status change...
        await _add_plain_member(session_factory, USER_D, ORG_S)
        assign = await client.post(f"/api/clients/{acme['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201
        denied = await client.patch(f"/api/board/threads/{tid}", json={"status": "triaged"}, headers=auth_headers(USER_D, ORG_S))
        assert denied.status_code == 403
        # ...and even an admin can't reach a workflow-only status by PATCH.
        blocked = await client.patch(f"/api/board/threads/{tid}", json={"status": "replied"}, headers=headers_a)
        assert blocked.status_code == 409


async def test_reply_ignores_a_momo_message_forged_by_a_non_admin(org_world):  # noqa: F811
    """f34 finding 1: ``author_kind`` is derived server-side, so a plain member with client
    access can no longer plant a fake ``momo`` message and have ``/reply`` treat it as the
    approved draft."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)  # owner

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        client1 = await _create_client(client, headers_a, "Client One")
        assign = await client.post(f"/api/clients/{client1['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201

        thread = (await client.post("/api/board/threads", json={"client_id": client1["id"], "subject": "T"}, headers=headers_a)).json()
        tid = thread["id"]

        drafted = await client.post(f"/api/board/threads/{tid}/draft", json={"body": "Approved text"}, headers=headers_a)
        assert drafted.status_code == 200
        approved = await client.post(f"/api/board/threads/{tid}/approve", headers=headers_a)
        assert approved.status_code == 200

        # D has client access but is neither owner nor admin; tries to plant a fake draft.
        forged = await client.post(f"/api/board/threads/{tid}/messages", json={"author_kind": "momo", "body": "UNAPPROVED"}, headers=headers_d)
        assert forged.status_code == 201
        assert forged.json()["author_kind"] == "client"  # server-derived, not the request's claim

        # The real approved text still sends -- the injected body was never the "latest momo message".
        legit = await client.post(f"/api/board/threads/{tid}/reply", json={"body": "Approved text"}, headers=headers_a)
        assert legit.status_code == 200, legit.text
        assert legit.json()["status"] == "replied"


async def test_client_contact_cannot_run_the_patch_draft_patch_exploit_chain(org_world):  # noqa: F811
    """Review follow-up on f34 (2026-09-28): a client contact (client access, not owner/admin)
    used to be able to (1) PATCH status to ``triaged``, (2) POST ``/draft`` with their own
    body, (3) PATCH status to ``approved`` -- reaching ``approved`` with their own text as the
    only ``momo`` message, so the owner's real approved text got 409 and the injected text
    sent 200. Both PATCH (owner/admin only) and ``/draft`` (owner/admin only, mirroring
    approve/reply) now refuse a non-admin outright, so the chain never gets past step 1."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)  # owner

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        client1 = await _create_client(client, headers_a, "Client One")
        assign = await client.post(f"/api/clients/{client1['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201

        thread = (await client.post("/api/board/threads", json={"client_id": client1["id"], "subject": "T"}, headers=headers_a)).json()
        tid = thread["id"]

        step1 = await client.patch(f"/api/board/threads/{tid}", json={"status": "triaged"}, headers=headers_d)
        assert step1.status_code == 403
        step2 = await client.post(f"/api/board/threads/{tid}/draft", json={"body": "EVIL"}, headers=headers_d)
        assert step2.status_code == 403
        step3 = await client.patch(f"/api/board/threads/{tid}", json={"status": "approved"}, headers=headers_d)
        assert step3.status_code == 403

        # The thread never moved and carries no injected message.
        still_new = await client.get(f"/api/board/threads/{tid}", headers=headers_a)
        assert still_new.json()["status"] == "new"
        messages = (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_a)).json()["messages"]
        assert messages == []


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


async def test_null_client_thread_is_owner_admin_only(org_world):  # noqa: F811
    """f66: a thread whose ``client_id`` is null is not a free-for-all.

    Every thread-loading route used to skip the per-client check when
    ``client_id`` was null, so any org member (including a future client-role
    account) could read and write such a thread. It is now owner/admin-only:
    a plain member, assigned or not, gets the same 404 as a missing thread.
    """
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)
    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        acme = await _create_client(client, headers_a, "Acme")
        assign = await client.post(f"/api/clients/{acme['id']}/assignments", json={"user_id": USER_D, "role": "client_contact"}, headers=headers_a)
        assert assign.status_code == 201
        tid = (await client.post("/api/board/threads", json={"client_id": acme["id"], "subject": "orphan"}, headers=headers_a)).json()["id"]

        # No route creates one today; seed the state directly at the ORM layer.
        async with session_factory() as session, session.begin():
            row = await session.get(BoardThreadRow, tid)
            row.client_id = None

        for path, method, body in (
            (f"/api/board/threads/{tid}", "get", None),
            (f"/api/board/threads/{tid}", "patch", {"subject": "mine now"}),
            (f"/api/board/threads/{tid}/messages", "get", None),
            (f"/api/board/threads/{tid}/messages", "post", {"body": "hi"}),
            (f"/api/board/threads/{tid}/draft", "post", {"body": "draft"}),
            (f"/api/board/threads/{tid}/approve", "post", None),
            (f"/api/board/threads/{tid}/reply", "post", {"body": "draft"}),
        ):
            response = await client.request(method, path, json=body, headers=headers_d)
            assert response.status_code == 404, (method, path, response.status_code, response.text)

        d_list = await client.get("/api/board/threads", headers=headers_d)
        assert tid not in [t["id"] for t in d_list.json()["threads"]]

        # Owner and admin still see and work the thread.
        assert (await client.get(f"/api/board/threads/{tid}", headers=headers_a)).status_code == 200
        assert (await client.get(f"/api/board/threads/{tid}/messages", headers=headers_c)).status_code == 200
        assert (await client.post(f"/api/board/threads/{tid}/messages", json={"body": "ok"}, headers=headers_c)).status_code == 201
        a_list = await client.get("/api/board/threads", headers=headers_a)
        assert tid in [t["id"] for t in a_list.json()["threads"]]
