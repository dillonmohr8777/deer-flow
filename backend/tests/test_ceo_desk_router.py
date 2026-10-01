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
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_C, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.deps import get_config
from app.gateway.routers import board, ceo_desk, clients
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.ceo_desk import CeoDeskDigestRepository
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.fleet import FleetBindingRepository
from deerflow.persistence.organizations.identity import private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

USER_D = "user-d"
# ORG_S plays Momentum's own workspace by default (its momentum_internal slug
# matches), mirroring test_team_board_router.py's convention.
MOMENTUM_SLUG = private_organization_slug(STORAGE_S)


def _momentum_internal_config(*, enabled: bool = True, slugs: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(momentum_internal=SimpleNamespace(enabled=enabled, organization_slugs=[MOMENTUM_SLUG] if slugs is None else slugs))


def _build_app(session_factory, *, config: SimpleNamespace | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.board_repo = BoardRepository(session_factory)
    app.state.agent_seat_repo = AgentSeatRepository(session_factory)
    app.state.ceo_desk_digest_repo = CeoDeskDigestRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.state.team_board_repo = TeamBoardRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(board.router)
    app.include_router(ceo_desk.router)
    app.dependency_overrides[get_config] = lambda: config or _momentum_internal_config()
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
            assert body["board_drafts"][0]["status"] == "drafted"
            assert body["board_drafts"][0]["draft_body"] == "Here's a proposed reply."
            assert [s["seat_id"] for s in body["seat_ratifications"]] == [claimed["id"]]

            roster = await client.get("/api/ceo/seats", headers=headers)
            assert roster.status_code == 200, roster.text
            seats = roster.json()["seats"]
            assert [s["seat"] for s in seats] == ["cmo"]
            assert seats[0]["status"] == "claimed"
            assert seats[0]["burn_this_week"] == 0
            assert seats[0]["paused"] is False


async def test_needs_my_yes_keeps_an_approved_thread_until_its_reply_is_sent(org_world):  # noqa: F811
    """An ``approved`` thread still needs its own explicit Send (``assert_can_reply``),
    so the queue keeps it -- with Momo's draft body -- past Approve; a reply that
    matches the draft verbatim clears it.
    """
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        created = await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)
        client_id = created.json()["id"]
        thread = await client.post("/api/board/threads", json={"client_id": client_id, "kind": "ticket", "subject": "Broken widget"}, headers=headers_a)
        thread_id = thread.json()["id"]
        await client.post(f"/api/board/threads/{thread_id}/draft", json={"body": "Here's a proposed reply."}, headers=headers_a)

        approved = await client.post(f"/api/board/threads/{thread_id}/approve", headers=headers_a)
        assert approved.status_code == 200, approved.text

        needs_yes = await client.get("/api/ceo/needs-my-yes", headers=headers_a)
        board_drafts = needs_yes.json()["board_drafts"]
        assert [d["thread_id"] for d in board_drafts] == [thread_id]
        assert board_drafts[0]["status"] == "approved"
        assert board_drafts[0]["draft_body"] == "Here's a proposed reply."

        replied = await client.post(f"/api/board/threads/{thread_id}/reply", json={"body": "Here's a proposed reply."}, headers=headers_a)
        assert replied.status_code == 200, replied.text

        needs_yes_after = await client.get("/api/ceo/needs-my-yes", headers=headers_a)
        assert needs_yes_after.json()["board_drafts"] == []


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
        assert (await client.get("/api/ceo/digest", headers=headers_member)).status_code == 403


async def test_ratify_seat_requires_an_independent_actor(org_world):  # noqa: F811
    """The needs-my-yes queue's one-tap ratify action (queue item e14, slice 4)."""
    session_factory = org_world
    app = _build_app(session_factory)
    audit_repo = app.state.audit_repo
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    with acting_as(USER_A, ORG_S):
        seat_repo = AgentSeatRepository(session_factory)
        claimed = await seat_repo.claim_seat(seat="cmo", agent_name="cmo-agent", kpi="pipeline", weekly_token_budget=0, claimed_by_user_id=USER_A)
    seat_id = claimed["id"]

    async with _client(app) as client:
        # A claimed the seat, so A cannot also be the one who ratifies it.
        self_ratify = await client.post(f"/api/ceo/seats/{seat_id}/ratify", headers=headers_a)
        assert self_ratify.status_code == 403, self_ratify.text
        still_claimed = await client.get("/api/ceo/seats", headers=headers_a)
        assert still_claimed.json()["seats"][0]["status"] == "claimed"

        # C is an independent admin: ratification succeeds.
        ratified = await client.post(f"/api/ceo/seats/{seat_id}/ratify", headers=headers_c)
        assert ratified.status_code == 200, ratified.text
        body = ratified.json()
        assert body == {"seat_id": seat_id, "seat": "cmo", "agent_name": "cmo-agent", "status": "ratified"}

        # Already ratified: a second ratify is refused as a bad transition.
        again = await client.post(f"/api/ceo/seats/{seat_id}/ratify", headers=headers_c)
        assert again.status_code == 409, again.text

        events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="ceo.seat.ratify")
        outcomes = [(e["outcome"], e["target_id"]) for e in events]
        assert ("denied", seat_id) in outcomes  # A's self-ratify attempt
        assert ("success", seat_id) in outcomes  # C's independent ratify


