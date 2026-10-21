#!/usr/bin/env python3
"""MomoBot desktop bridge runner (stdlib only), run by launchd on the Mac host.

Polls the Gateway outbound (nothing listens on this machine), leases one approved
``desktop`` fleet item at a time, runs ``claude -p <prompt> --model haiku`` limited
to the client's folder, and reports the result through the fleet lease routes
(``/api/fleet/work/{claim,renew,running,finalize}``).

Environment (values are never printed):
    MOMOBOT_GATEWAY_URL      Gateway base URL, e.g. https://momobot.example.com
    MOMOBOT_HOST_KEY         X-DeerFlow-Internal-Token for this host
    MOMOBOT_DELEGATION_ID    X-DeerFlow-Delegation-Id (an org delegation with fleet:work)
    MOMOBOT_RUNNER_CONFIG    JSON file (default ~/.momobot/desktop-runner.json):
                             {"clients": {"<client_id>": "/abs/client/folder"},
                              "allowed_tools": ["Read", "Grep", "Glob", "Edit", "Write"],
                              "claude_bin": "claude", "timeout_seconds": 1200}
    MOMOBOT_STOP_FILE        Kill switch (default ~/.momobot/STOP); while it exists nothing runs
    MOMOBOT_QUIET_HOURS_BIN  Gate command (default ~/.local/bin/quiet-hours); exit 0 = quiet
                             hours, so the runner claims nothing and kills nothing new

Usage: momobot_desktop_runner.py [--once] [--dry-run]
    --dry-run  print the gates, the client mapping and the claude command for a sample
               prompt; never contacts the Gateway or starts claude.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HOME = Path.home()
DEFAULT_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write"]  # no Bash: a Slack prompt must not get a shell
POLL_SECONDS = 30
RENEW_SECONDS = 30
MAX_RESULT_CHARS = 100_000


def _csrf_pair() -> dict[str, str]:
    value = secrets.token_urlsafe(16)
    return {"Cookie": f"csrf_token={value}", "X-CSRF-Token": value}


def load_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("MOMOBOT_RUNNER_CONFIG") or HOME / ".momobot/desktop-runner.json")
    cfg = json.loads(p.read_text()) if p.exists() else {}
    cfg.setdefault("clients", {})
    cfg.setdefault("allowed_tools", DEFAULT_TOOLS)
    cfg.setdefault("claude_bin", "claude")
    cfg.setdefault("timeout_seconds", 20 * 60)
    return cfg


def stop_file() -> Path:
    return Path(os.environ.get("MOMOBOT_STOP_FILE") or HOME / ".momobot/STOP")


def in_quiet_hours() -> bool:
    """True when the quiet-hours gate exits 0. A missing or broken gate fails closed (counts as quiet)."""
    gate = os.environ.get("MOMOBOT_QUIET_HOURS_BIN") or str(HOME / ".local/bin/quiet-hours")
    try:
        return subprocess.run([gate], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True


def api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the Gateway. Errors carry the status only, never headers or the key."""
    request = urllib.request.Request(
        os.environ["MOMOBOT_GATEWAY_URL"].rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-DeerFlow-Internal-Token": os.environ["MOMOBOT_HOST_KEY"],
            "X-DeerFlow-Delegation-Id": os.environ["MOMOBOT_DELEGATION_ID"],
            # The Gateway's CSRF double-submit check covers internal callers too; a per-call
            # random pair satisfies it (it guards browsers, the internal token guards this).
            **_csrf_pair(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - operator-supplied https URL
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}") from None


def claude_argv(cfg: dict[str, Any], prompt: str, folder: str) -> list[str]:
    return [cfg["claude_bin"], "-p", prompt, "--model", "haiku", "--allowedTools", ",".join(cfg["allowed_tools"]), "--add-dir", folder]


def run_claude(cfg: dict[str, Any], prompt: str, folder: str, *, on_tick=None) -> tuple[bool, str]:
    """Run claude in the client folder. Kills it on the STOP file or the timeout. Returns (succeeded, text)."""
    proc = subprocess.Popen(claude_argv(cfg, prompt, folder), cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)  # noqa: S603
    started = last_tick = time.monotonic()
    while proc.poll() is None:
        now = time.monotonic()
        reason = "STOP file present" if stop_file().exists() else "timed out" if now - started > cfg["timeout_seconds"] else None
        if reason is None and now - last_tick >= RENEW_SECONDS:
            last_tick = now
            if in_quiet_hours():
                reason = "quiet hours began"
            elif on_tick and not on_tick():
                reason = "lease lost or job cancelled"
        if reason:
            os.killpg(proc.pid, signal.SIGKILL)  # the whole tree: claude may have spawned children
            proc.communicate()
            return False, f"Killed: {reason}"
        time.sleep(0.2)
    out, err = proc.communicate()
    return proc.returncode == 0, (out if proc.returncode == 0 else f"claude exited {proc.returncode}: {err.strip()[-500:]}")[:MAX_RESULT_CHARS]


def handle_item(cfg: dict[str, Any], item: dict[str, Any], owner: str) -> str:
    item_id = item["id"]
    lease = {"lease_owner": owner}
    folder = cfg["clients"].get(item.get("client_id") or "")
    if item.get("lane") != "desktop" or item.get("approval_state") != "approved" or not folder or not Path(folder).is_dir():
        reason = "not an approved desktop job" if item.get("approval_state") != "approved" or item.get("lane") != "desktop" else "no folder mapped for this client"
        api("POST", f"/api/fleet/work/{item_id}/finalize", {**lease, "succeeded": False, "error": reason})
        return f"refused:{reason}"
    api("POST", f"/api/fleet/work/{item_id}/running", lease)
    ok, text = run_claude(cfg, item["prompt"], folder, on_tick=lambda: bool((r := api("POST", f"/api/fleet/work/{item_id}/renew", lease)).get("valid")) and not r.get("cancel_requested"))
    api("POST", f"/api/fleet/work/{item_id}/finalize", {**lease, "succeeded": ok, "result": text if ok else None, "error": None if ok else text[:4000], "model_name": "haiku"})
    return "done" if ok else "failed"


def run_once(cfg: dict[str, Any]) -> str:
    if stop_file().exists():
        return "stopped"
    if in_quiet_hours():
        return "quiet"
    owner = f"{socket.gethostname()}:desktop"
    items = api("POST", "/api/fleet/work/claim", {"lease_owner": owner, "lanes": ["desktop"], "limit": 1}).get("items", [])
    return handle_item(cfg, items[0], owner) if items else "idle"


def dry_run(cfg: dict[str, Any]) -> int:
    print(f"stop_file_present={stop_file().exists()} quiet_hours={in_quiet_hours()} timeout_seconds={cfg['timeout_seconds']}")
    print(f"gateway_url_set={bool(os.environ.get('MOMOBOT_GATEWAY_URL'))} host_key_set={bool(os.environ.get('MOMOBOT_HOST_KEY'))} delegation_set={bool(os.environ.get('MOMOBOT_DELEGATION_ID'))}")
    for client, folder in sorted(cfg["clients"].items()):
        print(f"client {client}: {folder} exists={Path(folder).is_dir()}")
        print("  would run:", " ".join(claude_argv(cfg, "<prompt>", folder)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.dry_run:
        return dry_run(cfg)
    missing = [k for k in ("MOMOBOT_GATEWAY_URL", "MOMOBOT_HOST_KEY", "MOMOBOT_DELEGATION_ID") if not os.environ.get(k)]
    if missing:
        print("missing env: " + ", ".join(missing), file=sys.stderr)
        return 2
    while True:
        try:
            state = run_once(cfg)
        except Exception as exc:  # keep polling; the message never includes credentials
            state = f"error:{type(exc).__name__}:{exc}"
        print(time.strftime("%H:%M:%S"), state, flush=True)
        if args.once:
            return 0
        time.sleep(POLL_SECONDS if state in ("idle", "quiet", "stopped") or state.startswith("error") else 1)


if __name__ == "__main__":
    sys.exit(main())
