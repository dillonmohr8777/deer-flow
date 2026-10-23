"""Opt-in durable diagnostic exchange. This module never executes a job."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROTOCOL = "momo-pcw-wsl-v1"
ALLOWLIST = (("/usr/bin/true",), ("/usr/bin/false",), ("/usr/bin/uname", "-s"))
MAX_OUTPUT_BYTES = 65536
MAX_MESSAGE_BYTES = 196608
MAX_OUTSTANDING = 32
MAX_RECORDS = 1024
RECEIPT_FIELDS = (
    "id",
    "key_sha256",
    "state",
    "exit_code",
    "start_utc",
    "end_utc",
    "stdout_sha256",
    "stdout_bytes",
    "stdout_truncated",
    "stderr_sha256",
    "stderr_bytes",
    "stderr_truncated",
    "stdout_b64",
    "stderr_b64",
    "duration_seconds",
    "resource_limits",
    "limits_applied",
)
_JOB_ID = re.compile(r"momo-[0-9a-f]{16}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_STATES = {"queued", "claimed", "done", "failed", "unknown", "held"}


class BridgeError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class _Held(BridgeError):
    """A hold must commit even though the caller receives a conflict."""


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def receipt_digest(receipt: dict[str, Any]) -> str:
    canonical = {field: receipt[field] for field in RECEIPT_FIELDS}
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def job_id_for_digest(digest: str) -> str:
    return "momo-" + digest[:16]


def resource_limits(timeout: int) -> dict[str, int]:
    return {"address_space_bytes": 536870912, "cpu_seconds": timeout, "wall_seconds": timeout, "stdout_bytes": MAX_OUTPUT_BYTES, "stderr_bytes": MAX_OUTPUT_BYTES}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise BridgeError("Invalid receipt timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except ValueError:
        raise BridgeError("Invalid receipt timestamp") from None
    return stamp


def validate_command(argv: Any, timeout: Any) -> None:
    if not isinstance(argv, list) or tuple(argv) not in ALLOWLIST or type(timeout) is not int or not 1 <= timeout <= 600:
        raise BridgeError("Only bounded allowlisted diagnostics are accepted", 422)


def validate_receipt(job: dict[str, Any], receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or not set(RECEIPT_FIELDS) <= receipt.keys():
        raise BridgeError("Incomplete diagnostic receipt")
    try:
        if len(compact_json(receipt).encode()) > MAX_MESSAGE_BYTES:
            raise BridgeError("Diagnostic receipt exceeds its bound")
    except (ValueError, TypeError):
        raise BridgeError("Invalid diagnostic receipt JSON") from None
    result = {field: receipt[field] for field in RECEIPT_FIELDS}
    if result["id"] != job["id"] or result["key_sha256"] != job["key_sha256"] or not isinstance(result["state"], str) or result["state"] not in {"done", "failed", "timeout", "held"}:
        raise BridgeError("Diagnostic receipt binding mismatch")
    code, state = result["exit_code"], result["state"]
    if code is not None and (type(code) is not int or not -2147483648 <= code <= 2147483647):
        raise BridgeError("Invalid diagnostic exit code")
    if (state == "done" and code != 0) or (state == "failed" and (code is None or code == 0)):
        raise BridgeError("Diagnostic exit code contradicts state")
    if _timestamp(result["end_utc"]) < _timestamp(result["start_utc"]):
        raise BridgeError("Diagnostic timestamps are reversed")
    duration = result["duration_seconds"]
    if type(duration) not in (int, float) or duration < 0 or duration > sys.float_info.max or not math.isfinite(duration):
        raise BridgeError("Invalid diagnostic duration")
    limits = result["resource_limits"]
    if not isinstance(limits, dict) or any(type(value) is not int for value in limits.values()) or limits != resource_limits(job["timeout"]) or type(result["limits_applied"]) is not bool:
        raise BridgeError("Diagnostic resource limits mismatch")
    if state in {"done", "failed"} and not result["limits_applied"]:
        raise BridgeError("Completed diagnostic has no applied limits")
    for stream in ("stdout", "stderr"):
        encoded, count, truncated = result[stream + "_b64"], result[stream + "_bytes"], result[stream + "_truncated"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_OUTPUT_BYTES + 2) // 3) or type(count) is not int or not 0 <= count <= MAX_OUTPUT_BYTES or type(truncated) is not bool:
            raise BridgeError("Invalid diagnostic output bound")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise BridgeError("Invalid diagnostic output encoding") from None
        if base64.b64encode(raw).decode("ascii") != encoded or len(raw) != count or hashlib.sha256(raw).hexdigest() != result[stream + "_sha256"]:
            raise BridgeError("Diagnostic output hash or size mismatch")
        if truncated and state in {"done", "failed"}:
            raise BridgeError("Partial diagnostic output requires reconciliation")
    return result


class BridgeStore:
    """A private SQLite spool; BEGIN IMMEDIATE fences all process writers."""

    def __init__(self, root: Path):
        self.path = root / "wsl-bridge.sqlite3"

    @classmethod
    def from_environment(cls) -> BridgeStore:
        if os.environ.get("MOMO_WSL_BRIDGE_ENABLED", "").lower() != "true":
            raise BridgeError("WSL bridge is disabled", 503)
        if os.environ.get("DEER_FLOW_AUTH_DISABLED") == "1":
            raise BridgeError("WSL bridge requires authenticated operation", 503)
        root = Path(os.environ.get("MOMO_WSL_BRIDGE_ROOT", ""))
        if not root.is_absolute() or not root.is_dir() or root.resolve() != root or root.is_symlink():
            raise BridgeError("WSL bridge requires an existing absolute persistent root", 503)
        if os.name == "posix" and root.stat().st_mode & 0o077:
            raise BridgeError("WSL bridge root must be operator-owned and private", 503)
        return cls(root)

    @contextmanager
    def _connect(self, *, write: bool = False, create: bool = False):
        if self.path.is_symlink():
            raise BridgeError("WSL bridge store is held", 503)
        if not create and not self.path.exists():
            raise BridgeError("Diagnostic request not found", 404)
        uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw" if write else "?mode=ro")
        conn = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            if create:
                conn.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, state TEXT NOT NULL, record TEXT NOT NULL)")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise BridgeError("WSL bridge schema is held", 503)
                conn.execute("PRAGMA user_version=1")
            elif conn.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise BridgeError("WSL bridge schema is held", 503)
            yield conn
            if write:
                conn.commit()
        except _Held:
            conn.commit()
            raise
        except sqlite3.Error:
            conn.rollback()
            raise BridgeError("WSL bridge store is held", 503) from None
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _record(self, row) -> dict[str, Any]:
        if row is None:
            raise BridgeError("Diagnostic request not found", 404)
        try:
            job_id, state, encoded = row
            record = json.loads(encoded)
            binding, job = record["binding"], record["job"]
            if not isinstance(binding, list) or len(binding) != 5 or binding[0] != "momo-wsl-v1" or any(not isinstance(part, str) or not part or len(part) > 128 for part in binding):
                raise ValueError
            digest = hashlib.sha256(compact_json(binding).encode()).hexdigest()
            expected = self._job(job_id, digest, job["argv"], job["timeout"], job["submitted"])
            if state not in _STATES or not _JOB_ID.fullmatch(job_id) or job_id != job_id_for_digest(digest) or job != expected or type(record["attached"]) is not bool:
                raise ValueError
            if not isinstance(record["storage_user_id"], str) or not record["storage_user_id"] or len(record["storage_user_id"]) > 128 or not _THREAD_ID.fullmatch(binding[3]) or not _REQUEST_ID.fullmatch(binding[4]):
                raise ValueError
            if record["receipt"] is not None:
                canonical = validate_receipt(job, record["receipt"])
                if receipt_digest(canonical) != record["receipt_sha256"]:
                    raise ValueError
                expected_state = canonical["state"] if canonical["state"] in {"done", "failed"} else "unknown"
                if state not in {expected_state, "held"} or (record["attached"] and expected_state == "unknown"):
                    raise ValueError
            elif record["receipt_sha256"] is not None or record["attached"] or state in {"done", "failed"}:
                raise ValueError
            if record["attached"] and record["artifact_path"] != self.artifact_path(job_id):
                raise ValueError
            if not record["attached"] and record["artifact_path"] is not None:
                raise ValueError
            return {**record, "state": state}
        except (KeyError, TypeError, ValueError, BridgeError):
            raise BridgeError("Diagnostic record is held for reconciliation") from None

    @staticmethod
    def _job(job_id, digest, argv, timeout, submitted):
        validate_command(argv, timeout)
        _timestamp(submitted)
        return {
            "id": job_id,
            "key_sha256": digest,
            "task": "Momo WSL diagnostic",
            "engine": "wsl",
            "model": None,
            "tools": None,
            "turns": 25,
            "budget": 1,
            "composio": False,
            "thread": None,
            "argv": argv,
            "timeout": timeout,
            "state": "queued",
            "submitted": submitted,
        }

    @staticmethod
    def artifact_path(job_id):
        return f"/mnt/user-data/outputs/wsl-diagnostic-{job_id}.json"

    @staticmethod
    def _save(conn, record):
        conn.execute("UPDATE requests SET state=?, record=? WHERE id=?", (record["state"], compact_json({key: value for key, value in record.items() if key != "state"}), record["job"]["id"]))

    def enqueue(self, *, organization_id, actor_user_id, storage_user_id, thread_id, request_id, argv, timeout):
        validate_command(argv, timeout)
        binding = ["momo-wsl-v1", organization_id, actor_user_id, thread_id, request_id]
        if (
            any(not isinstance(part, str) or not part or len(part) > 128 for part in binding)
            or not _THREAD_ID.fullmatch(thread_id)
            or not _REQUEST_ID.fullmatch(request_id)
            or not isinstance(storage_user_id, str)
            or not storage_user_id
            or len(storage_user_id) > 128
        ):
            raise BridgeError("Invalid trusted diagnostic binding", 422)
        digest = hashlib.sha256(compact_json(binding).encode()).hexdigest()
        job_id = job_id_for_digest(digest)
        with self._connect(write=True, create=True) as conn:
            existing = conn.execute("SELECT id,state,record FROM requests WHERE id=?", (job_id,)).fetchone()
            if existing:
                record = self._record(existing)
                if record["binding"] != binding or record["storage_user_id"] != storage_user_id or record["job"]["argv"] != argv or record["job"]["timeout"] != timeout:
                    conn.execute("UPDATE requests SET state='held' WHERE id=?", (job_id,))
                    raise _Held("Diagnostic request conflicts with its durable binding")
                return record
            count, outstanding = conn.execute("SELECT count(*),sum(state NOT IN ('done','failed')) FROM requests").fetchone()
            if count >= MAX_RECORDS or (outstanding or 0) >= MAX_OUTSTANDING:
                raise BridgeError("Diagnostic spool capacity reached", 429)
            job = self._job(job_id, digest, argv, timeout, datetime.now(UTC).isoformat())
            record = {"binding": binding, "storage_user_id": storage_user_id, "job": job, "receipt": None, "receipt_sha256": None, "attached": False, "artifact_path": None}
            conn.execute("INSERT INTO requests VALUES (?,?,?)", (job_id, "queued", compact_json(record)))
            return {**record, "state": "queued"}

    def read(self, job_id):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise BridgeError("Diagnostic request not found", 404)
        with self._connect() as conn:
            return self._record(conn.execute("SELECT id,state,record FROM requests WHERE id=?", (job_id,)).fetchone())

    def status(self, job_id):
        record = self.read(job_id)
        return {"protocol": PROTOCOL, "job_id": job_id, "state": record["state"], "attached": record["attached"], "receipt_sha256": record["receipt_sha256"]}

    def claim(self):
        if not self.path.exists():
            return {"protocol": PROTOCOL, "requests": []}
        with self._connect(write=True) as conn:
            records = [self._record(row) for row in conn.execute("SELECT id,state,record FROM requests ORDER BY rowid")]
            if any(record["state"] in {"unknown", "held"} for record in records):
                return {"protocol": PROTOCOL, "requests": []}
            record = next((item for item in records if item["state"] == "claimed"), None) or next((item for item in records if item["state"] == "queued"), None)
            if record is None:
                return {"protocol": PROTOCOL, "requests": []}
            record["state"] = "claimed"
            self._save(conn, record)
            return {"protocol": PROTOCOL, "requests": [{"job": record["job"], "idempotency_key": compact_json(record["binding"])}]}

    def ingest(self, job_id, receipt):
        with self._connect(write=True) as conn:
            record = self._record(conn.execute("SELECT id,state,record FROM requests WHERE id=?", (job_id,)).fetchone())
            try:
                canonical = validate_receipt(record["job"], receipt)
                digest = receipt_digest(canonical)
                if record["receipt_sha256"] is not None:
                    if record["receipt_sha256"] != digest:
                        raise BridgeError("Conflicting diagnostic receipt")
                    return self._view(record)
                if record["state"] != "claimed":
                    raise BridgeError("Diagnostic is not claimed")
            except BridgeError as exc:
                conn.execute("UPDATE requests SET state='held' WHERE id=?", (job_id,))
                raise _Held(str(exc)) from None
            record.update(receipt=receipt, receipt_sha256=digest, state=canonical["state"] if canonical["state"] in {"done", "failed"} else "unknown")
            self._save(conn, record)
            return self._view(record)

    @staticmethod
    def _view(record):
        return {"protocol": PROTOCOL, "job_id": record["job"]["id"], "state": record["state"], "attached": record["attached"], "receipt_sha256": record["receipt_sha256"]}

    def mark_attached(self, job_id, digest, *, check_ownership=None):
        with self._connect(write=True) as conn:
            record = self._record(conn.execute("SELECT id,state,record FROM requests WHERE id=?", (job_id,)).fetchone())
            if record["receipt_sha256"] != digest or record["state"] not in {"done", "failed"}:
                raise BridgeError("Diagnostic attachment is held")
            if check_ownership is not None:
                check_ownership()
            record.update(attached=True, artifact_path=self.artifact_path(job_id))
            self._save(conn, record)
            if check_ownership is not None:
                check_ownership()
            return self._view(record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("claim", "receipt", "status"))
    args = parser.parse_args(argv)
    try:
        store = BridgeStore.from_environment()
        if args.action == "claim":
            result = store.claim()
        else:
            raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1)
            if len(raw) > MAX_MESSAGE_BYTES:
                raise BridgeError("Diagnostic message exceeds its bound", 422)
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                raise BridgeError("Invalid diagnostic message", 422) from None
            expected = {"job_id", "receipt"} if args.action == "receipt" else {"job_id"}
            if not isinstance(body, dict) or set(body) != expected:
                raise BridgeError("Invalid diagnostic message fields", 422)
            if args.action == "status":
                result = store.status(body["job_id"])
            else:
                from app.gateway.wsl_bridge_attachment import ingest_local_receipt

                result = asyncio.run(ingest_local_receipt(store, body["job_id"], body["receipt"]))
        print(compact_json(result))
        return 0
    except BridgeError as exc:
        print(compact_json({"protocol": PROTOCOL, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
