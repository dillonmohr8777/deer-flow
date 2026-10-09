#!/usr/bin/env python3
"""Post the canonical client registry to a running Gateway (Momentum Phase 2 item 3).

``POST /api/clients/import`` is admin-only and organization-scoped to the
caller's active workspace, so this script logs in (email/password, matching
``POST /api/v1/auth/login/local``), carries the session + CSRF cookies the
Gateway issues, and posts the registry file's JSON content verbatim -- the
endpoint reads only ``{"clients": [...]}`` and ignores the rest of the
envelope.

The registry file itself lives outside this repository
(``client-operations/registry/clients.json``); this operator-run script is
the only thing that reads it from that path -- the endpoint never does.

Usage:
    python scripts/import_client_registry.py --file /path/to/clients.json \\
        --base-url http://localhost:8001 --email you@example.com

The password is read from $DEER_FLOW_ADMIN_PASSWORD, or prompted if unset.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _login(opener: urllib.request.OpenerDirector, base_url: str, email: str, password: str) -> None:
    body = urlencode({"username": email, "password": password, "remember_me": "true"}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/v1/auth/login/local",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(request) as response:
        if response.status >= 400:
            raise SystemExit(f"Login failed: HTTP {response.status}")


def _csrf_token(jar: http.cookiejar.CookieJar, base_url: str) -> str:
    for cookie in jar:
        if cookie.name == CSRF_COOKIE_NAME:
            return cookie.value or ""
    raise SystemExit(f"Login succeeded but no {CSRF_COOKIE_NAME!r} cookie was issued; is {base_url} a real Gateway?")


def _import(opener: urllib.request.OpenerDirector, base_url: str, csrf_token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/clients/import",
        data=body,
        headers={"Content-Type": "application/json", CSRF_HEADER_NAME: csrf_token},
        method="POST",
    )
    try:
        with opener.open(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Import failed: HTTP {exc.code} {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, help="Path to the registry JSON file (clients.json)")
    parser.add_argument("--base-url", default=os.environ.get("DEER_FLOW_BASE_URL", "http://localhost:8001"))
    parser.add_argument("--email", required=True, help="Admin account email")
    args = parser.parse_args()

    password = os.environ.get("DEER_FLOW_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

    with open(args.file, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "clients" not in payload:
        raise SystemExit(f"{args.file} does not look like a registry file (no top-level 'clients' key)")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    _login(opener, args.base_url, args.email, password)
    csrf_token = _csrf_token(jar, args.base_url)
    result = _import(opener, args.base_url, csrf_token, payload)

    print(f"created={result['created']} updated={result['updated']} skipped={result['skipped']}")
    if result["skipped_ids"]:
        print(f"skipped ids: {', '.join(result['skipped_ids'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
