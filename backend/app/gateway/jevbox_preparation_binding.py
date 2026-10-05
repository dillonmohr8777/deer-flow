"""Load an opt-in, bounded reviewer binding for preparation-only requests."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn, overload

from app.gateway.jevbox_evidence import (
    MAX_DOCUMENTS,
    TrustedJevboxPreparationContext,
)

ENV_NAME = "MOMOBOT_JEVBOX_PREPARATION_FILE"
MAX_BINDING_BYTES = 64_000
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_TOP_KEYS = {"schema_version", "context"}
_CONTEXT_KEYS = {
    "actor_user_id",
    "owner_user_id",
    "storage_user_id",
    "momo_organization_id",
    "jevbox_organization_id",
    "source_client_id",
    "document_ids",
    "source_pins",
    "expected_packet_sha256",
    "expected_reviewed_by",
    "expected_reviewed_at",
    "review_expires_at",
    "owner_scope_active",
}


class JevboxPreparationBindingError(ValueError):
    """Fixed safe startup errors; never include a path or file contents."""


@dataclass(frozen=True)
class JevboxPreparationBinding:
    context: TrustedJevboxPreparationContext


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JevboxPreparationBindingError("binding_invalid")
        result[key] = value
    return result


def _fail() -> NoReturn:
    raise JevboxPreparationBindingError("binding_invalid")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        _fail()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail()
    if parsed.utcoffset() is None:
        _fail()
    return parsed


@overload
def _identifier(value: Any) -> str: ...


@overload
def _identifier(value: Any, *, optional: bool) -> str | None: ...


def _identifier(value: Any, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail()
    return value


def _load_bytes(path: str) -> bytes:
    try:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            _fail()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BINDING_BYTES or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                _fail()
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(fd, min(8192, MAX_BINDING_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BINDING_BYTES:
                    _fail()
            return b"".join(chunks)
        finally:
            os.close(fd)
    except JevboxPreparationBindingError:
        raise
    except (OSError, TypeError, ValueError):
        _fail()


def load_jevbox_preparation_binding(path: str) -> JevboxPreparationBinding:
    """Read one strict startup binding; requests cannot replace its context."""
    raw = _load_bytes(path)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, ValueError, RecursionError):
        _fail()
    if not isinstance(value, dict) or set(value) != _TOP_KEYS or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _fail()
    values = value["context"]
    if not isinstance(values, dict) or set(values) != _CONTEXT_KEYS:
        _fail()
    document_ids = values["document_ids"]
    source_pins = values["source_pins"]
    if not isinstance(document_ids, list) or not 1 <= len(document_ids) <= MAX_DOCUMENTS:
        _fail()
    docs = tuple(_identifier(item) for item in document_ids)
    if len(set(docs)) != len(docs):
        _fail()
    if not isinstance(source_pins, list) or len(source_pins) != len(docs):
        _fail()
    pins: list[tuple[str, str]] = []
    for pin in source_pins:
        if not isinstance(pin, dict) or set(pin) != {"document_id", "sha256"}:
            _fail()
        document_id = _identifier(pin["document_id"])
        digest = pin["sha256"]
        if document_id not in docs or not isinstance(digest, str) or not _HASH.fullmatch(digest):
            _fail()
        pins.append((document_id, digest))
    if len({item[0] for item in pins}) != len(pins) or {item[0] for item in pins} != set(docs):
        _fail()
    packet_hash = values["expected_packet_sha256"]
    if not isinstance(packet_hash, str) or not _HASH.fullmatch(packet_hash):
        _fail()
    active = values["owner_scope_active"]
    if type(active) is not bool or active is not True:
        _fail()
    context = TrustedJevboxPreparationContext(
        actor_user_id=_identifier(values["actor_user_id"]),
        owner_user_id=_identifier(values["owner_user_id"]),
        storage_user_id=_identifier(values["storage_user_id"]),
        momo_organization_id=_identifier(values["momo_organization_id"], optional=True),
        jevbox_organization_id=_identifier(values["jevbox_organization_id"]),
        source_client_id=_identifier(values["source_client_id"]),
        document_ids=docs,
        source_pins=tuple(pins),
        expected_packet_sha256=packet_hash,
        expected_reviewed_by=_identifier(values["expected_reviewed_by"]),
        expected_reviewed_at=_timestamp(values["expected_reviewed_at"]),
        review_expires_at=_timestamp(values["review_expires_at"]),
        owner_scope_active=True,
    )
    if context.actor_user_id != context.owner_user_id or context.storage_user_id != context.owner_user_id:
        _fail()
    if context.expected_reviewed_at > context.review_expires_at:
        _fail()
    return JevboxPreparationBinding(context=context)


def load_optional_jevbox_preparation_binding() -> JevboxPreparationBinding | None:
    """Absent opt-in means no configured preparation admission."""
    path = os.environ.get(ENV_NAME)
    if path is None:
        return None
    if not path:
        _fail()
    return load_jevbox_preparation_binding(path)
