"""Slack roster auto-link: roster members bind on their first message, nobody else does."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.slack import SlackChannel
from app.channels.slack_autolink import SlackRosterAutoLinker
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.config.roster_config import RosterConfig, RosterUser
from deerflow.persistence.audit_events.model import AuditEventRow
from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelConnectionRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

TEAM = "T-MOMENTUM"
AGENCY_ID = "org-agency"


class _SlackError(Exception):
    def __init__(self, error: str) -> None:
        self.response = {"error": error}


@pytest.fixture
async def env(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'autolink.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    now = datetime.now(UTC)
    async with sf() as session:
        session.add(OrganizationRow(id=AGENCY_ID, slug="momentum", name="Momentum", status="active", created_at=now, updated_at=now))
        await session.commit()
    try:
        yield sf, ChannelConnectionRepository(sf)
    finally:
        await close_engine()


def _channel(env, users: dict[str, RosterUser], *, slack_email: str | None = None, slack_error: str | None = None, team: str = TEAM):
    sf, repo = env
    linker = SlackRosterAutoLinker(repo=repo, roster=RosterConfig(users=users), workspace_id=team, organization_slugs=["momentum"], session_factory=sf)
    channel = SlackChannel(bus=MessageBus(), config={"connection_repo": repo, "roster_auto_linker": linker})
    client = MagicMock()
    if slack_error:
        client.users_info.side_effect = _SlackError(slack_error)
    else:
        client.users_info.return_value = {"user": {"profile": {"email": slack_email}}}
    channel._web_client = client
    return channel, client


def _msg(user_id: str = "U1") -> InboundMessage:
    return InboundMessage(channel_name="slack", chat_id="D1", user_id=user_id, text="hi")


async def _count(sf, model) -> int:
    async with sf() as session:
        return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.anyio
async def test_roster_member_is_linked_with_email_from_slack(env):
    sf, repo = env
    channel, _ = _channel(env, {"U1": RosterUser(role="am")}, slack_email="Ana@Example.com")

    inbound = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert inbound.connection_id and inbound.owner_user_id and inbound.workspace_id == TEAM
    async with sf() as session:
        user = (await session.execute(select(UserRow))).scalar_one()
        assert user.email == "ana@example.com" and user.system_role == "user" and user.password_hash is None
        member = await session.get(OrganizationMemberRow, {"organization_id": AGENCY_ID, "user_id": user.id})
        assert member is not None and member.role == "member" and member.status == "active"
        audit = (await session.execute(select(AuditEventRow).where(AuditEventRow.action == "channel_connection.auto_linked"))).scalar_one()
        assert audit.target_id == inbound.connection_id and audit.actor_user_id == user.id


@pytest.mark.anyio
async def test_roster_email_works_without_the_slack_scope(env):
    channel, client = _channel(env, {"U1": RosterUser(role="am", email="ana@example.com")}, slack_error="missing_scope")

    inbound = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert inbound.connection_id
    client.users_info.assert_not_called()


@pytest.mark.anyio
async def test_roster_admin_role_never_makes_an_admin_user(env):
    sf, _ = env
    channel, _ = _channel(env, {"U1": RosterUser(role="admin")}, slack_email="boss@example.com")

    await channel._attach_connection_identity(_msg(), team_id=TEAM)

    async with sf() as session:
        assert (await session.execute(select(UserRow.system_role))).scalar_one() == "user"


@pytest.mark.anyio
async def test_non_roster_sender_is_refused(env):
    sf, _ = env
    channel, client = _channel(env, {"U1": RosterUser(role="am")}, slack_email="x@example.com")

    inbound = await channel._attach_connection_identity(_msg("U-stranger"), team_id=TEAM)

    assert inbound.connection_id is None
    client.users_info.assert_not_called()
    assert await _count(sf, UserRow) == 0 and await _count(sf, ChannelConnectionRow) == 0


@pytest.mark.anyio
async def test_wrong_team_is_refused(env):
    sf, _ = env
    channel, client = _channel(env, {"U1": RosterUser(role="am")}, slack_email="x@example.com")

    inbound = await channel._attach_connection_identity(_msg(), team_id="T-OTHER")

    assert inbound.connection_id is None
    client.users_info.assert_not_called()
    assert await _count(sf, UserRow) == 0


@pytest.mark.anyio
async def test_existing_user_is_matched_by_email_case_insensitively(env):
    sf, _ = env
    from app.gateway.auth.models import User
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    existing = await SQLiteUserRepository(sf).create_user(User(email="ana@example.com", password_hash="hash", system_role="user"))
    channel, _ = _channel(env, {"U1": RosterUser(role="am")}, slack_email="ANA@EXAMPLE.COM")

    inbound = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert inbound.owner_user_id == str(existing.id)
    assert await _count(sf, UserRow) == 1
    async with sf() as session:
        # An existing account keeps its own role and password; the link only adds membership.
        row = (await session.execute(select(UserRow))).scalar_one()
        assert row.system_role == "user" and row.password_hash == "hash"
        assert await session.get(OrganizationMemberRow, {"organization_id": AGENCY_ID, "user_id": row.id}) is not None


@pytest.mark.anyio
async def test_existing_admin_account_is_never_auto_linked(env):
    sf, _ = env
    from app.gateway.auth.models import User
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    await SQLiteUserRepository(sf).create_user(User(email="boss@example.com", password_hash="hash", system_role="admin"))
    channel, _ = _channel(env, {"U1": RosterUser(role="admin")}, slack_email="boss@example.com")

    inbound = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert inbound.connection_id is None
    assert await _count(sf, ChannelConnectionRow) == 0


def test_roster_email_must_look_like_an_email():
    assert RosterUser(role="am", email=" Ana@Example.COM ").email == "ana@example.com"
    with pytest.raises(ValueError):
        RosterUser(role="am", email="not an email")


@pytest.mark.anyio
async def test_missing_email_scope_falls_back_and_asks_slack_only_once(env, caplog):
    sf, _ = env
    channel, client = _channel(env, {"U1": RosterUser(role="am")}, slack_error="missing_scope")

    with caplog.at_level("WARNING"):
        first = await channel._attach_connection_identity(_msg(), team_id=TEAM)
        second = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert first.connection_id is None and second.connection_id is None
    assert client.users_info.call_count == 1
    assert sum("users:read.email" in r.message for r in caplog.records) == 1
    assert await _count(sf, UserRow) == 0


@pytest.mark.anyio
async def test_second_message_and_concurrent_messages_link_once(env):
    sf, _ = env
    channel, client = _channel(env, {"U1": RosterUser(role="am")}, slack_email="ana@example.com")

    results = await asyncio.gather(*(channel._attach_connection_identity(_msg(), team_id=TEAM) for _ in range(5)))
    later = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert {r.connection_id for r in results} | {later.connection_id} == {later.connection_id}
    assert later.connection_id
    assert client.users_info.call_count == 1
    assert await _count(sf, UserRow) == 1 and await _count(sf, ChannelConnectionRow) == 1
    assert await _count(sf, AuditEventRow) == 1


@pytest.mark.anyio
async def test_disabled_user_is_not_linked(env):
    sf, _ = env
    from app.gateway.auth.models import User
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

    await SQLiteUserRepository(sf).create_user(User(email="ana@example.com", disabled_at=datetime.now(UTC)))
    channel, _ = _channel(env, {"U1": RosterUser(role="am")}, slack_email="ana@example.com")

    inbound = await channel._attach_connection_identity(_msg(), team_id=TEAM)

    assert inbound.connection_id is None


def test_auto_link_is_off_by_default():
    assert ChannelConnectionsConfig().slack.auto_link_roster is False
    assert RosterUser(role="am").email == ""


@pytest.mark.anyio
async def test_service_builds_the_linker_only_when_flag_and_workspace_are_set(env):
    from types import SimpleNamespace

    from app.channels.service import _make_slack_auto_linker

    _, repo = env

    def cfg(**slack):
        return SimpleNamespace(
            channel_connections=SimpleNamespace(slack=SimpleNamespace(**slack)),
            roster=RosterConfig(),
            momentum_internal=SimpleNamespace(enabled=True, organization_slugs=["momentum"]),
        )

    assert _make_slack_auto_linker(cfg(auto_link_roster=False, workspace_id=TEAM), repo) is None
    assert _make_slack_auto_linker(cfg(auto_link_roster=True, workspace_id=" "), repo) is None
    assert _make_slack_auto_linker(cfg(auto_link_roster=True, workspace_id=TEAM), None) is None
    assert _make_slack_auto_linker(cfg(auto_link_roster=True, workspace_id=TEAM), repo) is not None
