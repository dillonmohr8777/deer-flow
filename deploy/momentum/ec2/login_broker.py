"""Host-only 1Password login broker for MomoBot's isolated Browserbase MCP.

The MCP sends one JSON line: {"session": <its Browserbase session id>, "item": <1Password item title>}.
The broker resolves the item with the host-only 1Password service account, attaches to that exact
Browserbase session, fills the login form on a page whose host matches the item's website, and answers
with a status and the page host/path only. Credential values never leave this process: not to the
socket, the gateway, the model, stdout or the journal.

Guards: the item must be a Login tagged `momobot`; the session must be RUNNING in our project and owned
by the isolated MCP; the page host must equal (or be a subdomain of) one of the item's websites.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

SOCKET = os.environ.get("MOMOBOT_LOGIN_SOCKET", "/var/lib/docker/volumes/momobot-prod_gateway-data/_data/run/login.sock")
TOKEN_PARAM = os.environ.get("MOMOBOT_OP_TOKEN_PARAM", "/momobot/prod/OP_SERVICE_ACCOUNT_TOKEN")
CLIENTS_PARAM = "/momobot/prod/OP_CLIENTS_TOKEN"  # optional read-only service account for the shared Clients vault
TAG = "momobot"
OWNER = "momobot-isolated-mcp"
UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
EDITABLE = ":not([readonly]):not([disabled]):not([type=hidden])"
# Priority order, best first: a catch-all text box is the last resort, never a search box.
USER = [f"input{s}{EDITABLE}" for s in ("[autocomplete=username]", "[type=email]", "[name*=email i]", "[id*=email i]",
                                        "[name*=user i]", "[id*=user i]", "[name=login]")] + \
       [f"form:has(input[type=password]) input[type=text]{EDITABLE}:not([name*=search i])",
        f"form:not([role=search]) input[type=text]{EDITABLE}:not([name*=search i])"]
PASS = f"input[type=password]{EDITABLE}"
OTP = [f"input{s}{EDITABLE}" for s in ("[autocomplete=one-time-code]", "[name*=otp i]", "[id*=otp i]", "[name*=totp i]",
                                       "[name*=mfa i]", "[name*=2fa i]", "[name*=code i]", "[id*=code i]")]
OTP_WORDS = ("verification code", "authentication code", "security code", "two-factor", "2-step", "two-step",
             "one-time", "authenticator", "6-digit")

def host_allowed(page_url: str, websites: list[str]) -> bool:
    host = (urlsplit(page_url).hostname or "").lower()
    allowed = {(urlsplit(w if "://" in w else "https://" + w).hostname or "").lower() for w in websites}
    return urlsplit(page_url).scheme == "https" and any(h and (host == h or host.endswith("." + h)) for h in allowed)


def where(page_url: str) -> str:
    parts = urlsplit(page_url)
    return f"{parts.hostname or ''}{parts.path}"  # no query or fragment: tokens can live there


async def _visible(page, selectors, timeout_ms: int):
    """First visible match, trying selectors in priority order (DOM order would let a header box win)."""
    selectors = [selectors] if isinstance(selectors, str) else selectors
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while True:
        for sel in selectors:
            loc = page.locator(sel).filter(visible=True)
            if await loc.count():
                return loc.first
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.25)


async def fill_login(page, secret, allowed) -> str:
    """Username (one or two steps), password, then the 1Password OTP code on a real 2FA prompt.
    allowed(page) is re-checked before EVERY fill: a redirect between steps must not receive a value."""
    async def put(field, name):
        if not allowed(page):
            raise PermissionError("page left the item's website")
        await field.fill(await secret(name))

    password = await _visible(page, PASS, 4000)
    user = await _visible(page, USER, 1000)
    if user is not None:
        await put(user, "username")
        if password is None:
            await user.press("Enter")
            password = await _visible(page, PASS, 12000)
    if password is None:
        return "login_form_not_found"
    await put(password, "password")
    await password.press("Enter")
    await page.wait_for_timeout(3000)
    text = (await page.locator("body").inner_text(timeout=5000)).lower()
    if await _visible(page, PASS, 500) is None and any(w in text for w in OTP_WORDS):
        otp = await _visible(page, OTP, 5000)
        if otp is not None:
            try:
                await put(otp, "one-time password?attribute=otp")
            except LookupError:
                return "needs_2fa"
            await otp.press("Enter")
            await page.wait_for_timeout(3000)
    still = await _visible(page, PASS, 500)
    if still is not None:
        await still.fill("")  # never leave a typed password in the page for a later snapshot
        return "password_form_still_visible"
    return "submitted"


class Broker:
    def __init__(self, ops: list, bb_key: str, project: str, connect=None):
        self.ops, self.bb_key, self.project = ops, bb_key, project
        self.connect = connect
        self.lock = asyncio.Lock()  # ponytail: one login at a time on this host; per-session locks if it ever queues
        self._index, self._index_at = None, 0.0

    async def items(self) -> dict[str, tuple | None]:
        """title -> (account, vault, item, websites); None marks a title used by two items (refused, never guessed).
        Cached 60 s so retries cannot burn the service-account rate limit secrets.sh also needs."""
        now = asyncio.get_running_loop().time()
        if self._index is not None and now - self._index_at < 60:
            return self._index
        out = {}
        for op in self.ops:  # each service account sees only its own vaults
            for vault in await op.vaults.list():
                for item in await op.items.list(vault.id):
                    if str(getattr(item.category, "value", item.category)).upper() == "LOGIN" and TAG in (item.tags or []):
                        entry = (op, vault.id, item.id, [w.url for w in item.websites or []])
                        out[item.title] = None if item.title in out else entry
        self._index, self._index_at = out, now
        return out

    def _session(self, session_id: str) -> dict:
        req = urllib.request.Request("https://api.browserbase.com/v1/sessions/" + session_id, headers={"X-BB-API-Key": self.bb_key})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)

    async def login(self, request: dict) -> dict:
        session_id, title = request.get("session"), request.get("item")
        if not isinstance(session_id, str) or not UUID.fullmatch(session_id) or not isinstance(title, str) or len(title) > 200:
            return {"status": "bad_request"}
        session = await asyncio.to_thread(self._session, session_id)
        if session.get("status") != "RUNNING" or session.get("projectId") != self.project or (session.get("userMetadata") or {}).get("owner") != OWNER:
            return {"status": "session_not_owned"}
        items = await self.items()
        if title not in items:
            return {"status": "unknown_item", "available": sorted(items)}
        if items[title] is None:
            return {"status": "ambiguous_item", "note": "two 1Password items share this title; rename one"}
        op, vault_id, item_id, websites = items[title]
        ref = f"op://{vault_id}/{item_id}/"

        async def secret(field: str) -> str:
            try:
                return await op.secrets.resolve(ref + field)
            except Exception:  # noqa: BLE001 - provider text can echo values
                raise LookupError(field.split("?")[0]) from None

        url = f"wss://connect.browserbase.com?apiKey={self.bb_key}&sessionId={session_id}"
        async with self.lock:
            async with self.connect() as pw:  # leaving the block drops the CDP link without closing the browser
                browser = await pw.chromium.connect_over_cdp(url, timeout=30000)
                pages = [p for ctx in browser.contexts for p in ctx.pages if host_allowed(p.url, websites)]
                if not pages:
                    return {"status": "open_login_page_first", "hosts": [where(w) for w in websites]}
                page = pages[-1]
                try:
                    status = await fill_login(page, secret, lambda pg: host_allowed(pg.url, websites))
                except PermissionError:
                    status = "stopped_page_left_site"
                return {"status": status, "page": where(page.url)}


async def handle(broker: Broker, reader, writer) -> None:
    try:
        line = await asyncio.wait_for(reader.readline(), 10)
        result = await asyncio.wait_for(broker.login(json.loads(line)), 120)
    except Exception as exc:  # noqa: BLE001 - only the type leaves the broker
        result = {"status": "failed", "error_type": type(exc).__name__}
    print(json.dumps({"login": result.get("status"), "error_type": result.get("error_type")}), flush=True)
    writer.write((json.dumps(result) + "\n").encode())
    with contextlib.suppress(Exception):
        await writer.drain()
        writer.close()


def ssm_token(name: str) -> str | None:
    r = subprocess.run(["aws", "ssm", "get-parameter", "--region", os.environ.get("AWS_REGION", "us-east-2"), "--name", name,
                        "--with-decryption", "--query", "Parameter.Value", "--output", "text"],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout.strip()
    return out if r.returncode == 0 and out.startswith("ops_") else None


async def main() -> None:
    from onepassword import Client
    from playwright.async_api import async_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render_secrets import BROWSERBASE_REFS

    tokens = [os.environ.get("OP_SERVICE_ACCOUNT_TOKEN") or ssm_token(TOKEN_PARAM), ssm_token(CLIENTS_PARAM)]
    if not tokens[0]:
        raise ValueError("service-account token missing")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ops = [await Client.authenticate(auth=t, integration_name="MomoBot EC2 login broker", integration_version="1.0.0")
               for t in tokens if t]
        bb_key = await ops[0].secrets.resolve(BROWSERBASE_REFS["BROWSERBASE_API_KEY"])
        project = await ops[0].secrets.resolve(BROWSERBASE_REFS["BROWSERBASE_PROJECT_ID"])
    broker = Broker(ops, bb_key, project, connect=async_playwright)
    sock = Path(SOCKET)
    sock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    sock.unlink(missing_ok=True)
    old = os.umask(0o177)
    server = await asyncio.start_unix_server(lambda r, w: handle(broker, r, w), path=str(sock))
    os.umask(old)
    print(json.dumps({"broker": "ready", "accounts": len(ops), "items": len(await broker.items())}), flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - SDK/AWS text can carry secrets
        print(json.dumps({"broker": "failed", "error_type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
