"""Offline Socket Mode adapter checks: persist-before-ACK and bounded dispatch."""

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import markdown_to_mrkdwn  # noqa: F401
except ImportError:
    converter = ModuleType("markdown_to_mrkdwn")
    converter.SlackMarkdownConverter = lambda: SimpleNamespace(convert=lambda text: text)
    with patch.dict(sys.modules, {"markdown_to_mrkdwn": converter}):
        slack = importlib.import_module("app.channels.slack")
else:
    slack = importlib.import_module("app.channels.slack")

from app.channels.message_bus import MessageBus


class BrainForgeSlackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.channel = slack.SlackChannel(MessageBus(), {})
        self.channel._loop = asyncio.get_running_loop()
        self.channel._running = True
        self.channel._SocketModeResponse = lambda **kwargs: kwargs
        self.channel._brainforge = SimpleNamespace(
            matches=Mock(return_value=True),
            prepare=Mock(return_value=SimpleNamespace(message_ts="100.001")),
            recover=AsyncMock(return_value=0),
            recovery_has_more=False,
            next_recovery_delay=AsyncMock(return_value=None),
            close=AsyncMock(),
        )
        self.submissions = []

        def submit(coroutine, *args, **kwargs):
            self.submissions.append((coroutine, kwargs))
            return True

        self.channel._submit_threadsafe_coroutine = submit
        self.addCleanup(self.close_submissions)

    def close_submissions(self):
        if self.channel._brainforge_recovery_timer:
            self.channel._brainforge_recovery_timer.cancel()
        for coroutine, _ in self.submissions:
            coroutine.close()

    def request(self):
        return SimpleNamespace(type="events_api", envelope_id="synthetic-envelope", payload={"team_id": "T123", "event": {"type": "app_mention"}})

    async def test_admission_is_durable_before_ack(self):
        observed = []
        self.channel._brainforge.prepare.side_effect = lambda *args, **kwargs: observed.append("persist") or SimpleNamespace(message_ts="100.001")
        client = SimpleNamespace(send_socket_mode_response=lambda response: observed.append("ack"))
        self.channel._on_socket_event(client, self.request())
        self.assertEqual(observed, ["persist", "ack"])
        self.assertEqual(len(self.submissions), 1)

    async def test_rejected_event_never_dispatches(self):
        self.channel._brainforge.prepare.return_value = None
        legacy = Mock()
        self.channel._handle_message_event = legacy
        client = SimpleNamespace(send_socket_mode_response=Mock())
        self.channel._on_socket_event(client, self.request())
        client.send_socket_mode_response.assert_called_once()
        legacy.assert_not_called()
        self.assertEqual(self.submissions, [])

    async def test_non_brief_event_is_dropped_in_exclusive_mode(self):
        self.channel._brainforge.matches.return_value = False
        legacy = Mock()
        self.channel._handle_message_event = legacy
        client = SimpleNamespace(send_socket_mode_response=Mock())
        self.channel._on_socket_event(client, self.request())
        client.send_socket_mode_response.assert_called_once()
        legacy.assert_not_called()
        self.channel._brainforge.prepare.assert_not_called()

    async def test_agent_passthrough_sends_only_non_brief_events_to_agent(self):
        self.channel._brainforge_config = {"agent_passthrough": True}
        legacy = Mock()
        self.channel._handle_message_event = legacy
        client = SimpleNamespace(send_socket_mode_response=Mock())
        self.channel._on_socket_event(client, self.request())
        legacy.assert_not_called()
        self.assertEqual(len(self.submissions), 1)
        self.channel._brainforge.matches.return_value = False
        self.channel._on_socket_event(client, self.request())
        legacy.assert_called_once()
        self.assertEqual(client.send_socket_mode_response.call_count, 2)
        self.assertEqual(self.channel._brainforge.prepare.call_count, 1)

    async def test_passthrough_start_subscribes_outbound_for_agent_replies(self):
        for passthrough, expected in ((False, 0), (True, 1)):
            channel = slack.SlackChannel(MessageBus(), {"bot_token": "xoxb-synthetic", "app_token": "xapp-synthetic", "brain_forge": {"enabled": True, "agent_passthrough": passthrough}})
            runtime = SimpleNamespace(validate_transport=AsyncMock(), close=AsyncMock())
            socket = SimpleNamespace(socket_mode_request_listeners=[], connect=Mock(), close=Mock())
            with (
                patch.object(slack, "BrainForgeRuntime", return_value=runtime),
                patch("slack_sdk.socket_mode.SocketModeClient", return_value=socket),
                patch.object(channel, "_initialize_operator_web_client", AsyncMock()),
                patch.object(channel, "_wake_brainforge"),
                patch.object(channel.bus, "subscribe_outbound") as subscribe,
            ):
                await channel.start()
            self.assertEqual(subscribe.call_count, expected)

    async def test_sdk_burst_schedules_one_drain(self):
        client = SimpleNamespace(send_socket_mode_response=Mock())
        for _ in range(1000):
            self.channel._on_socket_event(client, self.request())
        self.assertEqual(self.channel._brainforge.prepare.call_count, 1000)
        self.assertEqual(client.send_socket_mode_response.call_count, 1000)
        self.assertEqual(len(self.submissions), 1)

    async def test_wakeup_while_draining_is_not_lost(self):
        self.channel._wake_brainforge()
        token = self.channel._brainforge_drain_token
        calls = 0

        async def recover():
            nonlocal calls
            calls += 1
            if calls == 1:
                self.channel._wake_brainforge()
            return 0

        self.channel._brainforge.recover = recover
        await self.channel._drain_brainforge(token)
        self.assertEqual(calls, 2)
        self.assertEqual(len(self.submissions), 1)
        self.assertIsNone(self.channel._brainforge_drain_token)

    async def test_full_page_continues_without_task_fanout(self):
        self.channel._wake_brainforge()
        pages = iter([True, False])

        async def recover():
            self.channel._brainforge.recovery_has_more = next(pages)
            # Full pages can be entirely held; processed count must not stop scanning.
            return 0

        self.channel._brainforge.recover = AsyncMock(side_effect=recover)
        await self.channel._drain_brainforge(self.channel._brainforge_drain_token)
        self.assertEqual(self.channel._brainforge.recover.await_count, 2)
        self.assertEqual(len(self.submissions), 1)

    async def test_live_claim_schedules_one_expiry_wakeup_without_an_inbound_event(self):
        self.channel._brainforge.next_recovery_delay.return_value = 200
        self.channel._wake_brainforge()
        loop = asyncio.get_running_loop()
        handle = Mock()
        with patch.object(loop, "call_later", return_value=handle) as later:
            await self.channel._drain_brainforge(self.channel._brainforge_drain_token)
        later.assert_called_once_with(200, self.channel._retry_brainforge_lease)
        self.assertIs(self.channel._brainforge_recovery_timer, handle)
        later.call_args.args[1]()
        self.assertIsNone(self.channel._brainforge_recovery_timer)
        self.assertEqual(len(self.submissions), 2)
        self.channel._brainforge.next_recovery_delay.return_value = None
        await self.channel._drain_brainforge(self.channel._brainforge_drain_token)
        self.assertIsNone(self.channel._brainforge_recovery_timer)

    async def test_stop_cancels_expiry_wakeup_and_late_callback_cannot_dispatch(self):
        timer = Mock()
        self.channel._brainforge_recovery_timer = timer
        await self.channel.stop()
        timer.cancel.assert_called_once()
        self.channel._retry_brainforge_lease()
        self.assertEqual(self.submissions, [])
        self.assertIsNone(self.channel._brainforge_recovery_timer)

    async def test_drain_exception_releases_worker_fence(self):
        self.channel._wake_brainforge()
        self.channel._brainforge.recover = AsyncMock(side_effect=RuntimeError("synthetic failure"))
        with self.assertRaises(RuntimeError):
            await self.channel._drain_brainforge(self.channel._brainforge_drain_token)
        self.assertIsNone(self.channel._brainforge_drain_token)

    async def test_failed_submission_preserves_retryable_worker_state(self):
        def fail_submit(coroutine, *args, **kwargs):
            coroutine.close()
            return False

        self.channel._submit_threadsafe_coroutine = fail_submit
        self.channel._wake_brainforge()
        self.assertIsNone(self.channel._brainforge_drain_token)
        self.assertTrue(self.channel._brainforge_drain_wakeup)


if __name__ == "__main__":
    unittest.main()
