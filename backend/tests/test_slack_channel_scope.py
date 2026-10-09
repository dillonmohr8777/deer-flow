"""Workspace/chat policy admission and persona isolation, without Slack calls."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.slack import SlackChannel
from app.channels.store import ChannelStore

TEAM = "TNEWS"
CHAT = "CNEWS"


@pytest.fixture(autouse=True)
def authenticated_gateway(monkeypatch):
    monkeypatch.setattr("app.gateway.auth_disabled.is_auth_disabled", lambda: False)


def channel():
    return SlackChannel(
        bus=MessageBus(),
        config={
            "allowed_users": ["UOWNER"],
            "connection_repo": MagicMock(),
            "bot_user_id": "UBOT",
            "channel_policies": {
                f"{TEAM}:{CHAT}": {
                    "allow_all_users": True,
                    "mentions_and_threads_only": True,
                }
            },
        },
    )


@pytest.mark.parametrize(
    "team,chat,kind,text,expected",
    [
        (TEAM, CHAT, "app_mention", "<@UBOT> hi", True),
        ("TOTHER", CHAT, "app_mention", "<@UBOT> hi", False),
        (TEAM, "COTHER", "app_mention", "<@UBOT> hi", False),
        (TEAM, CHAT, "message", "random news", False),
        (TEAM, CHAT, "app_mention", "<@UBOT> /agent use private-agent", False),
        (TEAM, CHAT, "app_mention", "<@UBOT> /goal do something", False),
    ],
)
def test_scoped_admission(team, chat, kind, text, expected):
    adapter = channel()
    adapter._make_inbound = MagicMock(wraps=adapter._make_inbound)
    adapter._handle_message_event({"type": kind, "channel": chat, "user": "UMEMBER", "text": text, "ts": "1"}, team_id=team)
    assert adapter._make_inbound.called is expected


def test_global_owner_and_empty_allowlist_defaults_unchanged():
    for config, user in [({"allowed_users": ["UOWNER"]}, "UOWNER"), ({}, "UMEMBER")]:
        adapter = SlackChannel(bus=MessageBus(), config=config)
        adapter._make_inbound = MagicMock(wraps=adapter._make_inbound)
        adapter._handle_message_event({"type": "message", "channel": "COTHER", "user": user, "text": "hi", "ts": "1"}, team_id=TEAM)
        assert adapter._make_inbound.called


def test_only_engaged_threads_follow_up():
    async def go():
        adapter = channel()
        adapter._loop = asyncio.get_running_loop()
        adapter._reserve_inbound = MagicMock(return_value=MagicMock())
        adapter._commit_reserved_inbound = MagicMock()
        adapter._add_reaction = MagicMock()
        adapter._send_running_reply = MagicMock()
        queued = []

        def submit(coro, *_args, **_kwargs):
            queued.append(coro)
            return True

        adapter._submit_threadsafe_coroutine = submit

        async def attach(msg, **_kwargs):
            msg.connection_id = "connection"
            msg.owner_user_id = "member-owner"
            msg.workspace_id = TEAM
            return msg

        adapter._attach_connection_identity = attach

        def event(ts, thread=None, kind="message"):
            return {"type": kind, "channel": CHAT, "user": "UMEMBER", "text": "hi", "ts": ts, "thread_ts": thread}

        adapter._handle_message_event(event("1", kind="app_mention"), team_id=TEAM)
        assert not adapter._engaged_threads
        await queued.pop(0)
        adapter._handle_message_event(event("2", "1"), team_id=TEAM)
        adapter._handle_message_event(event("3", "unrelated"), team_id=TEAM)
        adapter._handle_message_event(event("4", "1"), team_id="TOTHER")
        assert adapter._reserve_inbound.call_count == 2
        for pending in queued:
            await pending

    asyncio.run(go())


@pytest.mark.parametrize("team,chat,expected", [(TEAM, CHAT, "news-persona"), ("TOTHER", CHAT, "lead_agent"), (TEAM, "COTHER", "lead_agent"), (None, CHAT, "lead_agent")])
def test_persona_scoped_and_model_defaults_preserved(tmp_path, team, chat, expected):
    manager = ChannelManager(
        bus=MessageBus(),
        store=ChannelStore(path=tmp_path / "store.json"),
        channel_sessions={
            "slack": {"context": {"model_name": "worker-client"}, "chats": {f"{TEAM}:{CHAT}": {"assistant_id": "news-persona"}}},
        },
    )
    msg = InboundMessage(channel_name="slack", chat_id=chat, user_id="UMEMBER", text="hi", metadata={"team_id": team})
    assistant, _, context = manager._resolve_run_params(msg, "thread")
    assert assistant == "lead_agent"
    assert context.get("agent_name", "lead_agent") == expected
    assert context["model_name"] == "worker-client"
    assert manager._channel_sessions["slack"].get("assistant_id") is None


@pytest.mark.parametrize("auth_disabled,has_repo", [(True, True), (False, False)])
def test_public_members_never_inherit_operator_identity(monkeypatch, auth_disabled, has_repo):
    monkeypatch.setattr("app.gateway.auth_disabled.is_auth_disabled", lambda: auth_disabled)
    adapter = channel()
    if not has_repo:
        adapter._connection_repo = None
    adapter._make_inbound = MagicMock(wraps=adapter._make_inbound)
    adapter._handle_message_event({"type": "app_mention", "channel": CHAT, "user": "UMEMBER", "text": "<@UBOT> hi", "ts": "1"}, team_id=TEAM)
    assert not adapter._make_inbound.called


@pytest.mark.parametrize("bound", [False, True])
def test_expanded_member_requires_own_binding_before_dispatch(bound):
    async def go():
        adapter = channel()
        msg = InboundMessage(channel_name="slack", chat_id=CHAT, user_id="UMEMBER", text="hi", thread_ts="1", metadata={"requires_personal_connection": True, "team_id": TEAM, "message_id": "2"})
        if bound:
            msg.connection_id = "personal-connection"
            msg.owner_user_id = "personal-owner"
            msg.workspace_id = TEAM
        adapter._attach_connection_identity = AsyncMock(return_value=msg)
        adapter._commit_reserved_inbound = MagicMock()
        adapter._add_reaction = MagicMock()
        adapter._send_running_reply = MagicMock()
        reservation = MagicMock()
        await adapter._publish_inbound_with_connection(msg, reservation=reservation, team_id=TEAM)
        assert adapter._commit_reserved_inbound.called is bound
        assert adapter._add_reaction.called is bound
        assert adapter._send_running_reply.called is bound
        assert bool(adapter._engaged_threads) is bound
        reservation.release.assert_called_once()

    asyncio.run(go())


@pytest.mark.parametrize("policies", [None, [], "bad", {f"{TEAM}:{CHAT}": None}, {f"{TEAM}:{CHAT}": "bad"}, {f"{TEAM}:{CHAT}": {"allow_all_users": "true"}}])
def test_malformed_policy_does_not_expand_access(policies):
    adapter = channel()
    adapter._channel_policies = policies
    adapter._make_inbound = MagicMock(wraps=adapter._make_inbound)
    adapter._handle_message_event({"type": "app_mention", "channel": CHAT, "user": "UMEMBER", "text": "hi", "ts": "1"}, team_id=TEAM)
    assert not adapter._make_inbound.called


def test_public_news_route_overrides_user_and_thread_agent_choices(tmp_path):
    manager = ChannelManager(
        bus=MessageBus(),
        store=ChannelStore(path=tmp_path / "store.json"),
        channel_sessions={"slack": {"users": {"UMEMBER": {"assistant_id": "private-agent", "context": {"public_news_channel": True, "is_bootstrap": True, "subagent_enabled": True}}}}},
    )
    manager._thread_agent_names["thread"] = "private-agent"
    msg = InboundMessage(channel_name="slack", chat_id="C04HXSVN2CS", user_id="UMEMBER", text="hi", metadata={"team_id": "T066HGS7N"})
    assistant, _, context = manager._resolve_run_params(msg, "thread")
    assert assistant == "lead_agent"
    assert context["agent_name"] == "ai-tech-news"
    assert context["public_news_channel"] is True
    assert context["is_bootstrap"] is False
    assert context["subagent_enabled"] is False
    msg.chat_id = "OTHER"
    assert manager._resolve_run_params(msg, "thread")[2]["public_news_channel"] is False
