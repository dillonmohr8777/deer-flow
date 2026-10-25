#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
FIELDS = {"schema_version", "job_id", "client_id", "attempt", "command", "timeout_seconds"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_job(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != FIELDS or value["schema_version"] != 1:
        raise ValueError("invalid_job_schema")
    for key in ("job_id", "client_id"):
        if not isinstance(value[key], str) or not ID.fullmatch(value[key]):
            raise ValueError("invalid_job_identity")
    if type(value["attempt"]) is not int or not 1 <= value["attempt"] <= 100:
        raise ValueError("invalid_job_attempt")
    if type(value["timeout_seconds"]) is not int or not 1 <= value["timeout_seconds"] <= 3600:
        raise ValueError("invalid_job_timeout")
    command = value["command"]
    if not isinstance(command, list) or not 1 <= len(command) <= 32 or any(not isinstance(part, str) or not part or len(part) > 8192 for part in command):
        raise ValueError("invalid_job_command")
    if value["job_id"] != os.environ.get("MOMO_JOB_ID") or value["client_id"] != os.environ.get("MOMO_CLIENT_ID"):
        raise ValueError("job_scope_mismatch")
    return value


def main() -> int:
    job_path = Path(sys.argv[1] if len(sys.argv) == 2 else "")
    if job_path != Path("/mnt/data/job.json"):
        raise ValueError("job_path_rejected")
    job = load_job(job_path)
    fingerprint = digest({**job, "attempt": 0})
    root = job_path.parent
    receipt_path = root / "receipts" / f"{job['job_id']}.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("request_sha256") != fingerprint or receipt.get("status") != "completed":
            raise ValueError("duplicate_job_conflict")
        print(json.dumps({"job_id": job["job_id"], "status": "reused", "receipt": str(receipt_path)}))
        return 0
    checkpoint = root / "checkpoints" / f"{job['job_id']}.json"
    atomic_json(checkpoint, {"status": "running", "job_id": job["job_id"], "client_id": job["client_id"], "attempt": job["attempt"], "request_sha256": fingerprint, "started_at": utc_now()})
    timed_out = False
    try:
        result = subprocess.run(job["command"], cwd="/work", stdin=subprocess.DEVNULL, capture_output=True, timeout=job["timeout_seconds"], check=False)
        code = result.returncode
        stdout = result.stdout[:65536]
        stderr = result.stderr[:65536]
    except subprocess.TimeoutExpired as error:
        timed_out = True
        code = 124
        stdout = (error.stdout or b"")[:65536]
        stderr = (error.stderr or b"")[:65536]
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / f"{job['job_id']}.stdout").write_bytes(stdout)
    (root / "logs" / f"{job['job_id']}.stderr").write_bytes(stderr)
    status = "completed" if code == 0 and not timed_out else "failed"
    receipt = {
        "schema_version": 1,
        "status": status,
        "job_id": job["job_id"],
        "client_id": job["client_id"],
        "attempt": job["attempt"],
        "request_sha256": fingerprint,
        "exit_code": code,
        "timed_out": timed_out,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "finished_at": utc_now(),
    }
    if code != 0 or timed_out:
        atomic_json(checkpoint, receipt)
        print(json.dumps({"job_id": job["job_id"], "status": status, "exit_code": code}))
        return 1
    atomic_json(receipt_path, receipt)
    atomic_json(checkpoint, receipt)
    print(json.dumps({"job_id": job["job_id"], "status": status, "receipt_sha256": digest(receipt)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
