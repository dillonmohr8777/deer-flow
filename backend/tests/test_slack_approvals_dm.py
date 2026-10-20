"""Slack approvals DM: message building, permission check, action routing, config-off no-op."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.channels import slack_approvals as sa
from app.channels.message_bus import MessageBus
from app.channels.slack import SlackChannel
from deerflow.approvals import notify_created, register_created_hook, unregister_created_hook

CFG = sa.parse_config({"enabled": True, "user_ids": ["U1"], "base_url": "https://momo.example/"})


def _row(**kw):
    row = {
        "id": "abc123",
        "action_type": "email",
        "title": "Weekly update",
        "target": "client@example.com",
        "payload": {"subject": "Hi", "body": "x" * 900, "loop": {"client": "Omega Landscape"}},
        "status": "pending",
        "agent_name": None,
        "user_id": "owner",
    }
    row.update(kw)
    return row


class FakeStore:
    def __init__(self, row=None, decided=None):
        self.row, self.decided, self.calls = row, decided, []

    async def get(self, action_id):
        return self.row

    async def decide(self, row, *, approve, decided_by):
        self.calls.append((approve, decided_by))
        return self.decided


def _action(verb, user="U1"):
    return sa.ParsedAction(verb=verb, item_id="abc123", user_id=user, channel="D1", message_ts="1.2", blocks=[])


def test_build_message_truncates_links_and_has_three_buttons():
    text, blocks = sa.build_message(_row(), CFG)
    assert "Omega Landscape" in text and "email" in text
    body = blocks[1]["text"]["text"]
    assert body.endswith("...") and len(body) < sa.SUMMARY_CHARS + 120
    assert "https://momo.example/workspace/approvals?id=abc123" in blocks[2]["elements"][0]["text"]
    buttons = blocks[3]["elements"]
    assert [b["action_id"] for b in buttons] == ["momo_approval_approve", "momo_approval_edit", "momo_approval_skip"]
    assert {b["value"] for b in buttons} == {"abc123"}


def test_build_message_scrubs_secrets_and_escapes():
    row = _row(action_type="slack_message", payload={"text": "token=xoxb-123-abc <!channel> & key sk-abcdefgh12345"})
    _, blocks = sa.build_message(row, CFG)
    body = blocks[1]["text"]["text"]
    assert "xoxb" not in body and "sk-abcdefgh" not in body
    assert "<!channel>" not in body and "&lt;!channel&gt;" in body
    assert "AI" not in blocks[2]["elements"][0]["text"]  # no footer text


def test_config_defaults_off():
    assert sa.parse_config(None).enabled is False
    assert sa.parse_config({"enabled": False, "user_ids": ["U1"]}).enabled is False
    assert sa.parse_config({"enabled": True, "user_ids": []}).enabled is False
    assert sa.parse_config({"enabled": True, "user_ids": "U1"}).user_ids == {"U1"}


def test_permission_check():
    assert sa.is_allowed(CFG, "U1")
    assert not sa.is_allowed(CFG, "U2")
    assert not sa.is_allowed(CFG, "")
    assert not sa.is_allowed(sa.parse_config(None), "U1")


def test_parse_block_action():
    payload = {
        "type": "block_actions",
        "user": {"id": "U1"},
        "channel": {"id": "D1"},
        "message": {"ts": "1.2", "blocks": [{"type": "section"}]},
        "actions": [{"action_id": "momo_approval_skip", "value": "abc123"}],
    }
    parsed = sa.parse_block_action(payload)
    assert (parsed.verb, parsed.item_id, parsed.user_id, parsed.channel) == ("skip", "abc123", "U1", "D1")
    assert sa.parse_block_action({**payload, "actions": [{"action_id": "other", "value": "x"}]}) is None
    assert sa.parse_block_action({"type": "view_submission"}) is None


def test_unauthorized_user_denied_and_store_untouched():
    store = FakeStore(row=_row(), decided=_row(status="approved"))
    result = asyncio.run(sa.route_action(_action("approve", user="U2"), CFG, store))
    assert result.kind == "denied" and "Not allowed" in result.text
    assert store.calls == []


def test_approve_email_keeps_draft_and_skip_rejects():
    store = FakeStore(row=_row(), decided=_row(status="approved", execution_result={"state": "ready_to_send"}))
    result = asyncio.run(sa.route_action(_action("approve"), CFG, store))
    assert result.kind == "approved" and "nothing sent" in result.text
    assert store.calls == [(True, "slack:U1")]

    store = FakeStore(row=_row(), decided=_row(status="rejected"))
    result = asyncio.run(sa.route_action(_action("skip"), CFG, store))
    assert result.kind == "skipped" and store.calls == [(False, "slack:U1")]


def test_edit_links_without_deciding_and_stale_and_missing():
    store = FakeStore(row=_row())
    result = asyncio.run(sa.route_action(_action("edit"), CFG, store))
    assert result.kind == "edit" and "approvals?id=abc123" in result.text and store.calls == []
    assert asyncio.run(sa.route_action(_action("skip"), CFG, FakeStore(row=_row(), decided=None))).kind == "stale"
    assert asyncio.run(sa.route_action(_action("skip"), CFG, FakeStore(row=None))).kind == "missing"


def test_off_by_default_registers_no_hook_and_ignores_interactive():
    channel = SlackChannel(bus=MessageBus(), config={"bot_token": "xoxb-a", "app_token": "xapp-a"})
    assert channel._approvals_dm.enabled is False
    channel._web_client = MagicMock()
    asyncio.run(channel._notify_approval(_row()))
    channel._web_client.conversations_open.assert_not_called()
    channel._web_client.chat_postMessage.assert_not_called()


def test_notify_posts_dm_to_each_user_when_enabled():
    cfg = {"bot_token": "xoxb-a", "app_token": "xapp-a", "approvals_dm": {"enabled": True, "user_ids": ["U1"]}}
    channel = SlackChannel(bus=MessageBus(), config=cfg)
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D9"}}
    channel._web_client = client
    asyncio.run(channel._notify_approval(_row()))
    client.conversations_open.assert_called_once_with(users="U1")
    kwargs = client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "D9" and kwargs["blocks"][3]["type"] == "actions"
    asyncio.run(channel._notify_approval(_row(status="approved")))
    assert client.chat_postMessage.call_count == 1


def test_created_hook_failure_never_blocks():
    seen = []

    def boom(row):
        raise RuntimeError("slack down")

    def ok(row):
        seen.append(row["id"])

    register_created_hook(boom)
    register_created_hook(ok)
    try:
        asyncio.run(notify_created({"id": "r1"}))
    finally:
        unregister_created_hook(boom)
        unregister_created_hook(ok)
    assert seen == ["r1"]


def test_interactive_event_routes_only_when_enabled():
    cfg = {"bot_token": "xoxb-a", "app_token": "xapp-a", "approvals_dm": {"enabled": True, "user_ids": ["U1"]}}
    channel = SlackChannel(bus=MessageBus(), config=cfg)
    channel._running = True
    channel._SocketModeResponse = lambda envelope_id: envelope_id
    channel._handle_interactive = MagicMock()
    req = SimpleNamespace(type="interactive", envelope_id="e1", payload={"type": "block_actions"})
    channel._on_socket_event(MagicMock(), req)
    channel._handle_interactive.assert_called_once()

    off = SlackChannel(bus=MessageBus(), config={"bot_token": "xoxb-a", "app_token": "xapp-a"})
    off._running = True
    off._SocketModeResponse = lambda envelope_id: envelope_id
    off._handle_interactive = MagicMock()
    off._on_socket_event(MagicMock(), req)
    off._handle_interactive.assert_not_called()
