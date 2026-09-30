"""Manual, bounded public-page QA using Browserbase's headless HTTP/CDP API.

No registration, scheduler, model call, persistent browser context or live-client
write. The operator supplies an exact host allowlist and private output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import os
import socket
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

_API = "https://api.browserbase.com"
_WIDTHS = (390, 768, 1440)
_MAX_SCREENSHOT_BYTES = 5_000_000
_MAX_API_BYTES = 2_000_000


@dataclass(frozen=True)
class QaPolicy:
    allowed_hosts: tuple[str, ...]
    max_reported_browser_minutes: float = 50
    max_requests: int = 200

    def validate_url(self, url: str, *, target: bool = False) -> None:
        try:
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname not in self.allowed_hosts or parts.port not in (None, 443):
                raise ValueError
            if parts.username or parts.password or (target and (parts.query or parts.fragment)):
                raise ValueError
            try:
                ipaddress.ip_address(parts.hostname)
            except ValueError:
                pass
            else:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("QA URL must be HTTPS on an exact allowed public host, without credentials or target query/fragment") from None

    def request_allowed(self, url: str, method: str) -> bool:
        if method not in {"GET", "HEAD"}:
            return False
        try:
            self.validate_url(url)
        except ValueError:
            return False
        return True


class BrowserbaseAPI:
    def __init__(self, api_key: str, project_id: str, http: httpx.AsyncClient):
        self._key = api_key
        self.project_id = str(UUID(project_id))
        self.http = http

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            response = await self.http.request(method, _API + path, headers={"X-BB-API-Key": self._key}, json=body)
        except httpx.HTTPError:
            raise RuntimeError("Browserbase API transport failed; no automatic retry") from None
        if not response.is_success:
            raise RuntimeError(f"Browserbase API request failed (HTTP {response.status_code})")
        if len(response.content) > _MAX_API_BYTES:
            raise RuntimeError("Browserbase API response exceeds QA limit")
        try:
            result = response.json()
        except ValueError:
            raise RuntimeError("Browserbase API response is not JSON") from None
        if not isinstance(result, dict):
            raise RuntimeError("Browserbase API response has an invalid shape")
        return result

    async def usage(self) -> dict:
        return await self._request("GET", f"/v1/projects/{self.project_id}/usage")

    async def create(self, policy: QaPolicy) -> dict:
        return await self._request(
            "POST",
            "/v1/sessions",
            {
                "projectId": self.project_id,
                "timeout": 60,
                "keepAlive": False,
                "proxies": False,
                "browserSettings": {"allowedDomains": list(policy.allowed_hosts), "recordSession": False, "logSession": False, "solveCaptchas": False, "blockAds": True},
                "userMetadata": {"purpose": "momobot-public-readonly-qa"},
            },
        )

    async def release(self, session_id: str) -> dict:
        return await self._request("POST", f"/v1/sessions/{UUID(session_id)}", {"projectId": self.project_id, "status": "REQUEST_RELEASE"})

    async def retrieve(self, session_id: str) -> dict:
        return await self._request("GET", f"/v1/sessions/{UUID(session_id)}")


async def capture_page(connect_url: str, policy: QaPolicy, target: str, output: Path) -> list[dict]:
    from playwright.async_api import async_playwright

    endpoint = urlsplit(connect_url)
    if endpoint.scheme != "wss" or not endpoint.hostname or not endpoint.hostname.endswith(".browserbase.com") or endpoint.username or endpoint.password or endpoint.port not in (None, 443):
        raise ValueError("Invalid Browserbase connection endpoint")
    public_hosts: dict[str, bool] = {}
    request_count = 0
    blocked_count = 0
    response_bytes = 0

    async def route_request(route):
        nonlocal request_count, blocked_count, response_bytes
        request_count += 1
        request = route.request
        allowed = request_count <= policy.max_requests and policy.request_allowed(request.url, request.method)
        host = urlsplit(request.url).hostname
        if allowed and host not in public_hosts:
            try:
                answers = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
                public_hosts[host] = bool(answers) and all(ipaddress.ip_address(answer[4][0]).is_global for answer in answers)
            except (OSError, ValueError):
                public_hosts[host] = False
        if allowed and public_hosts.get(host):
            try:
                # Do not let redirects bypass request admission. Only 2xx
                # responses are served, and each response/body is bounded.
                fetched = await route.fetch(max_redirects=0, timeout=8_000)
                body = await fetched.body()
                response_bytes += len(body)
                if 200 <= fetched.status < 300 and len(body) <= 5_000_000 and response_bytes <= 20_000_000:
                    await route.fulfill(response=fetched)
                    return
            except Exception:
                pass
        blocked_count += 1
        await route.abort()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(connect_url, timeout=15_000)
        try:
            context = await browser.new_context(accept_downloads=False, service_workers="block", viewport={"width": 390, "height": 900})
            await context.route("**/*", route_request)
            await context.route_web_socket("**/*", lambda ws: ws.close())
            page = await context.new_page()
            page.on("dialog", lambda dialog: dialog.dismiss())
            response = await page.goto(target, wait_until="domcontentloaded", timeout=20_000)
            policy.validate_url(page.url, target=True)
            reports = []
            for width in _WIDTHS:
                await page.set_viewport_size({"width": width, "height": 900})
                await page.evaluate("document.fonts.ready")
                metrics = await page.evaluate("""() => {
                    const nodes = [...document.querySelectorAll('a,button,input,select,textarea,[role=button]')].slice(0,500);
                    const visible = nodes.map(e => e.getBoundingClientRect()).filter(r => r.width > 0 && r.height > 0);
                    return {title: document.title.slice(0,120), width: innerWidth,
                      scroll_width: document.documentElement.scrollWidth,
                      overflow: document.documentElement.scrollWidth > innerWidth,
                      interactive_nodes_checked: visible.length,
                      targets_below_44px: visible.filter(r => r.width < 44 || r.height < 44).length};
                }""")
                image = await page.screenshot(full_page=False)
                if len(image) > _MAX_SCREENSHOT_BYTES:
                    raise ValueError("QA screenshot exceeds size limit")
                screenshot = output / f"viewport-{width}.png"
                with screenshot.open("xb") as handle:
                    handle.write(image)
                screenshot.chmod(0o600)
                reports.append({**metrics, "http_status": response.status if response else None, "screenshot": screenshot.name})
            dropdown = {"available": False}
            select = page.locator("select").first
            if await select.count():
                options = await select.locator("option").evaluate_all("els => els.slice(0,30).map(e => ({value:e.value,label:e.textContent,disabled:e.disabled}))")
                demo = next((opt for opt in options if opt["value"] and not opt["disabled"] and "demo" in (opt["label"] or "").lower()), None)
                dropdown = {"available": True, "demo_option_present": demo is not None}
                if demo:
                    await select.select_option(value=demo["value"], timeout=5_000)
                    dropdown["selection_readback_matches"] = await select.input_value() == demo["value"]
            reports[-1]["dropdown"] = dropdown
            reports[-1]["requests_observed"] = request_count
            reports[-1]["requests_blocked"] = blocked_count
            reports[-1]["response_bytes"] = response_bytes
            await context.close()
            return reports
        finally:
            # This is a new cloud browser created by this runner, never a user browser.
            await browser.close()


Capture = Callable[[str, QaPolicy, str, Path], Awaitable[list[dict]]]


async def run_qa(api: BrowserbaseAPI, target: str, policy: QaPolicy, output: Path, *, capture: Capture = capture_page) -> dict[str, Any]:
    policy.validate_url(target, target=True)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("QA output must be a fresh, empty local directory")
    usage = await api.usage()
    minutes = usage.get("browserMinutes")
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not math.isfinite(minutes) or minutes < 0 or minutes >= policy.max_reported_browser_minutes:
        raise ValueError("Missing, invalid or exhausted browser-usage allowance; no session created")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    created = await api.create(policy)  # Exactly one attempt; ambiguous failures are not retried.
    session_id = str(UUID(created["id"]))
    result: dict[str, Any] = {"status": "failed", "session_id": session_id, "project_id": api.project_id, "usage_before_browser_minutes": minutes, "target": target, "max_session_seconds": 60, "model_calls": 0}
    try:
        result["viewports"] = await asyncio.wait_for(capture(created["connectUrl"], policy, target, output), timeout=45)
        result["status"] = "completed"
    except Exception as exc:
        # Playwright errors may include a credential-bearing CDP URL. Never echo them.
        result["capture_error_type"] = type(exc).__name__
    finally:
        try:
            released = await api.release(session_id)
            final = await api.retrieve(session_id)
            status = final.get("status", released.get("status"))
            result["release_status"] = status if status in {"COMPLETED", "ERROR", "TIMED_OUT", "RUNNING", "PENDING"} else "unconfirmed"
        except Exception as exc:
            result["release_status"] = "unconfirmed"
            result["release_error_type"] = type(exc).__name__
    return result


def existing_api_key() -> str:
    key = os.environ.get("BROWSERBASE_API_KEY")
    if not key:
        read = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", "dillonmohr", "-s", "browserbase.api-key", "-w"], capture_output=True, text=True, check=False)
        key = read.stdout.strip() if read.returncode == 0 else None
    if not key:
        raise RuntimeError("Existing Browserbase credential unavailable")
    return key


async def _main(args) -> int:
    policy = QaPolicy(tuple(args.allow_host))
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as http:
        result = await run_qa(BrowserbaseAPI(existing_api_key(), args.project_id, http), args.url, policy, Path(args.output))
    receipt = Path(args.output) / "receipt.json"
    with receipt.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    receipt.chmod(0o600)
    print(json.dumps(result))
    return 0 if result["status"] == "completed" and result["release_status"] in {"COMPLETED", "ERROR", "TIMED_OUT"} else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--allow-host", action="append", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", required=True, help="A fresh private local output directory; keep receipts outside Git")
    try:
        raise SystemExit(asyncio.run(_main(parser.parse_args())))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
