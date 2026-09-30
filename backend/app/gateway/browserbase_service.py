"""Durable public-only research with pinned HTTPS fetches and isolated cloud snapshots.

Browserbase never navigates untrusted target URLs: it renders escaped source text
with all network requests blocked. This avoids cloud DNS rebinding and the documented
limits of allowedDomains, which restricts only top-frame navigation.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import sqlite3
import ssl
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, overload
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

import httpx

MAX_PAGES = 3
SESSION_TIMEOUT = 180
CREATE_REQUEST_TIMEOUT = 10
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
MODE = "public_read_only_snapshot"
RESERVED_MINUTES_PER_SESSION = -(-SESSION_TIMEOUT // 60)  # ceil(seconds / 60)
MAX_ACTIVE_SESSIONS = 5
ALLOWED_CONNECT_HOSTS = {
    "connect.browserbase.com",
    # Exact endpoint observed from authenticated api.browserbase.com (us-west-2).
    "connect.usw2.browserbase.com",
}
_TERMINAL = {"completed", "failed", "cancelled"}
_PNG = b"\x89PNG\r\n\x1a\n"
_SECRET_QUERY = re.compile(r"(?:api[_-]?key|token|auth|authorization|password|passwd|secret|signature|credential|jwt|session|code|key)$", re.I)
type Record = dict[str, Any]
type StorageResult = Record | list[Record] | tuple[Record, bool] | tuple[str, Record] | None


def _owner_reserved(data: dict, now: float) -> bool:
    if data["status"] not in _TERMINAL:
        return True
    if data.get("session_closed") is True:
        return False
    expires_at = data.get("session_expires_at")
    return isinstance(expires_at, (int, float)) and expires_at > now


class BrowserbaseError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if isinstance(address, ipaddress.IPv6Address):
            if address.teredo or address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
                return False
            if address.sixtofour and not _public_address(str(address.sixtofour)):
                return False
        return address.is_global and not address.is_multicast
    except ValueError:
        return False


def public_https_url(value: str) -> str:
    """Normalize HTTPS public URLs; DNS is additionally validated before transport."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise BrowserbaseError("invalid_public_url")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")) or "." not in host and ":" not in host:
            raise BrowserbaseError("private_network_blocked")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                raise ValueError
        else:
            if not _public_address(host):
                raise BrowserbaseError("private_network_blocked")
        if any(_SECRET_QUERY.search(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise BrowserbaseError("secret_bearing_url")
        netloc = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        raise BrowserbaseError("invalid_public_url") from None


class _PublicText(HTMLParser):
    _excluded = {"script", "style", "form", "iframe", "object", "embed", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skipped: list[str] = []
        self.title_depth = 0
        self.parts: list[str] = []
        self.titles: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.skipped:
            if tag not in {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self.skipped.append(tag)
        elif tag in self._excluded:
            self.skipped.append(tag)
        elif tag == "title":
            self.title_depth += 1

    def handle_endtag(self, tag):
        if self.skipped:
            if tag in self.skipped:
                last = len(self.skipped) - 1 - self.skipped[::-1].index(tag)
                del self.skipped[last:]
        elif tag == "title" and self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data):
        if not self.skipped:
            clean = " ".join(data.split())
            if clean:
                (self.titles if self.title_depth else self.parts).append(clean)


def _resolve(host: str) -> list[str]:
    return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM) if isinstance(item[4][0], str)))


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, 443, timeout=10, context=self.tls_context)
        self.address = address

    def connect(self):
        # Connect to the validated literal address, while checking TLS for hostname.
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _pinned_get(url: str, address: str):
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise BrowserbaseError("invalid_public_url")
    connection = _PinnedHTTPS(parsed.hostname, address)
    try:
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        connection.request("GET", path, headers={"User-Agent": "MomoBot-Public-Research/1.0", "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        data = response.read(MAX_BODY_BYTES + 1)
        if len(data) > MAX_BODY_BYTES:
            raise BrowserbaseError("page_too_large")
        if headers.get("content-encoding", "").lower() == "gzip":
            # Read decompression through a bounded file object rather than gzip.decompress.
            import io

            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                data = compressed.read(MAX_BODY_BYTES + 1)
            if len(data) > MAX_BODY_BYTES:
                raise BrowserbaseError("page_too_large")
        elif headers.get("content-encoding", "").lower() not in ("", "identity"):
            raise BrowserbaseError("unsupported_content_encoding")
        return response.status, headers, data
    finally:
        connection.close()


class PublicPageFetcher:
    """No proxy/environment credentials/cookies; validate every hop and pin its IP."""

    def __init__(self, *, resolver: Callable = _resolve, transport: Callable = _pinned_get):
        self.resolver = resolver
        self.transport = transport

    def fetch(self, value: str) -> dict:
        original = public_https_url(value)
        current = original
        for _ in range(6):
            host = urlsplit(current).hostname
            try:
                addresses = self.resolver(host)
            except OSError:
                raise BrowserbaseError("dns_resolution_failed", 502) from None
            if not addresses or any(not _public_address(address) for address in addresses):
                raise BrowserbaseError("private_network_blocked")
            try:
                status, headers, data = self.transport(current, addresses[0])
            except BrowserbaseError:
                raise
            except Exception:
                raise BrowserbaseError("public_page_fetch_failed", 502) from None
            if status in (301, 302, 303, 307, 308):
                location = headers.get("location")
                if not location:
                    raise BrowserbaseError("invalid_redirect", 502)
                current = public_https_url(urljoin(current, location))
                continue
            if status != 200:
                raise BrowserbaseError("public_page_unavailable", 502)
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in ("text/html", "text/plain", "application/xhtml+xml"):
                raise BrowserbaseError("unsupported_public_content")
            text = data.decode("utf-8", errors="replace")
            title = host
            if content_type != "text/plain":
                parser = _PublicText()
                parser.feed(text)
                title = " ".join(parser.titles)[:200] or host
                text = "\n".join(parser.parts)
            return {"url": original, "final_url": current, "title": title, "text": text[:60000], "content_type": content_type}
        raise BrowserbaseError("too_many_redirects", 502)


async def _render_snapshots(connect_url: str, pages: list[dict]) -> list[bytes]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise BrowserbaseError("browser_dependency_missing", 503) from None
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(connect_url, timeout=20000)
        context = None
        try:
            context = await browser.new_context(java_script_enabled=False, service_workers="block", viewport={"width": 1280, "height": 900}, accept_downloads=False)
            await context.route("**/*", lambda route: route.abort())
            screenshots = []
            for evidence in pages:
                page = await context.new_page()
                try:
                    # Only escaped public text is sent to cloud browser; no target resource.
                    document = (
                        '<!doctype html><html><head><meta charset="utf-8">'
                        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'\">"
                        "<style>body{margin:48px;background:#fff;color:#141414;font:20px/1.55 system-ui}h1{font-size:30px}p{overflow-wrap:anywhere}pre{white-space:pre-wrap;font:inherit}</style>"
                        "</head><body><p>Public source text snapshot · MomoBot</p><h1>"
                        + html.escape(evidence["title"])
                        + "</h1><p>"
                        + html.escape(evidence["final_url"])
                        + "</p><pre>"
                        + html.escape(evidence["text"][:24000])
                        + "</pre></body></html>"
                    )
                    await page.set_content(document, wait_until="domcontentloaded", timeout=15000)
                    # Bound image size to one useful viewport; full text remains in receipt.
                    screenshots.append(await page.screenshot(type="png", full_page=False, timeout=15000))
                finally:
                    await page.close()
            return screenshots
        finally:
            if context is not None:
                await context.close()
            await browser.close()


class BrowserbaseResearchService:
    def __init__(self, path: Path, *, client_factory: Callable | None = None, browser_runner: Callable | None = None, fetcher: Callable | None = None):
        self.path = Path(path)
        self.artifact_dir = self.path.parent / "browserbase-artifacts"
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(base_url="https://api.browserbase.com", timeout=10, follow_redirects=False, trust_env=False))
        self.browser_runner = browser_runner or _render_snapshots
        self.fetcher = fetcher or self._fetch
        self.tasks: dict[str, asyncio.Task] = {}
        self.admissions: set[asyncio.Task] = set()
        self.cleanups: dict[str, asyncio.Task] = {}
        self.cancel_requested: set[str] = set()
        self.lease = None
        self.lock = asyncio.Lock()
        self.started = False
        self.closing = False

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("MOMOBOT_BROWSERBASE_ENABLED", "").lower() in ("1", "true", "yes")

    async def _fetch(self, url):
        return await asyncio.to_thread(PublicPageFetcher().fetch, url)

    def _init_db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS research (id TEXT PRIMARY KEY, owner TEXT NOT NULL, idem TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(owner, idem))")
        os.chmod(self.path, 0o600)

    def _db(self, action: str, *args: Any) -> StorageResult:
        with sqlite3.connect(self.path, timeout=15) as db:
            if action == "get":
                row = db.execute("SELECT data FROM research WHERE id=? AND owner=?", args).fetchone()
                if row is None:
                    raise BrowserbaseError("not_found", 404)
                return json.loads(row[0])
            if action == "list":
                return [json.loads(row[0]) for row in db.execute("SELECT data FROM research WHERE owner=? ORDER BY rowid DESC LIMIT 100", args)]
            if action == "active":
                rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM research")]
                return [row for row in rows if row["status"] not in _TERMINAL]
            if action == "held":
                rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM research")]
                return [row for row in rows if _owner_reserved(row, time.time())]
            if action == "save":
                data = args[0]
                db.execute("UPDATE research SET data=? WHERE id=?", (json.dumps(data, separators=(",", ":")), data["id"]))
                return
            if action == "reserve":
                owner, key, fingerprint, data = args
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT fingerprint,data FROM research WHERE owner=? AND idem=?", (owner, key)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise BrowserbaseError("idempotency_conflict", 409)
                    return json.loads(previous[1]), False
                rows = db.execute("SELECT data FROM research WHERE owner=?", (owner,))
                if any(_owner_reserved(json.loads(row[0]), time.time()) for row in rows):
                    raise BrowserbaseError("owner_busy", 409)
                db.execute("INSERT INTO research VALUES (?,?,?,?,?)", (data["id"], owner, key, fingerprint, json.dumps(data, separators=(",", ":"))))
                return data, True
            if action == "idem":
                row = db.execute("SELECT fingerprint,data FROM research WHERE owner=? AND idem=?", args).fetchone()
                return (row[0], json.loads(row[1])) if row else None
        raise ValueError("Unknown storage action")

    @overload
    async def _storage(self, action: Literal["get"], *args: Any) -> Record: ...

    @overload
    async def _storage(self, action: Literal["list", "active", "held"], *args: Any) -> list[Record]: ...

    @overload
    async def _storage(self, action: Literal["save"], *args: Any) -> None: ...

    @overload
    async def _storage(self, action: Literal["reserve"], *args: Any) -> tuple[Record, bool]: ...

    @overload
    async def _storage(self, action: Literal["idem"], *args: Any) -> tuple[str, Record] | None: ...

    async def _storage(self, action: str, *args: Any) -> StorageResult:
        if not self.started:
            raise BrowserbaseError("service_unavailable" if self.enabled() else "not_enabled", 503)
        return await asyncio.to_thread(self._db, action, *args)

    async def _save(self, data):
        data["updated_at"] = datetime.now(UTC).isoformat()
        await self._storage("save", data)

    async def start(self):
        if not self.enabled() or self.started:
            return
        async with self.lock:
            if self.started:
                return
            try:
                import fcntl

                self.path.parent.mkdir(parents=True, exist_ok=True)
                lease = self.path.with_suffix(".lock").open("a+b")
                os.chmod(self.path.with_suffix(".lock"), 0o600)
                try:
                    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    lease.close()
                    raise BrowserbaseError("service_already_running", 503) from None
                self.lease = lease
            except ImportError:
                raise BrowserbaseError("process_lock_unavailable", 503) from None
            try:
                await asyncio.to_thread(self._init_db)
            except BaseException:
                self.lease.close()
                self.lease = None
                raise
            self.started = True
            for data in await self._storage("held"):
                if data.get("session_id"):
                    data["session_closed"] = await self._release(data["session_id"])
                    if data["session_closed"]:
                        data["session_expires_at"] = None
                if data["status"] not in _TERMINAL:
                    data["status"] = "failed"
                    data["last_error"] = "interrupted_by_restart"
                await self._save(data)

    async def aclose(self):
        self.closing = True
        if self.admissions:
            await asyncio.gather(*tuple(self.admissions), return_exceptions=True)
        tasks = list(self.tasks.items())
        for run_id, task in tasks:
            if run_id not in self.cancel_requested:
                self.cancel_requested.add(run_id)
                task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        if self.cleanups:
            await asyncio.gather(*list(self.cleanups.values()), return_exceptions=True)
        # A task cancelled before its first instruction cannot execute its finally.
        if self.started:
            for data in await self._storage("active"):
                if data.get("session_id"):
                    data["session_closed"] = await self._release(data["session_id"])
                data["status"] = "cancelled"
                data["last_error"] = None
                await self._save(data)
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        self.started = False

    async def _request(self, method: str, path: str, body=None):
        key = os.environ.get("BROWSERBASE_API_KEY", "")
        if not key:
            raise BrowserbaseError("provider_unconfigured", 503)
        try:
            async with self.client_factory() as client:
                response = await client.request(method, path, json=body, headers={"X-BB-API-Key": key})
                if response.status_code >= 400:
                    raise BrowserbaseError("provider_request_failed", 502)
                result = response.json()
                if not isinstance(result, (dict, list)):
                    raise BrowserbaseError("invalid_provider_response", 502)
                return result
        except BrowserbaseError:
            raise
        except Exception:
            raise BrowserbaseError("provider_request_failed", 502) from None

    async def status(self):
        configured = bool(os.environ.get("BROWSERBASE_API_KEY")) and self.enabled()
        state = {
            "configured": configured,
            "available": False,
            "reason": None,
            "browser_minutes": None,
            "monthly_minute_limit": None,
            "remaining_minutes": None,
            "mode": MODE,
            "limits": {"max_pages": MAX_PAGES, "session_timeout_seconds": SESSION_TIMEOUT, "max_sessions_per_owner": 1, "max_active_sessions": MAX_ACTIVE_SESSIONS},
        }
        if not self.enabled():
            state["reason"] = "not_enabled"
            return state
        if not configured:
            state["reason"] = "provider_unconfigured"
            return state
        try:
            limit = int(os.environ.get("MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT", "0"))
            if limit < SESSION_TIMEOUT // 60:
                raise ValueError
        except ValueError:
            state["reason"] = "monthly_limit_unverified"
            return state
        state["monthly_minute_limit"] = limit
        if self.browser_runner is _render_snapshots:
            import importlib.util

            if importlib.util.find_spec("playwright") is None:
                state["reason"] = "browser_dependency_missing"
                return state
        try:
            projects = await self._request("GET", "/v1/projects")
            if not isinstance(projects, list) or not projects or len(projects) > 20:
                raise BrowserbaseError("organization_usage_unverified", 503)
            project_ids: list[str] = []
            for project in projects:
                project_id = project.get("id") if isinstance(project, dict) else None
                if not isinstance(project_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", project_id):
                    raise BrowserbaseError("organization_usage_unverified", 503)
                project_ids.append(project_id)
            if len(set(project_ids)) != len(project_ids):
                raise BrowserbaseError("organization_usage_unverified", 503)
            # Plan quota is shared across projects; sum every key-visible project.
            total = 0
            for project_id in project_ids:
                usage = await self._request("GET", f"/v1/projects/{quote(project_id, safe='')}/usage")
                minutes = usage.get("browserMinutes") if isinstance(usage, dict) else None
                if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 0 or not minutes < float("inf"):
                    raise BrowserbaseError("organization_usage_unverified", 503)
                total += minutes
            state["browser_minutes"] = total
            state["remaining_minutes"] = max(0, limit - total)
            state["available"] = state["remaining_minutes"] >= SESSION_TIMEOUT // 60
            state["reason"] = None if state["available"] else "browser_minutes_exhausted"
        except BrowserbaseError as error:
            state["reason"] = error.code
        return state

    async def create(self, owner: str, urls: list[str], title: str, idempotency_key: str, *, browser_runner: Callable | None = None, extension_id: str | None = None):
        # These keyword arguments are an internal gateway seam, never public
        # request fields. Keep the room's existing non-AI renderer unchanged.
        if extension_id is not None:
            try:
                if not isinstance(extension_id, str) or str(uuid.UUID(extension_id)) != extension_id:
                    raise ValueError
            except (ValueError, AttributeError):
                raise BrowserbaseError("invalid_server_extension", 503) from None
            if browser_runner is None:
                raise BrowserbaseError("stagehand_runner_required", 503)
        elif browser_runner is not None:
            raise BrowserbaseError("stagehand_extension_required", 503)
        if not self.enabled():
            raise BrowserbaseError("not_enabled", 503)
        if not os.environ.get("BROWSERBASE_API_KEY"):
            raise BrowserbaseError("provider_unconfigured", 503)
        await self.start()
        if self.closing:
            raise BrowserbaseError("service_stopping", 503)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128 or not idempotency_key.strip():
            raise BrowserbaseError("invalid_idempotency_key")
        if not 1 <= len(urls) <= MAX_PAGES:
            raise BrowserbaseError("invalid_page_count")
        normalized = [public_https_url(url) for url in urls]
        if len(set(normalized)) != len(normalized):
            raise BrowserbaseError("duplicate_public_url")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise BrowserbaseError("invalid_title")
        title = title.strip()
        identity = [normalized, title]
        if extension_id is not None:
            identity.append({"extension_id": extension_id, "mode": "stagehand_v4_public_snapshot"})
        fingerprint = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        async with self.lock:
            previous = await self._storage("idem", owner, idempotency_key)
            if previous:
                if previous[0] != fingerprint:
                    raise BrowserbaseError("idempotency_conflict", 409)
                return previous[1]
            state = await self.status()
            if state["available"]:
                # The provider's reported browserMinutes lags real usage, so a
                # session admitted moments ago (this owner or another) is not
                # yet reflected there. Reserve its worst-case cost, and cap
                # total concurrency, before trusting the provider's figure.
                active = await self._storage("active")
                if len(active) >= MAX_ACTIVE_SESSIONS:
                    state = {**state, "available": False, "reason": "browser_minutes_exhausted"}
                elif active and state["remaining_minutes"] is not None:
                    reserved_minutes = len(active) * RESERVED_MINUTES_PER_SESSION
                    if state["remaining_minutes"] - reserved_minutes < SESSION_TIMEOUT // 60:
                        state = {**state, "available": False, "reason": "browser_minutes_exhausted"}
            if not state["available"]:
                raise BrowserbaseError(state["reason"] or "provider_unavailable", 429 if state["reason"] == "browser_minutes_exhausted" else 503)
            now = datetime.now(UTC).isoformat()
            data = {
                "id": str(uuid.uuid4()),
                "title": title,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "last_error": None,
                "urls": normalized,
                "pages": [],
                "session_id": None,
                "session_expires_at": None,
                "replay_url": None,
                "session_closed": None,
                "browser_adapter": {"mode": "stagehand_v4_public_snapshot" if extension_id is not None else MODE, "ai_inference": extension_id is not None, "extension_id": extension_id, "keep_alive": extension_id is not None},
                "usage": {"browser_minutes": None, "elapsed_seconds": 0, "cost_usd": None},
            }
            cancelled = False

            async def admit():
                reserved, created = await self._storage("reserve", owner, idempotency_key, fingerprint, data)
                if created:
                    if cancelled or self.closing:
                        reserved["status"] = "cancelled"
                        await self._save(reserved)
                    else:
                        task = asyncio.create_task(self._run(owner, reserved, browser_runner=browser_runner, extension_id=extension_id), name=f"browserbase-research-{reserved['id']}")
                        self.tasks[reserved["id"]] = task
                        task.add_done_callback(lambda _task: self.tasks.pop(reserved["id"], None))
                return reserved, created

            admission = asyncio.create_task(admit(), name=f"browserbase-admission-{data['id']}")
            self.admissions.add(admission)
            admission.add_done_callback(self.admissions.discard)
            try:
                reserved, _created = await asyncio.shield(admission)
                return reserved
            except asyncio.CancelledError:
                # A worker thread cannot be cancelled after durable reservation.
                # Drain it before releasing ownership or allowing another key.
                cancelled = True
                while not admission.done():
                    try:
                        await asyncio.shield(admission)
                    except asyncio.CancelledError:
                        continue
                if not admission.cancelled() and admission.exception() is None:
                    reserved, created = admission.result()
                    if created and reserved["status"] not in _TERMINAL:
                        compensation = asyncio.create_task(self.cancel(owner, reserved["id"]))
                        while not compensation.done():
                            try:
                                await asyncio.shield(compensation)
                            except asyncio.CancelledError:
                                continue
                        compensation.result()
                raise

    async def _release(self, session_id: str) -> bool:
        try:
            await self._request("POST", f"/v1/sessions/{session_id}", {"status": "REQUEST_RELEASE"})
        except BrowserbaseError:
            # Browser disconnect may already have completed the session; read back.
            pass
        try:
            for _ in range(3):
                result = await self._request("GET", f"/v1/sessions/{session_id}")
                if isinstance(result, dict) and result.get("id") == session_id and result.get("status") in ("COMPLETED", "ERROR", "TIMED_OUT"):
                    return True
                await asyncio.sleep(0.25)
        except BrowserbaseError:
            pass
        return False

    async def _run(self, owner: str, data: dict, *, browser_runner: Callable | None = None, extension_id: str | None = None):
        started = time.monotonic()
        phase = "public_page_fetch_failed"
        try:
            data["status"] = "running"
            await self._save(data)
            async with asyncio.timeout(SESSION_TIMEOUT):
                pages = []
                for index, url in enumerate(data["urls"]):
                    evidence = await self.fetcher(url)
                    evidence.update({"index": index, "screenshot_url": None, "source_mode": MODE})
                    pages.append(evidence)
                data["pages"] = pages
                await self._save(data)
                # Recheck quota after fetching; never retry uncertain paid creation.
                state = await self.status()
                if not state["available"]:
                    raise BrowserbaseError(state["reason"] or "provider_unavailable", 503)
                phase = "provider_create_uncertain"
                # Persist before dispatch: a lost response or process death must
                # retain ownership through the latest possible session timeout.
                data["session_expires_at"] = time.time() + CREATE_REQUEST_TIMEOUT + SESSION_TIMEOUT
                await self._save(data)
                async with asyncio.timeout(CREATE_REQUEST_TIMEOUT):
                    # Stagehand discovery and SDK attachment are separate CDP
                    # connections. Paid-plan keepAlive prevents disconnects
                    # ending this service-owned session during their handoff;
                    # the same finite TTL and explicit release/readback remain.
                    session_settings = {"timeout": SESSION_TIMEOUT, "keepAlive": browser_runner is not None, "proxies": False, "browserSettings": {"recordSession": True}, "userMetadata": {"purpose": MODE, "momobot_run": data["id"]}}
                    if extension_id is not None:
                        session_settings["extensionId"] = extension_id
                    session = await self._request("POST", "/v1/sessions", session_settings)
                if not isinstance(session, dict):
                    raise BrowserbaseError("invalid_provider_response", 502)
                session_id = session.get("id")
                if not isinstance(session_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", session_id):
                    raise BrowserbaseError("invalid_provider_response", 502)
                data["session_id"] = session_id
                data["session_expires_at"] = time.time() + SESSION_TIMEOUT
                data["replay_url"] = f"https://www.browserbase.com/sessions/{session_id}"
                await self._save(data)
                connect_url = session.get("connectUrl", "")
                # Pending sessions may omit their URL until the browser is ready.
                for _ in range(10):
                    if connect_url:
                        break
                    await asyncio.sleep(0.5)
                    session = await self._request("GET", f"/v1/sessions/{session_id}")
                    if not isinstance(session, dict):
                        raise BrowserbaseError("invalid_provider_response", 502)
                    connect_url = session.get("connectUrl", "")
                    if session.get("status") in ("COMPLETED", "ERROR", "TIMED_OUT"):
                        break
                try:
                    parsed = urlsplit(connect_url)
                    port = parsed.port
                    query_sessions = [value for key, value in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=64) if key == "sessionId"]
                except (TypeError, ValueError):
                    raise BrowserbaseError("invalid_provider_connection", 502) from None
                if (
                    parsed.scheme != "wss"
                    or parsed.hostname not in ALLOWED_CONNECT_HOSTS
                    or port not in (None, 443)
                    or parsed.username is not None
                    or parsed.password is not None
                    or "#" in connect_url
                    or query_sessions
                    and query_sessions != [session_id]
                ):
                    raise BrowserbaseError("invalid_provider_connection", 502)
                phase = "browser_render_failed"
                # connectUrl is an opaque provider-owned transport credential.
                # Bind a custom Stagehand runner to the explicit create receipt;
                # never recover its lease identity from URL syntax.
                screenshots = await browser_runner(connect_url, pages, session_id=session_id) if browser_runner is not None else await self.browser_runner(connect_url, pages)
                if len(screenshots) != len(pages):
                    raise BrowserbaseError("browser_render_failed", 502)
                for index, screenshot in enumerate(screenshots):
                    if not isinstance(screenshot, bytes) or not screenshot.startswith(_PNG) or len(screenshot) > MAX_SCREENSHOT_BYTES:
                        raise BrowserbaseError("invalid_screenshot", 502)
                    target = self.artifact_dir / f"{data['id']}-{index}.png"
                    await asyncio.to_thread(target.write_bytes, screenshot)
                    await asyncio.to_thread(os.chmod, target, 0o600)
                    pages[index]["screenshot_url"] = f"/api/browserbase/research/{data['id']}/pages/{index}/screenshot"
                data["status"] = "completed"
                data["last_error"] = None
        except asyncio.CancelledError:
            data["status"] = "cancelled"
            data["last_error"] = None
        except TimeoutError:
            data["status"] = "failed"
            data["last_error"] = "provider_create_uncertain" if phase == "provider_create_uncertain" else "research_timeout"
        except BrowserbaseError as error:
            data["status"] = "failed"
            data["last_error"] = error.code
        except Exception as error:
            data["status"] = "failed"
            # Keep worker failures actionable without persisting provider
            # exception text, connection URLs, API keys or model prompts.
            safe_worker_codes = {
                "invalid_provider_endpoint",
                "invalid_browser_snapshot",
                "browser_worker_not_installed",
                "browser_worker_identity_mismatch",
                "browser_worker_protocol_error",
                "stagehand_extension_unavailable",
                "browser_operation_failed",
                "browser_model_input_invalid",
                "browser_model_call_limit",
                "browser_worker_failed",
                "browser_session_unavailable",
                "browser_cleanup_unconfirmed",
                "browser_transport_failed",
                "stagehand_extension_inspection_failed",
                "stagehand_runtime_incompatible",
                "stagehand_operation_timeout",
                "stagehand_initialization_failed",
                "browser_snapshot_render_failed",
                "browser_snapshot_capture_failed",
                "stagehand_observation_failed",
                "stagehand_extraction_failed",
                "browser_cleanup_failed",
            }
            code = getattr(error, "code", None)
            data["last_error"] = code if isinstance(code, str) and code in safe_worker_codes else phase
        finally:
            cleanup = asyncio.create_task(self._finish_run(data, started))
            self.cleanups[data["id"]] = cleanup
            cleanup.add_done_callback(lambda _task: self.cleanups.pop(data["id"], None))
            await asyncio.shield(cleanup)

    async def _finish_run(self, data: dict, started: float):
        if data.get("session_id"):
            try:
                async with asyncio.timeout(35):
                    data["session_closed"] = await self._release(data["session_id"])
            except TimeoutError:
                data["session_closed"] = False
            if data["session_closed"]:
                data["session_expires_at"] = None
        data["usage"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        await self._save(data)

    async def wait_for_run(self, run_id: str):
        task = self.tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def snapshot(self, owner: str, run_id: str):
        await self.start()
        return await self._storage("get", run_id, owner)

    async def list_runs(self, owner: str):
        await self.start()
        return [{key: row[key] for key in ("id", "title", "status", "created_at", "updated_at", "last_error")} for row in await self._storage("list", owner)]

    async def cancel(self, owner: str, run_id: str):
        data = await self.snapshot(owner, run_id)
        task = self.tasks.get(run_id)
        if task is not None and data["status"] not in _TERMINAL:
            if run_id not in self.cancel_requested:
                self.cancel_requested.add(run_id)
                task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    raise
                # Handle a queued task cancelled before its first instruction.
                latest = await self._storage("get", run_id, owner)
                if latest["status"] not in _TERMINAL:
                    latest["status"] = "cancelled"
                    latest["last_error"] = None
                    await self._save(latest)
        return await self.snapshot(owner, run_id)

    async def screenshot(self, owner: str, run_id: str, index: int):
        data = await self.snapshot(owner, run_id)
        if not 0 <= index < len(data["pages"]) or not data["pages"][index].get("screenshot_url"):
            raise BrowserbaseError("not_found", 404)
        target = self.artifact_dir / f"{data['id']}-{index}.png"
        try:
            content = await asyncio.to_thread(target.read_bytes)
            if not content.startswith(_PNG) or len(content) > MAX_SCREENSHOT_BYTES:
                raise BrowserbaseError("not_found", 404)
            return content
        except OSError:
            raise BrowserbaseError("not_found", 404) from None
