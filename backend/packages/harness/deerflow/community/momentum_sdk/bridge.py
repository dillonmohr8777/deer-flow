"""Bounded offline worker protocol; no SDK or provider imports in Gateway."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OUTPUT_LIMIT = 16384
INPUT_LIMIT = 32768


class HandoffPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_id: str = Field(min_length=1, max_length=200)
    status: Literal["draft", "blocked", "needs_approval"]
    found: str = Field(min_length=1, max_length=2000)
    proposed_change: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1, max_length=8)
    next_move: str = Field(min_length=1, max_length=2000)


def _read_regular(path: Path, max_bytes: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise ValueError("Invalid source")
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Source too large")
        return data
    finally:
        os.close(fd)


@dataclass(frozen=True)
class WorkerSpec:
    """Fixed operator paths; model arguments never choose an interpreter."""

    interpreter: Path
    script: Path
    timeout_seconds: float = 35.0

    def __post_init__(self):
        if not self.interpreter.is_absolute() or not self.script.is_absolute() or not 0 < self.timeout_seconds <= 60:
            raise ValueError("Fixed absolute paths and bounded deadline required")
        if not self.interpreter.is_file() or not os.access(self.interpreter, os.X_OK):
            raise ValueError("Interpreter unavailable")
        _read_regular(self.script, 100000)


def canonical_status(root: Path, client_id: str) -> dict:
    """Read exact existing registry and queue through no-follow directory FDs."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def read(directory, filename):
        folder_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 10000000:
                    raise ValueError("Invalid canonical source")
                data = os.read(fd, 10000001)
                if len(data) > 10000000:
                    raise ValueError("Canonical byte limit")
                return json.loads(data)
            finally:
                os.close(fd)
        finally:
            os.close(folder_fd)

    try:
        registry = read("registry", "clients.json")
        matches = [c for c in registry["clients"] if c["id"] == client_id]
        if len(matches) != 1:
            raise ValueError("Exact canonical identity required")
        queue = read("queue", "work-items.json")
        records = [r for r in queue["workItems"] if r.get("clientId") == client_id]
        return {"client_id": client_id, "engagement": "unknown", "queue_matches": len(records), "queue_revision": queue["revision"], "registry_status": matches[0].get("status", "unavailable")}
    finally:
        os.close(root_fd)


class OfflineReviewer:
    """Per-run trusted host grant; no live inference execution path."""

    def __init__(self, *, owner_id: str, thread_id: str, run_id: str, client_ids: frozenset[str], canonical_root: Path, worker: WorkerSpec):
        if not all(isinstance(v, str) and v for v in (owner_id, thread_id, run_id)) or not canonical_root.is_absolute():
            raise ValueError("Trusted identity and absolute canonical root required")
        self.scope = (owner_id, thread_id, run_id)
        self.client_ids = client_ids
        self.canonical_root = canonical_root
        self.worker = worker
        self.script_digest = hashlib.sha256(_read_regular(worker.script, 100000)).digest()

    async def __call__(self, *, client_id: str, request: str, user_id: str, thread_id: str, run_id: str) -> str:
        try:
            if (user_id, thread_id, run_id) != self.scope or client_id not in self.client_ids:
                raise ValueError("Scope denied")
            if not isinstance(request, str) or not 1 <= len(request) <= 8000:
                raise ValueError("Input limit")
            status = await asyncio.to_thread(canonical_status, self.canonical_root, client_id)
            source = await asyncio.to_thread(_read_regular, self.worker.script, 100000)
            if hashlib.sha256(source).digest() != self.script_digest:
                raise ValueError("Worker changed")
            payload = json.dumps({"client_id": client_id, "request": request, "canonical_status": status}).encode()
            if len(payload) > INPUT_LIMIT:
                raise ValueError("Input byte limit")
            output = await self._execute(payload)
            packet = HandoffPacket.model_validate_json(output)
            if packet.client_id != client_id or any(not e.strip() or len(e) > 512 for e in packet.evidence):
                raise ValueError("Identity/evidence mismatch")
            return packet.model_dump_json()
        except Exception:
            return json.dumps({"error": "Offline SDK review unavailable or invalid; no external action performed."})

    async def _execute(self, payload: bytes) -> bytes:
        proc = None
        tasks = []

        async def read(stream: asyncio.StreamReader) -> bytes:
            result = bytearray()
            while chunk := await stream.read(4096):
                result.extend(chunk)
                if len(result) > OUTPUT_LIMIT:
                    raise ValueError("Output byte limit")
            return bytes(result)

        try:
            async with asyncio.timeout(self.worker.timeout_seconds):
                spawn = asyncio.create_task(
                    asyncio.create_subprocess_exec(
                        str(self.worker.interpreter),
                        "-B",
                        "-I",
                        str(self.worker.script),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=self.worker.script.parent,
                        env={"LANG": "C.UTF-8", "OPENAI_AGENTS_DISABLE_TRACING": "1", "PYTHONDONTWRITEBYTECODE": "1"},
                        start_new_session=os.name == "posix",
                    )
                )
                try:
                    proc = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    while not spawn.done():
                        try:
                            await asyncio.shield(spawn)
                        except asyncio.CancelledError:
                            continue
                    proc = spawn.result()
                    raise
                if proc.stdin is None or proc.stdout is None or proc.stderr is None:
                    raise ValueError("Worker pipes unavailable")
                proc.stdin.write(payload)
                await proc.stdin.drain()
                proc.stdin.close()
                tasks = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr)), asyncio.create_task(proc.wait())]
                output, _, code = await asyncio.gather(*tasks)
                if code != 0 or not isinstance(output, bytes):
                    raise ValueError("Worker failed")
                return output
        finally:
            if proc is not None and proc.returncode is None:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                cleanup = asyncio.create_task(proc.wait())
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        continue
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
