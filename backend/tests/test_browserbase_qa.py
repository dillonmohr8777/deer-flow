"""Offline admission, cost and owned-session cleanup checks; no provider calls."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from deerflow.community.browser_automation.browserbase_qa import BrowserbaseAPI, QaPolicy, run_qa

PROJECT = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
SESSION = "b245e38f-bc70-49b4-94a4-671b93a57990"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://example.com.evil.test/",
        "https://user:secret@example.com/",
        "https://example.com:8443/",
        "https://example.com/?token=secret",
        "https://example.com/#secret",
        "file:///tmp/private",
        "https://127.0.0.1/",
        "https://[::1]/",
    ],
)
def test_policy_rejects_unsafe_targets(url):
    with pytest.raises(ValueError):
        QaPolicy(("example.com",)).validate_url(url, target=True)


def test_policy_requires_exact_hosts_and_blocks_mutating_resource_requests():
    policy = QaPolicy(("example.com",))
    assert policy.request_allowed("https://example.com/style.css?v=1", "GET")
    assert not policy.request_allowed("https://a.example.com/", "GET")
    assert not policy.request_allowed("https://example.com/submit", "POST")
    assert not policy.request_allowed("https://example.com/submit", "PUT")


def test_ip_literal_is_rejected_even_if_explicitly_allowlisted():
    with pytest.raises(ValueError):
        QaPolicy(("127.0.0.1",)).validate_url("https://127.0.0.1/", target=True)


@pytest.mark.asyncio
async def test_existing_artifacts_stop_before_any_provider_call(tmp_path: Path):
    (tmp_path / "original.txt").write_text("preserve", encoding="utf-8")

    def transport(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Existing output must be rejected before provider access")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        with pytest.raises(ValueError, match="fresh"):
            await run_qa(BrowserbaseAPI("secret", PROJECT, http), "https://example.com/", QaPolicy(("example.com",)), tmp_path)
    assert (tmp_path / "original.txt").read_text() == "preserve"


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_fails", [False, True])
async def test_runner_releases_only_its_created_session_even_when_capture_fails(tmp_path: Path, capture_fails):
    requests: list[tuple[str, str]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/usage"):
            return httpx.Response(200, json={"browserMinutes": 1, "proxyBytes": 0})
        if request.url.path == "/v1/sessions":
            body = json.loads(request.content)
            assert body["timeout"] == 60
            assert body["keepAlive"] is False and body["proxies"] is False
            assert body["browserSettings"]["recordSession"] is False
            assert body["browserSettings"]["logSession"] is False
            assert body["browserSettings"]["solveCaptchas"] is False
            assert body["browserSettings"]["allowedDomains"] == ["example.com"]
            return httpx.Response(200, json={"id": SESSION, "connectUrl": "wss://connect.browserbase.com/?apiKey=secret"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": SESSION, "status": "COMPLETED"})
        return httpx.Response(200, json={"id": SESSION, "status": "COMPLETED"})

    async def capture(*_args):
        if capture_fails:
            raise RuntimeError("unsafe raw failure containing apiKey=secret")
        return [{"width": 390, "overflow": False}]

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        result = await run_qa(BrowserbaseAPI("secret", PROJECT, http), "https://example.com/", QaPolicy(("example.com",)), tmp_path, capture=capture)

    assert requests.count(("POST", "/v1/sessions")) == 1
    assert requests.count(("POST", f"/v1/sessions/{SESSION}")) == 1
    assert result["release_status"] == "COMPLETED"
    assert result["status"] == ("failed" if capture_fails else "completed")
    assert "secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [{}, {"browserMinutes": None}, {"browserMinutes": 50}, {"browserMinutes": -1}, {"browserMinutes": True}, {"browserMinutes": float("nan")}, {"browserMinutes": float("inf")}])
async def test_missing_invalid_or_exhausted_usage_never_creates_a_session(tmp_path: Path, usage):
    requests: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(200, content=json.dumps(usage), headers={"Content-Type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        with pytest.raises(ValueError):
            await run_qa(BrowserbaseAPI("secret", PROJECT, http), "https://example.com/", QaPolicy(("example.com",)), tmp_path)
    assert requests == ["GET"]


@pytest.mark.asyncio
async def test_api_errors_do_not_echo_provider_payloads_or_credentials():
    def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private apiKey=secret provider payload")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        with pytest.raises(RuntimeError, match="HTTP 401") as exc:
            await BrowserbaseAPI("secret", PROJECT, http).usage()
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_missing_playwright_never_creates_a_session(tmp_path: Path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_qa

    monkeypatch.setattr(browserbase_qa, "playwright_available", lambda: False)

    class API:
        project_id = "fake-project"

        async def usage(self):
            return {"browserMinutes": 0}

        async def create(self, policy, **kwargs):
            raise AssertionError("no session may be created")

    with pytest.raises(ValueError, match="Playwright"):
        await browserbase_qa.run_qa(API(), "https://example.com/", browserbase_qa.QaPolicy(("example.com",)), tmp_path / "out")
