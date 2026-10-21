"""Offline login-broker checks: fake 1Password, Browserbase and Playwright; synthetic values only."""

import asyncio
import contextlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

EC2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EC2))
spec = importlib.util.spec_from_file_location("login_broker", EC2 / "login_broker.py")
broker_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker_mod)

SID = "22222222-2222-4222-8222-222222222222"
SECRETS = {"username": "synthetic-user", "password": "synthetic-pass-123"}


class FakeOp:
    def __init__(self):
        login = SimpleNamespace(id="i1", title="Demo", category="LOGIN", tags=["momobot"],
                                websites=[SimpleNamespace(url="https://login.example.com/signin")])
        untagged = SimpleNamespace(id="i2", title="Private", category="LOGIN", tags=[], websites=[])
        self.vaults = SimpleNamespace(list=self._async([SimpleNamespace(id="v1")]))
        self.items = SimpleNamespace(list=self._async([login, untagged]))
        self.resolved = []

        async def resolve(ref):
            self.resolved.append(ref)
            return SECRETS[ref.rsplit("/", 1)[1]]

        self.secrets = SimpleNamespace(resolve=resolve)

    @staticmethod
    def _async(value):
        async def call(*args):
            return value
        return call


def fake_connect(urls):
    page = SimpleNamespace(url=urls[0])
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[SimpleNamespace(url=u) for u in urls])])

    @contextlib.asynccontextmanager
    async def connect():
        async def connect_over_cdp(url, timeout):
            return browser
        yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect_over_cdp))

    return connect, page


def make(session=None, urls=("https://login.example.com/signin?next=/x",)):
    connect, _ = fake_connect(list(urls))
    b = broker_mod.Broker([FakeOp()], "synthetic-bb-key", "proj-1", connect=connect)
    b._session = lambda sid: session or {"status": "RUNNING", "projectId": "proj-1", "userMetadata": {"owner": broker_mod.OWNER}}
    return b


class BrokerTests(unittest.TestCase):
    def run_login(self, b, request):
        filled = []

        async def fake_fill(page, secret):
            filled.extend([await secret("username"), await secret("password")])
            return "submitted"

        with patch.object(broker_mod, "fill_login", fake_fill):
            return asyncio.run(b.login(request)), filled

    def test_happy_path_fills_but_never_returns_values(self):
        b = make()
        result, filled = self.run_login(b, {"session": SID, "item": "Demo"})
        self.assertEqual(filled, [SECRETS["username"], SECRETS["password"]])
        self.assertEqual(result, {"status": "submitted", "page": "login.example.com/signin"})
        text = json.dumps(result)
        self.assertTrue(all(v not in text for v in SECRETS.values()))
        self.assertTrue(all(r.startswith("op://v1/i1/") for r in b.ops[0].resolved))

    def test_unknown_item_lists_only_tagged_names(self):
        result, filled = self.run_login(make(), {"session": SID, "item": "Private"})
        self.assertEqual(result, {"status": "unknown_item", "available": ["Demo"]})
        self.assertEqual(filled, [])

    def test_foreign_or_stopped_session_is_rejected_before_any_secret(self):
        for session in ({"status": "RUNNING", "projectId": "other", "userMetadata": {"owner": broker_mod.OWNER}},
                        {"status": "COMPLETED", "projectId": "proj-1", "userMetadata": {"owner": broker_mod.OWNER}},
                        {"status": "RUNNING", "projectId": "proj-1", "userMetadata": {"owner": "someone-else"}}):
            b = make(session=session)
            result, filled = self.run_login(b, {"session": SID, "item": "Demo"})
            self.assertEqual(result["status"], "session_not_owned")
            self.assertEqual((filled, b.ops[0].resolved), ([], []))

    def test_page_on_another_host_or_plain_http_gets_nothing(self):
        for url in ("https://evil.example.net/login.example.com", "http://login.example.com/signin", "https://example.com/"):
            b = make(urls=(url,))
            result, filled = self.run_login(b, {"session": SID, "item": "Demo"})
            self.assertEqual(result["status"], "open_login_page_first")
            self.assertEqual((filled, b.ops[0].resolved), ([], []))

    def test_bad_requests(self):
        for req in ({"session": "not-a-uuid", "item": "Demo"}, {"session": SID}, {"session": SID, "item": "x" * 201}):
            self.assertEqual(self.run_login(make(), req)[0], {"status": "bad_request"})

    def test_subdomain_allowed(self):
        self.assertTrue(broker_mod.host_allowed("https://a.login.example.com/x", ["login.example.com"]))
        self.assertFalse(broker_mod.host_allowed("https://notlogin.example.com/x", ["https://login.example.com"]))


if __name__ == "__main__":
    unittest.main()
