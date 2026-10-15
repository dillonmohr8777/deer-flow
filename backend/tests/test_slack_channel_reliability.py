"""Slack MomoBot reliability: long runs, failed runs, file messages and start-up."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _wait_for(condition, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def _queued(bus):
    try:
        return bus.get_inbound_nowait()
    except asyncio.QueueEmpty:
        return None


def test_run_client_has_no_read_deadline_so_long_runs_are_not_cancelled():
    from app.channels.manager import ChannelManager

    manager = ChannelManager(bus=MessageBus(), store=ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json"))
    with patch("langgraph_sdk.get_client") as get_client:
        manager._get_client()
    timeout = get_client.call_args.kwargs["timeout"]
    # runs.wait sends nothing until the run ends; a read deadline disconnects and the Gateway cancels the run.
    assert timeout.read is None
    assert timeout.connect is not None


def test_failed_run_reports_an_error_instead_of_a_stale_answer():
    from app.channels.manager import ChannelManager

    async def go():
        bus = MessageBus()
        manager = ChannelManager(bus=bus, store=ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json"))
        outbound = []

        async def capture(msg):
            outbound.append(msg)

        bus.subscribe_outbound(capture)
        client = MagicMock()
        client.threads.create = AsyncMock(return_value={"thread_id": "t1"})
        client.threads.update = AsyncMock(return_value={"thread_id": "t1"})
        client.threads.get = AsyncMock(return_value={"thread_id": "t1"})

        async def wait(*_args, on_run_created=None, **_kwargs):
            on_run_created({"run_id": "r1", "thread_id": "t1"})
            # The run failed before recording the new question, so the state still ends with the previous turn.
            return {"messages": [{"type": "human", "content": "Q1"}, {"type": "ai", "content": "A1: $1,234"}]}

        client.runs.wait = wait
        client.runs.get = AsyncMock(return_value={"run_id": "r1", "status": "error"})
        manager._client = client
        await manager.start()
        await bus.publish_inbound(InboundMessage(channel_name="test", chat_id="c1", user_id="u1", text="Q2", topic_id="t", thread_ts="m1"))
        await _wait_for(lambda: len(outbound) >= 1)
        await manager.stop()
        client.runs.get.assert_awaited_once_with("t1", "r1")
        assert "A1" not in outbound[0].text
        assert "didn't finish" in outbound[0].text

    _run(go())


class TestSlackFileMessages:
    @staticmethod
    def _channel():
        from app.channels.slack import SlackChannel

        bus = MessageBus()
        channel = SlackChannel(bus=bus, config={"allowed_users": ["U1"]})
        loop = MagicMock()
        loop.is_running.return_value = True
        loop.call_soon_threadsafe.side_effect = lambda callback, *args: callback(*args)
        channel._loop = loop
        channel._add_reaction = MagicMock()
        channel._send_running_reply = MagicMock()
        channel._web_client = MagicMock()
        return bus, channel

    def test_text_sent_with_a_file_is_answered(self):
        bus, channel = self._channel()
        channel._handle_message_event({"subtype": "file_share", "user": "U1", "text": "summarize this", "channel": "C1", "ts": "1.1", "files": [{"id": "F1"}]})
        assert _queued(bus).text == "summarize this"

    def test_thread_broadcast_is_answered(self):
        bus, channel = self._channel()
        channel._handle_message_event({"subtype": "thread_broadcast", "user": "U1", "text": "also here", "channel": "C1", "ts": "1.2", "thread_ts": "1.0"})
        assert _queued(bus).text == "also here"

    def test_file_without_text_gets_a_reply_instead_of_silence(self):
        bus, channel = self._channel()
        channel._handle_message_event({"subtype": "file_share", "user": "U1", "text": "", "channel": "C1", "ts": "1.3", "files": [{"id": "F1"}]})
        assert _queued(bus) is None
        kwargs = channel._web_client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C1" and kwargs["thread_ts"] == "1.3"
        assert "attachments" in kwargs["text"]

    def test_bot_and_edit_events_stay_ignored(self):
        bus, channel = self._channel()
        channel._handle_message_event({"subtype": "file_share", "bot_id": "B1", "user": "U_OTHER_BOT", "text": "x", "channel": "C1", "ts": "1.4"})
        channel._handle_message_event({"subtype": "message_changed", "user": "U1", "text": "x", "channel": "C1", "ts": "1.5"})
        assert _queued(bus) is None
        channel._web_client.chat_postMessage.assert_not_called()


def test_failed_socket_connect_leaves_the_channel_not_running():
    from app.channels.slack import SlackChannel

    socket_client = MagicMock()
    socket_client.connect.side_effect = ConnectionError("slack unreachable")
    channel = SlackChannel(bus=MessageBus(), config={"bot_token": "xoxb-synthetic", "app_token": "xapp-synthetic"})
    channel._initialize_operator_web_client = AsyncMock()
    with patch("slack_sdk.socket_mode.SocketModeClient", return_value=socket_client):
        _run(channel.start())
    assert channel._running is False
    assert channel._socket_client is None
    socket_client.close.assert_called_once()
