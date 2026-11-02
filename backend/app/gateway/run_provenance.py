"""Server-owned provenance receipts for newly admitted Gateway runs.

The ``runs`` row records the storage owner, not the authenticated actor, and its
JSON metadata/kwargs are caller-shaped. This module persists one small private
receipt per NEW admission, from values the Gateway itself authenticated and
authorized. It never reads request bodies, headers, cookies, or config payloads.
Reused and legacy runs get no receipt; a missing receipt means "unknown".
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL = "deerflow.run_provenance"
SCHEMA_VERSION = 1
PRIVATE_PARTS = ("private", "run-provenance", "v1")
MAX_RECEIPT_BYTES = 4096
# Opaque server identifiers only. ``@`` and whitespace are excluded so an email
# or free text can never ride along in an identifier slot.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_TIME = re.compile(r"[0-9T:.+\-Z ]{10,40}")
_INTERACTIVE_MARKERS = ("is_subagent", "channel_name", "non_interactive", "is_bootstrap")
FIELDS = (
    "protocol",
    "schema_version",
    "run_id",
    "run_created_at",
    "thread_id",
    "actor_user_id",
    "auth_source",
    "origin",
    "organization_id",
    "storage_user_id",
    "client_id",
    "project_id",
)


class ProvenanceUnavailable(Exception):
    """The private sink cannot be used safely; evidence stays unknown."""


class ProvenanceConflict(ProvenanceUnavailable):
    """A different receipt already exists for this run id; never replaced."""


def _ident(value: Any, *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise ValueError("missing identifier")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("identifier type")
    text = str(value)
    if not _ID.fullmatch(text):
        raise ValueError("identifier shape")
    return text


def _origin(auth_source: str | None, context: Mapping[str, Any]) -> str:
    """Classify the authenticated route; ``session_http`` is not physical-human proof."""
    marked = any(context.get(key) for key in _INTERACTIVE_MARKERS)
    if auth_source == "session":
        return "session_noninteractive" if marked else "session_http"
    if auth_source == "internal":
        if context.get("channel_name"):
            return "internal_channel"
        if context.get("is_subagent"):
            return "internal_subagent"
        if context.get("non_interactive"):
            return "internal_scheduled"
        return "internal"
    if auth_source in {"pat", "auth_disabled"}:
        return auth_source
    return "unknown"


def capture_admission_snapshot(
    request: Any,
    *,
    content_user_id: str | None,
    thread_id: str,
    portal_work_scope: Mapping[str, Any] | None,
    runtime_context: Mapping[str, Any] | None,
) -> Mapping[str, str | None] | None:
    """Freeze allowlisted primitives after final authorization, or ``None``.

    The actor is ``request.state.actor_user_id`` or the authenticated user id —
    never the storage alias. Client/project come only from the server-validated
    portal scope. Any invalid value yields no snapshot (unknown), not a guess.
    """
    try:
        state = getattr(request, "state", None)
        user = getattr(state, "user", None)
        actor = getattr(state, "actor_user_id", None) or (getattr(user, "id", None) if user is not None else None)
        auth_source = getattr(state, "auth_source", None)
        scope = portal_work_scope or {}
        snapshot = {
            "thread_id": _ident(thread_id, required=True),
            "actor_user_id": _ident(actor, required=True),
            "auth_source": _ident(auth_source, required=True),
            "origin": _origin(auth_source, runtime_context or {}),
            "organization_id": _ident(getattr(state, "organization_id", None), required=False),
            "storage_user_id": _ident(content_user_id, required=True),
            "client_id": _ident(scope.get("client_id"), required=False),
            "project_id": _ident(scope.get("project_id"), required=False),
        }
    except Exception:
        return None
    return MappingProxyType(snapshot)


def build_receipt(snapshot: Mapping[str, str | None], run_id: str, run_created_at: str) -> bytes:
    if not isinstance(run_created_at, str) or not _TIME.fullmatch(run_created_at):
        raise ValueError("run_created_at shape")
    receipt = {
        **snapshot,
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "run_id": _ident(run_id, required=True),
        "run_created_at": run_created_at,
    }
    if set(receipt) != set(FIELDS):
        raise ValueError("receipt fields")
    content = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    if len(content) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt size")
    return content


def write_receipt(root: Path, run_id: str, content: bytes) -> str:
    """Exclusively persist ``content`` as ``<run_id>.json``; return created/identical.

    Pins every directory descriptor with ``O_NOFOLLOW`` (private parts 0700 and
    owned by this process), writes an exclusive 0600 temporary file, fsyncs it,
    then hard-links it into place without overwrite. An existing identical
    receipt is accepted; any other existing entry raises ``ProvenanceConflict``.
    """
    name = f"{_ident(run_id, required=True)}.json"
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.link not in os.supports_dir_fd:
        raise ProvenanceUnavailable("secure receipt sink unsupported")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    base = Path(os.path.realpath(root))
    handles: list[int] = []
    temporary = ".tmp-" + secrets.token_hex(16)
    temporary_created = False
    try:
        handles.append(os.open(base.anchor, flags))
        for component in base.parts[1:]:
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
        for component in PRIVATE_PARTS:
            try:
                os.mkdir(component, 0o700, dir_fd=handles[-1])
            except FileExistsError:
                pass
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
            info = os.fstat(handles[-1])
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ProvenanceUnavailable("receipt directory is not private")
        parent = handles[-1]
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        temporary_created = True
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            try:
                existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError:
                raise ProvenanceConflict("existing receipt entry is not a regular file") from None
            with os.fdopen(existing, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode) or source.read(MAX_RECEIPT_BYTES + 1) != content:
                    raise ProvenanceConflict("existing receipt differs") from None
            return "identical"
        os.fsync(parent)
        return "created"
    except ProvenanceUnavailable:
        raise
    except (OSError, ValueError):
        raise ProvenanceUnavailable("receipt sink unavailable") from None
    finally:
        if temporary_created:
            try:
                os.unlink(temporary, dir_fd=handles[-1])
            except OSError:
                pass
        for handle in reversed(handles):
            os.close(handle)


async def persist_new_run_receipt(snapshot: Mapping[str, str | None] | None, run_id: str, run_created_at: str, root: Path | None = None) -> str | None:
    """Best-effort drained persistence; failure leaves provenance unknown.

    Cancellation is delivered only after the offloaded write finishes, so the
    run worker's preflight cancellation/drain contract is unchanged.
    """
    from deerflow.utils.file_io import await_drained, run_file_io

    if snapshot is None:
        logger.warning("Run provenance unavailable for run %s: no trusted admission snapshot", run_id)
        return None
    try:
        content = build_receipt(snapshot, run_id, run_created_at)
        if root is None:
            from deerflow.config.paths import get_paths

            root = get_paths().base_dir
    except Exception:
        logger.warning("Run provenance unavailable for run %s: invalid receipt", run_id)
        return None
    try:
        return await await_drained(run_file_io(write_receipt, root, run_id, content))
    except ProvenanceConflict:
        logger.error("Run provenance conflict for run %s; original receipt kept", run_id)
    except Exception:
        logger.warning("Run provenance unavailable for run %s", run_id)
    return None