async def test_ratify_seat_is_owner_or_admin_only(org_world):  # noqa: F811
    """f178 review follow-up: no test covered a plain member's HTTP ratify attempt,
    so a mutant deleting ``_require_admin`` from ``ratify_seat`` still passed."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_member = auth_headers(USER_D, ORG_S)

    with acting_as(USER_A, ORG_S):
        seat_repo = AgentSeatRepository(session_factory)
        claimed = await seat_repo.claim_seat(seat="coo", agent_name="coo-agent", kpi="ops", weekly_token_budget=0, claimed_by_user_id=USER_A)
    seat_id = claimed["id"]

    async with _client(app) as client:
        denied = await client.post(f"/api/ceo/seats/{seat_id}/ratify", headers=headers_member)
        assert denied.status_code == 403, denied.text
        still_claimed = await client.get("/api/ceo/seats", headers=headers_a)
        assert still_claimed.json()["seats"][0]["status"] == "claimed"


async def test_reopen_seat_is_owner_or_admin_only(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    audit_repo = app.state.audit_repo
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_member = auth_headers(USER_D, ORG_S)

    with acting_as(USER_A, ORG_S):
        seat_repo = AgentSeatRepository(session_factory)
        claimed = await seat_repo.claim_seat(seat="cfo", agent_name="cfo-agent", kpi="runway", weekly_token_budget=0, claimed_by_user_id=USER_A)
    seat_id = claimed["id"]

    async with _client(app) as client:
        # A plain member gets a flat 403, same as every other CEO Desk route.
        denied = await client.post(f"/api/ceo/seats/{seat_id}/reopen", headers=headers_member)
        assert denied.status_code == 403, denied.text

        # The owner can reopen the claim itself (no self-action restriction
        # for reopen, unlike ratify -- an owner veto is unconditional).
        reopened = await client.post(f"/api/ceo/seats/{seat_id}/reopen", headers=headers_a)
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["status"] == "reopened"

        # Already reopened: a second reopen is refused as a bad transition
        # (f178 review follow-up -- no prior test exercised this, so a
        # mutant deleting the assert_can_reopen check still passed).
        again = await client.post(f"/api/ceo/seats/{seat_id}/reopen", headers=headers_a)
        assert again.status_code == 409, again.text

        # An admin can also reopen -- this codebase's owner/admin convention.
        with acting_as(USER_A, ORG_S):
            reclaimed = await seat_repo.claim_seat(seat="cfo", agent_name="cfo-agent-2", kpi="runway", weekly_token_budget=0, claimed_by_user_id=USER_A)
        reopened_again = await client.post(f"/api/ceo/seats/{reclaimed['id']}/reopen", headers=headers_c)
        assert reopened_again.status_code == 200, reopened_again.text

        events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="ceo.seat.reopen")
        assert len(events) == 2  # the owner's reopen and the admin's reopen; the denied 409 records no event
        assert all(e["outcome"] == "success" for e in events)
        assert {e["target_id"] for e in events} == {seat_id, reclaimed["id"]}


async def test_ratify_and_reopen_announce_to_exec(org_world):  # noqa: F811
    """f186(a): deleting either announce_to_exec call left every other test
    green, so the #exec post itself was unpinned. Mirrors
    test_exec_seat_tools.py's own announcement assertions."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)

    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(session_factory)
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat_repo = AgentSeatRepository(session_factory)
        claimed = await seat_repo.claim_seat(seat="cmo", agent_name="cmo-agent", kpi="pipeline", weekly_token_budget=0, claimed_by_user_id=USER_A)
    seat_id = claimed["id"]

    async with _client(app) as client:
        ratified = await client.post(f"/api/ceo/seats/{seat_id}/ratify", headers=headers_c)
        assert ratified.status_code == 200, ratified.text

        reopened = await client.post(f"/api/ceo/seats/{seat_id}/reopen", headers=headers_a)
        assert reopened.status_code == 200, reopened.text

    with acting_as(USER_A, ORG_S):
        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    bodies = [m["body"] for m in messages]
    assert any("ratified cmo for cmo-agent" in b for b in bodies)
    assert any("reopened cmo (was held by cmo-agent)" in b for b in bodies)


