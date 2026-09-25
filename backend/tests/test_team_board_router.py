"""Momentum team board: staff-only channels behind ``require_momentum_staff``.

Drives the real ``team_board`` router behind the real ``AuthMiddleware`` in
the shared ``org_world``. The rule under test: only staff (owner, admin,
member) on Momentum's private instance can see or use any route, and every
other caller (a ``client`` role, another organization, or any caller on a
client-facing instance) gets a 404 that reveals nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.deps import get_config
from app.gateway.routers import team_board
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.organizations.identity import private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.team_board import DEFAULT_TEAM_CHANNELS, TeamBoardRepository
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

USER_MEMBER = "user-member"
USER_CLIENT = "user-client"
# The shared workspace S plays "Momentum"; every private workspace plays a client.
MOMENTUM_SLUG = private_organization_slug(STORAGE_S)


def _config(*, enabled: bool = True, slugs: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(momentum_internal=SimpleNamespace(enabled=enabled, organization_slugs=[MOMENTUM_SLUG] if slugs is None else slugs))


def _build_app(session_factory, *, config: SimpleNamespace | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.team_board_repo = TeamBoardRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(team_board.router)
    resolved = config or _config()
    app.dependency_overrides[get_config] = lambda: resolved
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _add_member(session_factory, user_id: str, role: str) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=user_id, role=role, status="active", created_at=now, updated_at=now))


async def test_staff_get_default_channels_and_can_talk(org_world):  # noqa: F811
    await _add_member(org_world, USER_MEMBER, "member")
    app = _build_app(org_world)
    owner, member = auth_headers(USER_A, ORG_S), auth_headers(USER_MEMBER, ORG_S)

    async with _client(app) as client:
        listing = await client.get("/api/team/channels", headers=member)
        assert listing.status_code == 200, listing.text
        channels = listing.json()["channels"]
        assert [c["slug"] for c in channels] == [slug for slug, _, _ in DEFAULT_TEAM_CHANNELS]
        # Seeding is idempotent: a second call doesn't duplicate anything.
        again = (await client.get("/api/team/channels", headers=owner)).json()["channels"]
        assert [c["id"] for c in again] == [c["id"] for c in channels]

        general = channels[0]["id"]
        posted = await client.post(
            f"/api/team/channels/{general}/messages",
            # A forged author field is ignored: the author is always the caller.
            json={"body": "  Morning team  ", "author_user_id": USER_A},
            headers=member,
        )
        assert posted.status_code == 201, posted.text
        assert posted.json()["author_user_id"] == USER_MEMBER
        assert posted.json()["body"] == "Morning team"
        await client.post(f"/api/team/channels/{general}/messages", json={"body": "Morning"}, headers=owner)

        messages = await client.get(f"/api/team/channels/{general}/messages", headers=owner)
        assert messages.status_code == 200
        assert [(m["author_user_id"], m["body"]) for m in messages.json()["messages"]] == [(USER_MEMBER, "Morning team"), (USER_A, "Morning")]

        latest = await client.get(f"/api/team/channels/{general}/messages", params={"limit": 1}, headers=owner)
        assert [m["body"] for m in latest.json()["messages"]] == ["Morning"]

        blank = await client.post(f"/api/team/channels/{general}/messages", json={"body": "   "}, headers=owner)
        assert blank.status_code == 422
        assert (await client.get("/api/team/channels/nope/messages", headers=owner)).status_code == 404
        assert (await client.post("/api/team/channels/nope/messages", json={"body": "x"}, headers=owner)).status_code == 404


async def test_only_owner_or_admin_adds_channels(org_world):  # noqa: F811
    await _add_member(org_world, USER_MEMBER, "member")
    app = _build_app(org_world)
    audit_repo = app.state.audit_repo

    async with _client(app) as client:
        denied = await client.post("/api/team/channels", json={"name": "Design"}, headers=auth_headers(USER_MEMBER, ORG_S))
        assert denied.status_code == 403

        created = await client.post("/api/team/channels", json={"name": "Client Wins!", "topic": "Shout-outs"}, headers=auth_headers(USER_C, ORG_S))
        assert created.status_code == 201, created.text
        assert created.json()["slug"] == "client-wins"
        assert created.json()["topic"] == "Shout-outs"

        duplicate = await client.post("/api/team/channels", json={"name": "client wins"}, headers=auth_headers(USER_A, ORG_S))
        assert duplicate.status_code == 409
        nameless = await client.post("/api/team/channels", json={"name": "!!!"}, headers=auth_headers(USER_A, ORG_S))
        assert nameless.status_code == 422

    events, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="team.channel.")
    outcomes = {(e["action"], e["outcome"]) for e in events}
    assert outcomes == {("team.channel.create", "denied"), ("team.channel.create", "success")}


async def test_client_role_sees_nothing(org_world):  # noqa: F811
    await _add_member(org_world, USER_CLIENT, "client")
    app = _build_app(org_world)
    staff, client_headers = auth_headers(USER_A, ORG_S), auth_headers(USER_CLIENT, ORG_S)

    async with _client(app) as client:
        channel_id = (await client.get("/api/team/channels", headers=staff)).json()["channels"][0]["id"]
        await client.post(f"/api/team/channels/{channel_id}/messages", json={"body": "internal only"}, headers=staff)

        assert (await client.get("/api/team/channels", headers=client_headers)).status_code == 404
        assert (await client.get("/api/team/members", headers=client_headers)).status_code == 404
        assert (await client.get(f"/api/team/channels/{channel_id}/messages", headers=client_headers)).status_code == 404
        assert (await client.post(f"/api/team/channels/{channel_id}/messages", json={"body": "hi"}, headers=client_headers)).status_code == 404
        assert (await client.post("/api/team/channels", json={"name": "mine"}, headers=client_headers)).status_code == 404

        # And the client never shows up in the staff directory.
        members = (await client.get("/api/team/members", headers=staff)).json()["members"]
        assert USER_CLIENT not in {m["user_id"] for m in members}
        assert {m["user_id"]: m["role"] for m in members} == {USER_A: "owner", USER_C: "admin"}


async def test_client_workspace_owner_on_the_same_instance_sees_nothing(org_world):  # noqa: F811
    """B owns their own workspace on this instance, like a client would: still 404."""
    app = _build_app(org_world)
    async with _client(app) as client:
        channel_id = (await client.get("/api/team/channels", headers=auth_headers(USER_A, ORG_S))).json()["channels"][0]["id"]
        client_owner = auth_headers(USER_B)
        assert (await client.get("/api/team/channels", headers=client_owner)).status_code == 404
        assert (await client.get("/api/team/members", headers=client_owner)).status_code == 404
        assert (await client.post("/api/team/channels", json={"name": "x"}, headers=client_owner)).status_code == 404
        assert (await client.get(f"/api/team/channels/{channel_id}/messages", headers=client_owner)).status_code == 404
        assert (await client.post(f"/api/team/channels/{channel_id}/messages", json={"body": "x"}, headers=client_owner)).status_code == 404


@pytest.mark.parametrize("config", [_config(enabled=False), _config(slugs=[]), _config(slugs=["some-other-agency"])], ids=["disabled", "no-slugs", "other-slug"])
async def test_team_board_is_off_unless_this_workspace_is_configured(org_world, config):  # noqa: F811
    app = _build_app(org_world, config=config)
    owner = auth_headers(USER_A, ORG_S)
    async with _client(app) as client:
        assert (await client.get("/api/team/channels", headers=owner)).status_code == 404
        assert (await client.get("/api/team/members", headers=owner)).status_code == 404
        assert (await client.post("/api/team/channels", json={"name": "x"}, headers=owner)).status_code == 404
        assert (await client.get("/api/team/channels/any/messages", headers=owner)).status_code == 404
