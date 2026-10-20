"""``reply_in_thread: false`` posts top-level; the default still threads."""

from unittest.mock import MagicMock

import pytest

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.slack import SlackChannel


def _channel(**config):
    ch = SlackChannel(bus=MessageBus(), config=config)
    ch._web_client = MagicMock()
    ch._get_web_client_for_message = lambda _msg: _as_awaitable(ch._web_client)
    return ch


async def _as_awaitable(value):
    return value


def _msg():
    return OutboundMessage(channel_name="slack", chat_id="C1", thread_id="t1", thread_ts="111.222", text="hi")


@pytest.mark.asyncio
async def test_default_replies_in_thread() -> None:
    ch = _channel()
    await ch.send(_msg())
    assert ch._web_client.chat_postMessage.call_args.kwargs["thread_ts"] == "111.222"


@pytest.mark.asyncio
async def test_reply_in_thread_false_posts_top_level() -> None:
    ch = _channel(reply_in_thread=False)
    await ch.send(_msg())
    assert "thread_ts" not in ch._web_client.chat_postMessage.call_args.kwargs


def test_reply_in_thread_false_skips_running_reply() -> None:
    ch = _channel(reply_in_thread=False)
    ch._send_running_reply("C1", "111.222")
    ch._web_client.chat_postMessage.assert_not_called()
