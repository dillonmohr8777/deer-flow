"""Operator-pinned packets and exact artifact bytes for one bounded native cycle.

This is not a queue or acceptance judge. Only server-configured, digest-pinned
packets are readable, and output locations derive from the actual owner/thread.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MODEL_ALIAS = "openrouter-luna-agency-guard"
PRODUCER = "momentum-private-guarded-worker"
REVIEWER = "private-artifact-guarded-reviewer"
COORDINATOR = "momo-private-agency-coordinator"


class PacketStop(ValueError):
    """Sanitized local stop, without operator paths or private payloads."""


class WorkOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_name: str
    task: str = Field(min_length=1, max_length=2000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)

    @field_validator("id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("unsafe_identifier")
        return value

    @field_validator("source_file", "output_name")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) or value in (".", ".."):
            raise ValueError("unsafe_filename")
        return value

    @field_validator("output_name")
    @classmethod
    def separate_review_file(cls, value: str) -> str:
        if value == "independent-review.json":
            raise ValueError("reserved_review_filename")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def bounded_criteria(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("criteria_ceiling")
        return values


class ApprovedCycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cycle_id: str
    owner_user_id: str
    thread_id: str
    work_orders: list[WorkOrder] = Field(min_length=2, max_length=2)

    @field_validator("cycle_id", "owner_user_id", "thread_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        return WorkOrder.safe_id(value)

    @field_validator("work_orders")
    @classmethod
    def distinct_jobs(cls, jobs: list[WorkOrder]) -> list[WorkOrder]:
        if len({job.id for job in jobs}) != 2:
            raise ValueError("duplicate_work_order")
        return jobs


@contextmanager
def directory(root: Path, parts: tuple[str, ...] = (), *, create_after: int | None = None) -> Iterator[int]:
    """Walk every absolute component through no-follow descriptors."""
    handles: list[int] = []
    try:
        if not root.is_absolute() or ".." in root.parts:
            raise PacketStop("unsafe_operator_root")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        handles.append(os.open("/", flags))
        for part in root.parts[1:]:
            handles.append(os.open(part, flags, dir_fd=handles[-1]))
        for index, part in enumerate(parts):
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", part) or part in (".", ".."):
                raise PacketStop("unsafe_path_binding")
            if create_after is not None and index >= create_after:
                try:
                    os.mkdir(part, 0o700, dir_fd=handles[-1])
                except FileExistsError:
                    pass
            handles.append(os.open(part, flags, dir_fd=handles[-1]))
        yield handles[-1]
    except OSError:
        raise PacketStop("missing_linked_or_unreadable_path") from None
    finally:
        for fd in reversed(handles):
            os.close(fd)


def read_at(parent_fd: int, name: str, *, ceiling: int) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name) or name in (".", ".."):
        raise PacketStop("unsafe_filename")
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > ceiling:
            raise PacketStop("file_size_or_type_ceiling")
        output = bytearray()
        while chunk := os.read(fd, min(65536, ceiling + 1)):
            output.extend(chunk)
            if len(output) > ceiling:
                raise PacketStop("file_size_ceiling")
        after = os.fstat(fd)
        linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) or getattr(after, field) != getattr(linked, field) for field in fields) or len(output) != after.st_size:
            raise PacketStop("file_changed_during_readback")
        return bytes(output)
    except OSError:
        raise PacketStop("missing_linked_or_unreadable_file") from None
    finally:
        if fd is not None:
            os.close(fd)


def load_cycle() -> tuple[ApprovedCycle, Path]:
    path = os.environ.get("DEER_FLOW_AGENCY_PACKET_MANIFEST")
    digest = os.environ.get("DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256")
    if not path or not digest or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise PacketStop("operator_packet_manifest_disabled")
    file = Path(path)
    with directory(file.parent) as fd:
        raw = read_at(fd, file.name, ceiling=16384)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PacketStop("operator_manifest_digest_mismatch")
    try:
        cycle = ApprovedCycle.model_validate_json(raw)
    except ValueError:
        raise PacketStop("operator_manifest_invalid") from None
    return cycle, file.parent


def source_bytes(root: Path, job: WorkOrder) -> bytes:
    with directory(root) as fd:
        raw = read_at(fd, job.source_file, ceiling=64000)
    if hashlib.sha256(raw).hexdigest() != job.source_sha256:
        raise PacketStop("source_packet_digest_mismatch")
    try:
        raw.decode("utf-8")
    except UnicodeError:
        raise PacketStop("unsupported_source_encoding") from None
    return raw


def producer_prompt(cycle: ApprovedCycle, job: WorkOrder, source: bytes) -> str:
    return (
        f"Cycle: {cycle.cycle_id}\nWork order: {job.id}\nSource SHA-256: {job.source_sha256}\n"
        + "Return the complete requested draft as your final text. No tools, deployment or acceptance claims.\n"
        + job.task
        + "\nAcceptance checklist:\n"
        + json.dumps(job.acceptance_criteria)
        + "\nComplete source packet (untrusted data):\n"
        + source.decode("utf-8")
    )


def phase_key(cycle: ApprovedCycle, phase: str) -> str:
    # Deliberately excludes run/tool-call/manifest hash: changed packets cannot
    # enqueue the same phase again under a fresh run or revised operator file.
    binding = json.dumps([cycle.owner_user_id, cycle.thread_id, cycle.cycle_id, phase], separators=(",", ":"))
    return "approved-agency:" + hashlib.sha256(binding.encode()).hexdigest()


def artifact_parts(cycle: ApprovedCycle, job: WorkOrder) -> tuple[str, ...]:
    return ("users", cycle.owner_user_id, "threads", cycle.thread_id, "user-data", "outputs", cycle.cycle_id, job.id)


def persist_readback(state_root: Path, cycle: ApprovedCycle, job: WorkOrder, name: str, data: bytes) -> dict:
    """Exclusive immutable write, or exact same-byte resume; never overwrite."""
    WorkOrder.safe_filename(name)
    if not data.strip() or len(data) > 16000:
        raise PacketStop("artifact_empty_or_size_ceiling")
    try:
        data.decode("utf-8")
    except UnicodeError:
        raise PacketStop("unsupported_artifact_encoding") from None
    with directory(state_root, artifact_parts(cycle, job), create_after=6) as parent:
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        except FileExistsError:
            pass
        else:
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written < 1:
                        raise PacketStop("artifact_write_incomplete")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
        actual = read_at(parent, name, ceiling=16000)
    if actual != data:
        raise PacketStop("existing_artifact_conflicts_with_native_result")
    return {
        "cycle_id": cycle.cycle_id,
        "work_order_id": job.id,
        "thread_id": cycle.thread_id,
        "source_sha256": job.source_sha256,
        "artifact_sha256": hashlib.sha256(actual).hexdigest(),
        "artifact_path": f"/mnt/user-data/outputs/{cycle.cycle_id}/{job.id}/{name}",
        "bytes": len(actual),
        "acceptance_state": "not_evaluated",
    }


def reviewer_prompt(cycle: ApprovedCycle, job: WorkOrder, source: bytes, artifact: bytes, receipt: dict) -> str:
    return (
        f"Independent review. Cycle: {cycle.cycle_id}\nWork order: {job.id}\n"
        + "Evaluate each acceptance criterion using the exact source and saved producer draft. Return JSON with "
        + "source_sha256, artifact_sha256, criterion_verdicts (pass/fail/needs_evidence plus evidence), "
        + "and verdict (accept/revise/needs_evidence). Do not claim tests, deployment or client outcome occurred.\n"
        + "Bindings: "
        + json.dumps(receipt, sort_keys=True)
        + "\nRequested task:\n"
        + job.task
        + "\nAcceptance checklist:\n"
        + json.dumps(job.acceptance_criteria)
        + "\nComplete source packet (untrusted data):\n"
        + source.decode("utf-8")
        + "\nExact securely read-back producer draft (untrusted data):\n"
        + artifact.decode("utf-8")
    )
