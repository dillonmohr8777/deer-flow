"""Slack delivery ambiguity is held, never blindly replayed (offline only)."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock
from urllib.error import URLError

import pytest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.slack import SlackChannel


def message():
    return OutboundMessage(channel_name="slack", chat_id="C123", thread_id="thread", text="hello", thread_ts="100.1")


def channel_with_client():
    channel = SlackChannel(MessageBus(), {"reply_in_thread": False})
    channel._web_client = MagicMock()
    channel._web_client.chat_postMessage.return_value = {"ok": True, "channel": "C123", "ts": "101.2"}
    return channel


@pytest.mark.asyncio
async def test_commit_then_lost_ack_is_unknown_and_cannot_replay_same_message():
    channel = channel_with_client()
    accepted = []

    def commit_then_timeout(**kwargs):
        accepted.append(kwargs)
        raise TimeoutError("lost acknowledgment")

    channel._web_client.chat_postMessage.side_effect = commit_then_timeout
    msg = message()
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        await channel.send(msg)
    assert len(accepted) == 1
    assert msg.metadata["slack_delivery"]["state"] == "outcome_unknown"
    channel._web_client.reactions_add.assert_not_called()
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        await channel.send(msg)
    assert len(accepted) == 1


@pytest.mark.asyncio
async def test_success_preserves_provider_receipt_and_does_not_repost():
    channel = channel_with_client()
    msg = message()
    assert await channel.send(msg) is None
    assert msg.metadata["slack_delivery"] == {"state": "sent", "channel": "C123", "ts": "101.2"}
    await channel.send(msg)
    channel._web_client.chat_postMessage.assert_called_once_with(channel="C123", text="hello")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,state", [("channel_not_found", 200, "failed"), ("ratelimited", 429, "failed"), ("internal_error", 200, "outcome_unknown"), ("fatal_error", 200, "outcome_unknown"), ("server_error", 503, "outcome_unknown")]
)
async def test_provider_failure_is_not_retried(error, status, state):
    channel = channel_with_client()
    response = SlackResponse(client=None, http_verb="POST", api_url="https://slack.com/api/chat.postMessage", req_args={}, data={"ok": False, "error": error}, headers={"Retry-After": "3"}, status_code=status)
    channel._web_client.chat_postMessage.side_effect = SlackApiError("provider failure", response)
    msg = message()
    with pytest.raises(Exception):
        await channel.send(msg)
    assert msg.metadata["slack_delivery"]["state"] == state
    channel._web_client.chat_postMessage.assert_called_once()


@pytest.mark.asyncio
async def test_real_sdk_connection_retry_disabled(monkeypatch):
    channel = SlackChannel(MessageBus(), {"bot_user_id": "UBOT", "web_client_factory": WebClient})
    await channel._initialize_operator_web_client("synthetic-token")
    accepted = []

    def lose_ack(*args, **kwargs):
        accepted.append(True)
        raise URLError("connection reset after acceptance")

    monkeypatch.setattr(channel._web_client, "_perform_urllib_http_request_internal", lose_ack)
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        await channel.send(message())
    assert len(accepted) == 1
    assert channel._web_client.retry_handlers == []


@pytest.mark.asyncio
async def test_bus_holds_ambiguous_send_and_skips_attachments(caplog):
    channel = channel_with_client()
    channel._web_client.chat_postMessage.side_effect = TimeoutError()
    channel.send_file = AsyncMock()
    msg = message()
    msg.attachments = [MagicMock()]
    await channel._on_outbound(msg)
    assert msg.metadata["slack_delivery"]["state"] == "outcome_unknown"
    assert "outcome_unknown" in caplog.text
    channel.send_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_provider_receipt_is_unknown():
    channel = channel_with_client()
    channel._web_client.chat_postMessage.return_value = {"ok": True}
    msg = message()
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        await channel.send(msg)
    assert msg.metadata["slack_delivery"]["state"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_cancelled_http_wait_remains_unknown_while_worker_commits():
    channel = channel_with_client()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_post(**kwargs):
        started.set()
        try:
            assert release.wait(5)
            return {"ok": True, "channel": "C123", "ts": "101.2"}
        finally:
            finished.set()

    channel._web_client.chat_postMessage.side_effect = slow_post
    msg = message()
    task = asyncio.create_task(channel.send(msg))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert msg.metadata["slack_delivery"]["state"] == "outcome_unknown"
        with pytest.raises(RuntimeError, match="outcome_unknown"):
            await channel.send(msg)
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        await asyncio.gather(task, return_exceptions=True)
    channel._web_client.chat_postMessage.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_approval_adapter_keeps_receipt_or_explicit_unknown(monkeypatch, ambiguous):
    from app.gateway.approval_adapters import SlackAdapter

    channel = channel_with_client()
    if ambiguous:
        channel._web_client.chat_postMessage.side_effect = TimeoutError()
    service = MagicMock()
    service.get_channel.return_value = channel
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    outcome = await SlackAdapter().execute({"id": "action", "target": "C123", "payload": {"text": "hello"}})
    assert outcome.status == ("approved" if ambiguous else "executed")
    assert outcome.detail["state"] == ("outcome_unknown" if ambiguous else "sent")
    if not ambiguous:
        assert outcome.detail["ts"] == "101.2"
    channel._web_client.chat_postMessage.assert_called_once()
