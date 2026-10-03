"""Synthetic controller checks using its real admission, hydration and SQLite.

No Slack SDK, live transport, model or canonical source is used. Workflow
execution has its separate pinned-source suite; these tests fake that boundary.
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.channels.brainforge_runtime import BrainForgeRuntime


def request(**changes):
    return {"type": "app_mention", "user": "U123", "channel": "C123", "ts": "100.000002", "text": "<@U999> /forge brief", **changes}


class FakeClient:
    def __init__(self, event=None):
        self.event = event or request()
        self.auth_calls = 0
        self.read_calls = []
        self.send_calls = []
        self.page = None
        self.send_error = None
        self.retry_handlers = ["synthetic_retry_handler"]

    def auth_test(self):
        self.auth_calls += 1
        return {"ok": True, "team_id": "T123", "user_id": "U999"}

    def conversations_replies(self, **kwargs):
        self.read_calls.append(kwargs)
        if self.page is not None:
            return copy.deepcopy(self.page)
        event = self.event
        return {"ok": True, "messages": [{"ts": event["ts"], "user": event["user"], "text": event["text"], "thread_ts": event.get("thread_ts") or event["ts"]}]}

    def chat_postMessage(self, **kwargs):
        self.send_calls.append(kwargs)
        if self.send_error:
            raise self.send_error
        return {"ok": True, "ts": "101.000001"}


class FakeChannel:
    def __init__(self, client, *, repo=None, binding_owner="momo-owner", binding_workspace="T123"):
        self._web_client = client
        self._connection_repo = repo
        self.binding_owner = binding_owner
        self.binding_workspace = binding_workspace
        self.factory_calls = []
        self.bound_client = FakeClient(client.event)

    def _web_client_factory(self, **kwargs):
        self.factory_calls.append(kwargs)
        return self.bound_client

    def _make_inbound(self, **kwargs):
        return SimpleNamespace(**kwargs, connection_id=None, workspace_id=None, owner_user_id=None)

    async def _attach_connection_identity(self, inbound, **kwargs):
        inbound.connection_id = "synthetic-connection"
        inbound.owner_user_id = self.binding_owner
        inbound.workspace_id = self.binding_workspace
        return inbound


class FakeWorkflow:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text="Synthetic verified count projection")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.channel = FakeChannel(self.client)
        self.workflow = FakeWorkflow()
        self.runtimes = []

    async def asyncTearDown(self):
        for runtime in self.runtimes:
            await runtime.close()
        self.temp.cleanup()

    def make_runtime(self, channel=None, **changes):
        config = {
            "team_id": "T123",
            "bot_user_id": "U999",
            "allowed_users": ["U123"],
            "channel_clients": {"C123": "synthetic-client"},
            "owner_user_id": "U123",
            "require_connection": False,
            "ledger_path": str(Path(self.temp.name) / "receipts.sqlite"),
            "workflow": {},
            **changes,
        }
        with patch("app.channels.brainforge_runtime.BrainForgeBriefWorkflow", return_value=self.workflow):
            runtime = BrainForgeRuntime(channel or self.channel, config)
        self.runtimes.append(runtime)
        return runtime

    async def test_disallowed_events_cause_no_provider_or_workflow_io(self):
        runtime = self.make_runtime()
        for changes, team in [({}, "TOTHER"), ({"user": "UOTHER"}, "T123"), ({"channel": "COTHER"}, "T123"), ({"text": "ordinary discussion", "type": "message"}, "T123")]:
            self.assertIsNone(runtime.prepare(request(**changes), team_id=team))
        self.assertEqual(self.client.auth_calls, 0)
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(self.workflow.calls, [])
        self.assertEqual(runtime.ledger.pending(), [])

    async def test_aggregate_route_is_reserved_to_exact_slack_owner(self):
        runtime = self.make_runtime(allowed_users=["U123", "UOTHER"], channel_clients={"C123": "__owner__"})
        self.assertIsNone(runtime.prepare(request(user="UOTHER"), team_id="T123"))
        self.assertIsNotNone(runtime.prepare(request(), team_id="T123"))
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.workflow.calls, [])

    async def test_wrong_backend_owner_is_rejected_without_operator_fallback(self):
        repo = SimpleNamespace(get_credentials=AsyncMock(return_value={"access_token": "SYNTHETIC_BINDING_TOKEN"}))
        channel = FakeChannel(self.client, repo=repo, binding_owner="wrong-owner")
        runtime = self.make_runtime(channel, require_connection=True, connection_owner_id="momo-owner")
        admitted = runtime.prepare(request(), team_id="T123")
        await runtime.run(admitted)
        repo.get_credentials.assert_not_awaited()
        self.assertEqual(channel.factory_calls, [])
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(runtime.ledger.get("T123", "C123", "100.000002")["state"], "failed")

    async def test_missing_bound_credentials_never_fall_back_to_operator(self):
        repo = SimpleNamespace(get_credentials=AsyncMock(return_value=None))
        channel = FakeChannel(self.client, repo=repo)
        runtime = self.make_runtime(channel, require_connection=True, connection_owner_id="momo-owner")
        admitted = runtime.prepare(request(), team_id="T123")
        await runtime.run(admitted)
        self.assertEqual(channel.factory_calls, [])
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(self.workflow.calls, [])

    async def test_missing_trigger_in_hydrated_thread_sends_nothing(self):
        event = request(thread_ts="100.000001")
        self.client.page = {"ok": True, "messages": [{"ts": "100.000001", "user": "U123", "text": "Synthetic parent"}]}
        runtime = self.make_runtime()
        await runtime.run(runtime.prepare(event, team_id="T123"))
        self.assertEqual(self.workflow.calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(runtime.ledger.get("T123", "C123", "100.000002")["state"], "failed")

    async def test_changed_trigger_readback_sends_nothing(self):
        runtime = self.make_runtime()
        admitted = runtime.prepare(request(), team_id="T123")
        self.client.event = request(text="<@U999> brief")
        await runtime.run(admitted)
        self.assertEqual(self.workflow.calls, [])
        self.assertEqual(self.client.send_calls, [])

    async def test_duplicate_event_sends_once_and_persists_remote_timestamp(self):
        runtime = self.make_runtime()
        admitted = runtime.prepare(request(), team_id="T123")
        self.assertIsNone(runtime.prepare(request(), team_id="T123"))
        await runtime.run(admitted)
        await runtime.run(admitted)
        self.assertEqual(len(self.workflow.calls), 1)
        self.assertEqual(len(self.client.send_calls), 1)
        receipt = runtime.ledger.get("T123", "C123", "100.000002")
        self.assertEqual(receipt["state"], "delivered")
        self.assertEqual(receipt["remote_ts"], "101.000001")
        self.assertEqual(receipt["user_id"], "U123")
        self.assertEqual(self.client.retry_handlers, [])
        self.assertEqual(self.client.send_calls[0]["thread_ts"], admitted.thread_ts)

    async def test_ambiguous_delivery_never_retries_send_on_replay(self):
        runtime = self.make_runtime()
        self.client.send_error = TimeoutError("SYNTHETIC_PRIVATE_PROVIDER_ERROR")
        admitted = runtime.prepare(request(), team_id="T123")
        await runtime.run(admitted)
        first_reads = len(self.client.read_calls)
        await runtime.run(admitted)
        self.assertEqual(await runtime.recover(), 0)
        self.assertEqual(len(self.client.send_calls), 1)
        self.assertEqual(len(self.client.read_calls), first_reads)
        self.assertEqual(runtime.ledger.get("T123", "C123", "100.000002")["state"], "uncertain")

    async def test_restart_replays_queued_request_only_after_exact_hash_readback(self):
        first = self.make_runtime()
        first.prepare(request(), team_id="T123")
        await first.close()
        second = self.make_runtime()
        self.assertEqual(await second.recover(), 1)
        self.assertEqual(len(self.workflow.calls), 1)
        self.assertEqual(len(self.client.send_calls), 1)
        self.assertEqual(second.ledger.get("T123", "C123", "100.000002")["state"], "delivered")

    async def test_restart_changed_trigger_hash_is_held(self):
        first = self.make_runtime()
        first.prepare(request(), team_id="T123")
        await first.close()
        self.client.event = request(text="<@U999> brief")
        second = self.make_runtime()
        self.assertEqual(await second.recover(), 0)
        self.assertEqual(self.workflow.calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(second.ledger.get("T123", "C123", "100.000002")["state"], "queued")

    async def test_changed_route_rejects_replay_before_provider_fetch(self):
        first = self.make_runtime()
        first.prepare(request(), team_id="T123")
        await first.close()
        second = self.make_runtime(channel_clients={"C123": "different-client"})
        self.assertEqual(await second.recover(), 0)
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])
        self.assertEqual(self.workflow.calls, [])

    async def test_legacy_receipt_without_requester_cannot_fetch_or_replay(self):
        runtime = self.make_runtime()
        runtime.ledger.enqueue("T123", "C123", "100.000002", client_id="synthetic-client", thread_ts="100.000002", payload_sha256="0" * 64)
        self.assertEqual(await runtime.recover(), 0)
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])

    async def test_skipped_page_does_not_starve_current_route_or_fetch_old_routes(self):
        runtime = self.make_runtime()
        for index in range(100):
            stamp = f"{200 + index}.000001"
            runtime.ledger.enqueue("T123", "COLD", stamp, client_id="old-client", thread_ts=stamp, payload_sha256="a" * 64, user_id="U123")
        runtime.prepare(request(), team_id="T123")
        self.assertEqual(await runtime.recover(), 0)
        self.assertTrue(runtime.recovery_has_more)
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(await runtime.recover(), 1)
        self.assertFalse(runtime.recovery_has_more)
        self.assertEqual(len(self.workflow.calls), 1)
        self.assertEqual(len(self.client.send_calls), 1)
        self.assertEqual(runtime.ledger.get("T123", "COLD", "200.000001")["state"], "queued")
        # A new sweep can revisit held rows, but never sends the delivered row twice.
        self.assertEqual(await runtime.recover(), 0)
        self.assertEqual(await runtime.recover(), 0)
        self.assertEqual(len(self.client.send_calls), 1)

    async def test_exhausted_claims_never_fetch_or_keep_drain_alive(self):
        runtime = self.make_runtime()
        runtime.prepare(request(), team_id="T123")
        for clock in [100, 102, 104]:
            self.assertIsNotNone(runtime.ledger.claim("T123", "C123", "100.000002", now=clock, lease_seconds=1))
        self.assertEqual(await runtime.recover(), 0)
        self.assertFalse(runtime.recovery_has_more)
        self.assertIsNone(await runtime.next_recovery_delay())
        self.assertEqual(self.client.read_calls, [])
        self.assertEqual(self.client.send_calls, [])

    async def test_live_claim_returns_expiry_then_recovers_without_a_new_event(self):
        runtime = self.make_runtime()
        runtime.prepare(request(), team_id="T123")
        runtime.ledger.claim("T123", "C123", "100.000002", now=1000, lease_seconds=300)
        with patch("time.time", return_value=1100):
            self.assertEqual(await runtime.recover(), 0)
            self.assertEqual(await runtime.next_recovery_delay(), 200)
        self.assertEqual(self.client.read_calls, [])
        with patch("time.time", return_value=1301):
            self.assertEqual(await runtime.recover(), 1)
            self.assertIsNone(await runtime.next_recovery_delay())
        self.assertEqual(len(self.client.send_calls), 1)

    async def test_lease_expiring_during_scan_still_requests_another_sweep(self):
        runtime = self.make_runtime()
        runtime.prepare(request(), team_id="T123")
        runtime.ledger.claim("T123", "C123", "100.000002", now=1000, lease_seconds=300)
        with patch("time.time", return_value=1100):
            self.assertEqual(await runtime.recover(), 0)
        with patch("time.time", return_value=1301):
            self.assertEqual(await runtime.next_recovery_delay(), 0)
            self.assertEqual(await runtime.recover(), 1)
            self.assertIsNone(await runtime.next_recovery_delay())


if __name__ == "__main__":
    unittest.main()
