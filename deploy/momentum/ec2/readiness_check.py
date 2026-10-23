"""Offline tenant canary and read-only nightly S3 restore drill; no app hosting.

Receipts contain only commit, status and counts. This checkout must remain pinned
and its Python/frontend test dependencies must already be installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BUCKET = "momobot-prod-backups-009688440435"
SSH = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-i",
    str(Path.home() / ".ssh/id_ed25519_winpc"),
    "ubuntu@3.20.166.209",
]
TENANT_TESTS = [
    "tests/test_client_workspace_agents.py",
    "tests/test_customer_workspace_migration.py",
    "tests/test_client_route_boundary.py",
    "tests/test_org_isolation_b_threads.py",
    "tests/test_customer_workspace_invitations.py",
    "tests/test_client_portal.py",
]
UI_TESTS = [
    "tests/unit/core/auth/roles.test.ts",
    "tests/unit/components/workspace/role-route-guard.dom.test.tsx",
]


def latest_backup(objects: list[dict], now: dt.datetime) -> dict:
    eligible = [
        o
        for o in objects
        if o["Key"].startswith("nightly/momobot-") and o["Key"].endswith(".tgz")
    ]
    if not eligible:
        raise ValueError("No nightly backup objects")
    latest = max(eligible, key=lambda o: o["LastModified"])
    age = now - dt.datetime.fromisoformat(latest["LastModified"].replace("Z", "+00:00"))
    if not dt.timedelta(0) <= age <= dt.timedelta(hours=36):
        raise ValueError("Latest backup is stale or future-dated")
    if not 0 < latest["Size"] <= 2 * 1024**3:
        raise ValueError("Backup exceeds the 2 GiB download budget or is empty")
    return latest


def run(args: list[str], cwd: Path, env=None) -> None:
    # Test logs are synthetic; backup config and credential values are never printed.
    subprocess.run(args, cwd=cwd, env=env, check=True)


def check(mode: str, python: str, pnpm: str, backup: Path | None) -> None:
    if mode == "tenant":
        env = dict(
            os.environ,
            PYTHONPATH=f"{ROOT / 'backend'}:{ROOT / 'backend/packages/harness'}",
        )
        run([python, "-m", "pytest", *TENANT_TESTS, "-q"], ROOT / "backend", env)
        run([pnpm, "exec", "rstest", "run", *UI_TESTS], ROOT / "frontend")
        return
    from restore_check import verify_backup

    if backup:
        print(json.dumps(verify_backup(backup)))
        return
    with tempfile.TemporaryDirectory(prefix="momo-restore-download-") as temp:
        # 2 GiB download + 4 GiB expanded archive budget + 1 GiB headroom.
        if shutil.disk_usage(temp).free < 7 * 1024**3:
            raise ValueError("Restore needs 7 GiB free scratch space")
        listing = subprocess.run(
            [
                *SSH,
                f"sudo aws s3api list-objects-v2 --region us-east-2 --bucket {BUCKET} --prefix nightly/ --output json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        obj = latest_backup(
            json.loads(listing.stdout).get("Contents", []), dt.datetime.now(dt.UTC)
        )
        # SSH sends shell text; accept only the backup producer's fixed key grammar.
        import re

        if not re.fullmatch(r"nightly/momobot-[0-9]{8}T[0-9]{6}Z\.tgz", obj["Key"]):
            raise ValueError("Unexpected backup key")
        target = Path(temp) / "backup.tgz"
        with target.open("xb") as output:
            subprocess.run(
                [
                    *SSH,
                    f"sudo aws s3 cp s3://{BUCKET}/{obj['Key']} - --region us-east-2 --only-show-errors",
                ],
                check=True,
                stdout=output,
                stderr=subprocess.PIPE,
            )
        if target.stat().st_size != obj["Size"]:
            raise ValueError("Downloaded backup size mismatch")
        print(json.dumps(verify_backup(target)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tenant", "restore"))
    parser.add_argument("--python", default=os.sys.executable)
    parser.add_argument("--pnpm", default="pnpm")
    parser.add_argument(
        "--backup", type=Path, help="Check this local archive instead of reading S3"
    )
    parser.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    receipt = {"at": dt.datetime.now(dt.UTC).isoformat(), "mode": args.mode}
    try:
        receipt["sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT):
            raise ValueError(
                "Tracked checkout changes: refusing to certify a different commit"
            )
        check(args.mode, args.python, args.pnpm, args.backup)
        receipt["status"] = "pass"
    except Exception as exc:
        # Exception type only: provider responses and restored private data stay out of receipts.
        receipt.update(status="fail", error_type=type(exc).__name__)
    args.receipts.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with args.receipts.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt) + "\n")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
