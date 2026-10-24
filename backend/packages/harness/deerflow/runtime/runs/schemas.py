"""Run status and disconnect mode enums."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

LIMIT_ACTIONS = ("prestart_timeout", "execution_timeout")
HOLD_ACTIONS = (*LIMIT_ACTIONS, "cleanup_hold")
RUN_STORAGE_TAG = "__deerflow_run_storage_v1__"


def start_run_timing(timing: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """Stamp execution time only in the store's successful pending -> running CAS."""
    if timing is None or timing.get("started_at") is not None:
        return timing
    seconds = timing["execution_timeout_seconds"]
    return {**timing, "started_at": now.isoformat(), "execution_deadline_at": (now + timedelta(seconds=seconds)).isoformat() if seconds else None}


def timing_deadline(timing: dict[str, Any] | None, *, pending: bool) -> datetime | None:
    if timing is None:
        return None
    value = timing.get("prestart_deadline_at" if pending else "execution_deadline_at")
    return datetime.fromisoformat(value).astimezone(UTC) if value else None


def pack_run_kwargs(kwargs: dict, timing: dict | None) -> dict | list:
    # Legacy/API kwargs are objects. An array envelope cannot collide with a user key.
    return [RUN_STORAGE_TAG, kwargs, timing] if timing is not None else kwargs


def unpack_run_kwargs(value: dict | list) -> tuple[dict, dict | None]:
    if isinstance(value, list) and len(value) == 3 and value[0] == RUN_STORAGE_TAG and isinstance(value[1], dict) and isinstance(value[2], dict):
        return value[1], value[2]
    return value, None


def execution_deadline_expired(row: dict[str, Any], now: datetime) -> bool:
    if row.get("operation_kind", "run") != "run" or row.get("status") != "running":
        return False
    deadline = timing_deadline(row.get("run_limits"), pending=False)
    return deadline is not None and now >= deadline


class ThreadOperationKind(StrEnum):
    """Kind of operation holding exclusive admission for a thread."""

    run = "run"
    checkpoint_write = "checkpoint_write"
    artifact_write = "artifact_write"
    upload_write = "upload_write"
    artifact_archive = "artifact_archive"
    branch = "branch"
    delete = "delete"


class RunStatus(StrEnum):
    """Lifecycle status of a single run."""

    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"


class DisconnectMode(StrEnum):
    """Behaviour when the SSE consumer disconnects."""

    cancel = "cancel"
    continue_ = "continue"
