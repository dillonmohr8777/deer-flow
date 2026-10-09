import importlib.util
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location(
    "guard", Path(__file__).with_name("guard.py")
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = guard.Ledger(Path(self.tmp.name) / "receipts.jsonl", "test-cycle")
        self.policy = guard.Policy()
        self.catalog = {
            "id": "openai/gpt-6-luna",
            "context_length": 1050000,
            "pricing": {
                "prompt": "0.0000001",
                "completion": "0.0000005",
                "input_cache_write": "0.000000125",
                "overrides": [
                    {
                        "prompt": "0.0000002",
                        "completion": "0.00000075",
                        "input_cache_write": "0.00000025",
                    }
                ],
            },
        }
        self.payload = {
            "model": "openai/gpt-6-luna",
            "messages": [{"role": "user", "content": "Plan tests."}],
            "max_tokens": 2000,
        }

    def reserve(self, request_id="r1", remaining="10.04"):
        return self.ledger.reserve(
            request_id,
            guard.full_context_reservation(self.catalog, self.policy),
            Decimal(remaining),
            self.policy,
        )

    def test_full_context_reservation_covers_override_and_cache(self):
        self.assertEqual(
            guard.full_context_reservation(self.catalog, self.policy), Decimal("0.264")
        )

    def test_unsupported_paid_or_multimodal_payloads_block(self):
        cases = [
            dict(self.payload, plugins=[{"id": "web"}]),
            dict(self.payload, models=["other"]),
            dict(self.payload, tools=[{"type": "web_search"}]),
            dict(
                self.payload,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/x"},
                            }
                        ],
                    }
                ],
            ),
            dict(self.payload, model="openai/gpt-6.1-sol"),
        ]
        for payload in cases:
            with self.assertRaises(guard.Stop):
                guard.validate_payload(payload, self.policy)

    def test_output_and_input_are_bounded(self):
        with self.assertRaises(guard.Stop):
            guard.validate_payload(dict(self.payload, max_tokens=2001), self.policy)
        with self.assertRaises(guard.Stop):
            guard.validate_payload(
                dict(
                    self.payload, messages=[{"role": "user", "content": "x" * 130000}]
                ),
                self.policy,
            )

    def test_cap_reserve_concurrency_and_replay(self):
        self.reserve()
        self.reserve("r2")
        with self.assertRaises(guard.Stop):
            self.reserve("r3")
        with self.assertRaises(guard.Stop):
            self.reserve("r1")
        self.ledger.settle("r1", Decimal("0.01"), "gen-1")
        with self.assertRaises(guard.Stop):
            self.reserve("r3", "8.4")

    def test_unknown_cost_or_restart_stops_without_release(self):
        self.reserve()
        self.ledger.uncertain("r1", "usage_cost_missing")
        with self.assertRaises(guard.Stop):
            self.reserve("r2")
        other = guard.Ledger(self.ledger.path, "test-cycle")
        with self.assertRaises(guard.Stop):
            other.reserve("r3", Decimal("0.264"), Decimal(10), self.policy)
        self.assertEqual(self.ledger.snapshot()["held_usd"], Decimal("0.264"))

    def test_inflight_crash_and_concurrent_admission(self):
        def run(i):
            try:
                self.reserve(str(i))
                return True
            except guard.Stop:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(run, range(8))), 2)
        other = guard.Ledger(self.ledger.path, "test-cycle")
        with self.assertRaises(guard.Stop):
            other.reserve("after-restart", Decimal("0.264"), Decimal(10), self.policy)

    def test_call_ceiling_and_actual_cost_under_cap(self):
        for i in range(16):
            self.reserve(str(i))
            self.ledger.settle(str(i), Decimal("0.02"), "gen-" + str(i))
        with self.assertRaises(guard.Stop):
            self.reserve("17")
        self.assertEqual(self.ledger.snapshot()["settled_usd"], Decimal("0.32"))

    def test_usage_missing_nan_wrong_model_never_zero(self):
        cases = [
            {"model": "openai/gpt-6-luna", "usage": {}},
            {"model": "openai/gpt-6-luna", "usage": {"cost": float("nan")}},
            {"model": "other", "usage": {"cost": 0}},
        ]
        for data in cases:
            with self.assertRaises(guard.Stop):
                guard.response_cost(json.dumps(data).encode(), False, self.policy)

    def test_sse_cost_and_actual_overrun_blocks_future(self):
        data = b'data: {"model":"openai/gpt-6-luna","usage":{"cost":0.01},"id":"gen-x"}\n\ndata: [DONE]\n\n'
        self.assertEqual(
            guard.response_cost(data, True, self.policy), (Decimal("0.01"), "gen-x")
        )
        self.reserve()
        self.ledger.settle("r1", Decimal("0.3"), "overrun")
        with self.assertRaises(guard.Stop):
            self.reserve("next")

    def test_hash_broker_exact_binding_and_symlink_rejection(self):
        root = Path(self.tmp.name) / "outputs"
        target = root / "test-cycle" / "work-order" / "artifact.md"
        target.parent.mkdir(parents=True)
        target.write_text("Exact artifact", encoding="utf-8")
        receipt = guard.hash_artifact(
            root, "test-cycle", "work-order", "artifact.md", "a" * 64
        )
        self.assertTrue(receipt["nonempty"])
        self.assertEqual(receipt["source_sha256"], "a" * 64)
        target.unlink()
        target.symlink_to(Path(self.tmp.name) / "receipts.jsonl")
        with self.assertRaises(guard.Stop):
            guard.hash_artifact(
                root, "test-cycle", "work-order", "artifact.md", "a" * 64
            )

    def test_total_cap_and_corrupt_ledger(self):
        for i in range(4):
            self.reserve(str(i))
            self.ledger.settle(str(i), Decimal("0.2"), "gen-" + str(i))
        with self.assertRaises(guard.Stop):
            self.reserve("cap")
        self.ledger.path.write_text("partial-invalid-json", encoding="utf-8")
        with self.assertRaises(guard.Stop):
            self.reserve("corrupt")

    def test_loopback_transport_and_separate_existing_key_boundary(self):
        forwarded = []

        def fake_upstream(path, key, payload=None, limit=4000000):
            self.assertEqual(key, "upstream-fixture-token")
            if path == "/credits":
                return b'{"data":{"total_credits":132,"total_usage":121.96}}'
            if path == "/models":
                return json.dumps({"data": [self.catalog]}).encode()
            forwarded.append(payload)
            return b'{"id":"gen-fixture","model":"openai/gpt-6-luna","usage":{"cost":0.001},"choices":[]}'

        server = guard.make_server(
            self.ledger, "upstream-fixture-token", 0, "client-fixture-token"
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(guard, "upstream", fake_upstream):
            thread.start()
            try:
                request = Request(
                    "http://127.0.0.1:"
                    + str(server.server_port)
                    + "/v1/chat/completions",
                    data=json.dumps(self.payload).encode(),
                    headers={
                        "Authorization": "Bearer client-fixture-token",
                        "Content-Type": "application/json",
                    },
                )
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response)["id"], "gen-fixture")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        self.assertEqual(len(forwarded), 1)
        self.assertFalse(forwarded[0]["provider"]["allow_fallbacks"])
        self.assertEqual(forwarded[0]["provider"]["only"], ["openai"])
        self.assertEqual(self.ledger.snapshot()["settled_usd"], Decimal("0.001"))

    def test_sse_terminal_is_an_event_not_generated_text(self):
        fake_terminal = {
            "id": "gen-a",
            "model": self.policy.model,
            "choices": [{"delta": {"content": "data: [DONE]"}}],
            "usage": {"cost": 0.01},
        }
        body = ("data: " + json.dumps(fake_terminal) + "\n\n").encode()
        with self.assertRaises(guard.Stop):
            guard.response_cost(body, True, self.policy)

    def test_sse_generation_and_final_usage_must_be_bound(self):
        first = {"id": "gen-a", "model": self.policy.model, "choices": []}
        last = {"id": "gen-b", "model": self.policy.model, "usage": {"cost": 0.01}}
        body = (
            "data: "
            + json.dumps(first)
            + "\n\ndata: "
            + json.dumps(last)
            + "\n\ndata: [DONE]\n\n"
        ).encode()
        with self.assertRaises(guard.Stop):
            guard.response_cost(body, True, self.policy)
        last["id"] = "gen-a"
        last.pop("model")
        body = (
            "data: "
            + json.dumps(first)
            + "\n\ndata: "
            + json.dumps(last)
            + "\n\ndata: [DONE]\n\n"
        ).encode()
        with self.assertRaises(guard.Stop):
            guard.response_cost(body, True, self.policy)

    def test_sse_error_and_early_terminal_refused(self):
        valid = (
            'data: {"id":"gen-a","model":"openai/gpt-6-luna","usage":{"cost":0.01}}\n\n'
        )
        cases = [
            "data: [DONE]\n\n" + valid,
            valid + 'data: {"error":{"message":"private failure"}}\n\ndata: [DONE]\n\n',
            valid + "event: error\ndata: {}\n\ndata: [DONE]\n\n",
        ]
        for case in cases:
            with self.assertRaises(guard.Stop):
                guard.response_cost(case.encode(), True, self.policy)

    def test_malformed_containers_raise_sanitized_stop(self):
        cases = [
            dict(self.payload, tools=[{"type": "function", "function": []}]),
            dict(self.payload, stream={}),
            dict(self.payload, stream_options=[]),
            dict(self.payload, temperature=float("nan")),
        ]
        for case in cases:
            with self.assertRaises(guard.Stop):
                guard.validate_payload(case, self.policy)
        for raw in [b"data: []\n\ndata: [DONE]\n\n", b"data: null\n\ndata: [DONE]\n\n"]:
            with self.assertRaises(guard.Stop):
                guard.response_cost(raw, True, self.policy)

    def test_redirect_never_replays_bearer_or_private_body(self):
        seen = []

        class RedirectFixture(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/should-not-receive-key")
                self.end_headers()

            def do_GET(self):
                seen.append(self.path)
                self.send_response(200)
                self.end_headers()

        server = HTTPServer(("127.0.0.1", 0), RedirectFixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                "http://127.0.0.1:" + str(server.server_port) + "/first",
                data=b"private-fixture-body",
                headers={"Authorization": "Bearer fixture-not-a-key"},
            )
            with self.assertRaises(guard.Stop):
                guard.no_redirect_opener().open(request, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(seen, ["/first"])


if __name__ == "__main__":
    unittest.main()