async def test_ratify_and_reopen_unknown_seat_404(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        assert (await client.post("/api/ceo/seats/does-not-exist/ratify", headers=headers_a)).status_code == 404
        assert (await client.post("/api/ceo/seats/does-not-exist/reopen", headers=headers_a)).status_code == 404


async def test_digest_endpoint_reads_the_latest_recorded_digest(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        before = await client.get("/api/ceo/digest", headers=headers_a)
        assert before.status_code == 200, before.text
        assert before.json()["digest"] is None

        with acting_as(USER_A, ORG_S):
            digest_repo = CeoDeskDigestRepository(session_factory)
            await digest_repo.record_digest(digest_text="Shipped 1. Stuck on 0. Nothing needs your yes.", shipped_count=1, stuck_count=0, needs_my_yes_drafts=0, needs_my_yes_ratifications=0)

        after = await client.get("/api/ceo/digest", headers=headers_a)
        assert after.status_code == 200, after.text
        body = after.json()["digest"]
        assert body["digest_text"] == "Shipped 1. Stuck on 0. Nothing needs your yes."
        assert body["shipped_count"] == 1


async def test_exec_feed_reads_and_posts(org_world):  # noqa: F811
    """#exec is a default channel: it exists before anyone creates it, and the
    CEO Desk can read it and reply into it as the signed-in owner/admin."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        before = await client.get("/api/ceo/channels/exec/messages", headers=headers_a)
        assert before.status_code == 200, before.text
        assert before.json() == {"channel": "exec", "exists": True, "messages": []}

        # Leading '#' and mixed case are accepted, matching team_board_tools.py.
        posted = await client.post("/api/ceo/channels/%23EXEC/messages", json={"body": "Shipping the Q4 plan today."}, headers=headers_a)
        assert posted.status_code == 201, posted.text
        assert posted.json()["author_user_id"] == USER_A
        assert posted.json()["body"] == "Shipping the Q4 plan today."

        after = await client.get("/api/ceo/channels/exec/messages", headers=headers_a)
        assert after.status_code == 200, after.text
        messages = after.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["body"] == "Shipping the Q4 plan today."


async def test_feed_post_rejects_a_whitespace_only_body(org_world):  # noqa: F811
    """f193: a body that is only whitespace is empty after the handler's own
    .strip(), so it must 422 the same as a truly empty body (mutant-checked:
    deleting this branch left every other test green)."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        resp = await client.post("/api/ceo/channels/exec/messages", json={"body": "   "}, headers=headers_a)
        assert resp.status_code == 422, resp.text


async def test_fleet_feed_before_creation_then_after(org_world):  # noqa: F811
    """#fleet has no default: reading it before anyone creates it reports
    ``exists: false`` with no messages, and posting 404s; once an owner/admin
    creates it (from the Team Board), both work."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        before = await client.get("/api/ceo/channels/fleet/messages", headers=headers_a)
        assert before.status_code == 200, before.text
        assert before.json() == {"channel": "fleet", "exists": False, "messages": []}

        refused = await client.post("/api/ceo/channels/fleet/messages", json={"body": "hello"}, headers=headers_a)
        assert refused.status_code == 404

        with acting_as(USER_A, ORG_S):
            team_repo = TeamBoardRepository(session_factory)
            await team_repo.create_channel(slug="fleet", name="Fleet", topic="", created_by_user_id=USER_A)

        after = await client.get("/api/ceo/channels/fleet/messages", headers=headers_a)
        assert after.status_code == 200, after.text
        assert after.json() == {"channel": "fleet", "exists": True, "messages": []}

        posted = await client.post("/api/ceo/channels/fleet/messages", json={"body": "Fleet, status check."}, headers=headers_a)
        assert posted.status_code == 201, posted.text
        assert posted.json()["body"] == "Fleet, status check."


async def test_feed_rejects_a_non_exec_non_fleet_channel(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(session_factory)
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)

    async with _client(app) as client:
        get_resp = await client.get("/api/ceo/channels/general/messages", headers=headers_a)
        assert get_resp.status_code == 404
        post_resp = await client.post("/api/ceo/channels/general/messages", json={"body": "hi"}, headers=headers_a)
        assert post_resp.status_code == 404


async def test_feed_requires_admin(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    await _add_plain_member(session_factory, USER_D, ORG_S)
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        get_resp = await client.get("/api/ceo/channels/exec/messages", headers=headers_d)
        assert get_resp.status_code == 403
        post_resp = await client.post("/api/ceo/channels/exec/messages", json={"body": "hi"}, headers=headers_d)
        assert post_resp.status_code == 403


async def test_feeds_404_for_a_non_momentum_workspace_and_create_no_channels(org_world):  # noqa: F811
    """f189: the feeds are Momentum's own #exec/#fleet chatter, never a client
    workspace's -- an owner/admin outside the configured agency workspace must
    get the same 404 /api/team gives, and GET must never write Team Board
    channels into that workspace (the probed cross-tenant leak)."""
    session_factory = org_world
    # ORG_S is not the configured Momentum workspace in this app.
    app = _build_app(session_factory, config=_momentum_internal_config(slugs=["someone-elses-agency"]))
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        get_resp = await client.get("/api/ceo/channels/exec/messages", headers=headers_a)
        assert get_resp.status_code == 404, get_resp.text
        post_resp = await client.post("/api/ceo/channels/exec/messages", json={"body": "hi"}, headers=headers_a)
        assert post_resp.status_code == 404, post_resp.text

    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(session_factory)
        assert await team_repo.list_channels() == []  # the GET above created nothing


async def test_feed_refuses_an_admin_who_is_also_a_client_contact(org_world):  # noqa: F811
    """f189 suspected gap: ``_require_admin`` alone doesn't exclude an admin who
    also holds a ``client_contact`` assignment; staffing on ``is_momentum_staff``
    does (it already denies a client_contact everywhere else), so the same
    gate closes this too."""
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        acme = await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)
        assert acme.status_code == 201
        client_id = acme.json()["id"]

    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=USER_D, email=f"{USER_D}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_D, role="admin", status="active", created_at=now, updated_at=now))
        session.add(ClientAssignmentRow(client_id=client_id, user_id=USER_D, organization_id=ORG_S, role="client_contact", created_at=now, updated_at=now))
    headers_d = auth_headers(USER_D, ORG_S)

    async with _client(app) as client:
        get_resp = await client.get("/api/ceo/channels/exec/messages", headers=headers_d)
        assert get_resp.status_code == 404, get_resp.text
