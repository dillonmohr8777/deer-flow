"""Authenticated admission/readback; only delegated internal workers ingest."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL
from app.gateway.authz import require_permission
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.wsl_bridge import MAX_MESSAGE_BYTES, BridgeError, BridgeStore, validate_command
from app.gateway.wsl_bridge_attachment import attach_receipt
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api/threads/{thread_id}/wsl-diagnostics", tags=["wsl-diagnostics"])


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    argv: list[Annotated[str, StringConstraints(strict=True, max_length=64)]] = Field(min_length=1, max_length=2)
    timeout: int = Field(default=30, strict=True, ge=1, le=600)


def _identity(request):
    auth = getattr(request.state, "auth", None)
    if getattr(request.state, "auth_source", None) == AUTH_SOURCE_AUTH_DISABLED or auth is None or not auth.is_authenticated or not auth.organization_id or not auth.actor_user_id or not auth.storage_user_id:
        raise HTTPException(status_code=403, detail="Verified diagnostic identity is required")
    if str(auth.user.id) != auth.actor_user_id:
        raise HTTPException(status_code=403, detail="Verified diagnostic actor is required")
    return auth


def _owned(record, auth, thread_id):
    if record["binding"][1:4] != [auth.organization_id, auth.actor_user_id, thread_id] or record["storage_user_id"] != auth.storage_user_id:
        raise HTTPException(status_code=404, detail="Diagnostic request not found")


def _error(exc):
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def enqueue_diagnostic(thread_id: ThreadId, request: Request, body: DiagnosticRequest):
    auth = _identity(request)
    try:
        validate_command(body.argv, body.timeout)
        store = await asyncio.to_thread(BridgeStore.from_environment)
        record = await asyncio.to_thread(store.enqueue, organization_id=auth.organization_id, actor_user_id=auth.actor_user_id, storage_user_id=auth.storage_user_id, thread_id=thread_id, **body.model_dump())
        return {**store._view(record), "artifact_path": record["artifact_path"], "receipt": record["receipt"]}
    except BridgeError as exc:
        raise _error(exc) from None


@router.get("/{job_id}")
@require_permission("threads", "read", owner_check=True, require_existing=True)
async def read_diagnostic(thread_id: ThreadId, job_id: str, request: Request):
    auth = _identity(request)
    try:
        store = await asyncio.to_thread(BridgeStore.from_environment)
        record = await asyncio.to_thread(store.read, job_id)
        _owned(record, auth, thread_id)
        return {**store._view(record), "artifact_path": record["artifact_path"], "receipt": record["receipt"]}
    except BridgeError as exc:
        raise _error(exc) from None


@router.post("/{job_id}/receipt")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def ingest_diagnostic_receipt(thread_id: ThreadId, job_id: str, request: Request):
    auth = _identity(request)
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_INTERNAL or get_trusted_internal_owner_user_id(request) != auth.storage_user_id:
        raise HTTPException(status_code=403, detail="A verified internal delegation is required for diagnostic receipts")
    try:
        store = await asyncio.to_thread(BridgeStore.from_environment)
        record = await asyncio.to_thread(store.read, job_id)
        _owned(record, auth, thread_id)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_MESSAGE_BYTES:
                raise BridgeError("Diagnostic receipt exceeds its bound", 422)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise BridgeError("Invalid diagnostic receipt JSON", 422) from None
        if not isinstance(body, dict) or set(body) != {"receipt"}:
            raise BridgeError("Only the diagnostic receipt may be supplied", 422)
        await asyncio.to_thread(store.ingest, job_id, body["receipt"])
        return await attach_receipt(store, job_id, request)
    except BridgeError as exc:
        raise _error(exc) from None
