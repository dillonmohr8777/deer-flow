#!/usr/bin/env python3
"""Create the agency workflow scheduled tasks on a running Gateway, paused.

Idempotent: tasks are matched by title, so reruns create nothing new. Each new
task is paused right after creation. This script never touches
``scheduler.enabled``; resuming tasks and enabling the scheduler are separate,
manual steps.

Usage:
    python scripts/seed_scheduled_workflows.py --email you@example.com [--base-url URL] [--dry-run]

The password is read from $DEER_FLOW_ADMIN_PASSWORD, or prompted if unset.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import urllib.request
from urllib.parse import urlencode

from deerflow.scheduler.workflow_templates import plan_seed, validate_template, workflow_templates


def seed(call, *, dry_run: bool = False) -> dict[str, list[str]]:
    """``call(method, path, payload|None) -> json``. Returns created/existing titles."""
    for template in workflow_templates():
        validate_template(template)
    existing = {t["title"] for t in call("GET", "/api/scheduled-tasks", None)}
    todo = plan_seed(existing)
    if not dry_run:
        for template in todo:
            task = call("POST", "/api/scheduled-tasks", {k: v for k, v in template.items() if k != "key"})
            call("POST", f"/api/scheduled-tasks/{task['id']}/pause", None)
    return {
        "created": [t["title"] for t in todo],
        "existing": sorted(existing & {t["title"] for t in workflow_templates()}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("DEER_FLOW_BASE_URL", "http://localhost:8001"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    password = os.environ.get("DEER_FLOW_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(
        f"{args.base_url}/api/v1/auth/login/local",
        data=urlencode({"username": args.email, "password": password, "remember_me": "true"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener.open(login).close()
    csrf = next((c.value for c in jar if c.name == "csrf_token"), "")

    def call(method: str, path: str, payload):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            args.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
        )
        with opener.open(req) as resp:
            return json.loads(resp.read() or b"null")

    result = seed(call, dry_run=args.dry_run)
    print(f"{'would create' if args.dry_run else 'created'}={len(result['created'])} existing={len(result['existing'])}")


if __name__ == "__main__":
    main()
