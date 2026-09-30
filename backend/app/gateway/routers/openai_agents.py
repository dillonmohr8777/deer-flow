"""Authenticated mobile/desktop access to opt-in managed OpenAI sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.openai_agent_service import AgentServiceError, OpenAIAgentService
from app.gateway.paid_run_entitlement import require_paid_run_entitlement
from deerflow.config.paths import get_paths

router = APIRouter(prefix="/api/openai-agents", tags=["openai-agents"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=16000)

    @field_validator("input")
    @classmethod
    def validate_input(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > 65536:
            raise ValueError("Supply a nonempty message of at most 65536 UTF-8 bytes")
        return value


class CreateSessionRequest(MessageRequest):
    title: str = Field(default="MomoBot task", min_length=1, max_length=120)


def _service(request: Request) -> OpenAIAgentService:
    service = getattr(request.app.state, "openai_agent_service", None)
    if service is None:
        service = OpenAIAgentService(get_paths().base_dir / "openai-agents.sqlite")
        request.app.state.openai_agent_service = service
    return service


def _owner(request: Request) -> str:
    auth = get_auth_context(request)
    if auth is None or not auth.is_authenticated:
        raise HTTPException(401, detail="Authentication required")
    # Actor and workspace are separate: another workspace member cannot read this
    # person's provider session merely because both share a storage principal.
    actor = auth.actor_user_id or str(auth.require_user().id)
    values = [actor, auth.organization_id, auth.storage_user_id or actor]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _scoped_owner(request: Request) -> str:
    owner = _owner(request)
    expected = request.headers.get("X-Expected-Agent-Scope", "")
    if not hmac.compare_digest(owner.encode(), expected.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    return owner


async def _call(awaitable):
    try:
        return await awaitable
    except AgentServiceError as error:
        raise HTTPException(error.status_code, detail=error.code) from None


@router.get("/status")
@require_permission("runs", "read")
async def status(request: Request) -> dict:
    owner = _owner(request)
    auth = get_auth_context(request)
    actor = auth.actor_user_id or str(auth.require_user().id)
    expected = request.headers.get("X-Expected-User-Id", "")
    if not hmac.compare_digest(actor.encode(), expected.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    return {**_service(request).status(), "owner_scope": owner}


@router.get("/sessions")
@require_permission("runs", "read")
async def list_sessions(request: Request) -> dict:
    owner = _scoped_owner(request)
    return {"data": await _call(_service(request).list_sessions(owner))}


@router.post("/sessions")
@require_permission("runs", "create")
@require_paid_run_entitlement
async def create_session(body: CreateSessionRequest, request: Request, idempotency_key: IdempotencyKey) -> dict:
    owner = _scoped_owner(request)
    return await _call(_service(request).create(owner, body.input, body.title, idempotency_key))


@router.get("/sessions/{session_id}")
@require_permission("runs", "read")
async def get_session(session_id: str, request: Request) -> dict:
    owner = _scoped_owner(request)
    return await _call(_service(request).snapshot(owner, session_id))


@router.post("/sessions/{session_id}/messages")
@require_permission("runs", "create")
@require_paid_run_entitlement
async def message(session_id: str, body: MessageRequest, request: Request, idempotency_key: IdempotencyKey) -> dict:
    owner = _scoped_owner(request)
    return await _call(_service(request).message(owner, session_id, body.input, idempotency_key))


@router.post("/sessions/{session_id}/cancel")
@require_permission("runs", "cancel")
async def cancel(session_id: str, request: Request) -> dict:
    owner = _scoped_owner(request)
    return await _call(_service(request).cancel(owner, session_id))


@router.post("/sessions/{session_id}/browser-approval")
@require_permission("runs", "create")
async def browser_approval(session_id: str, request: Request) -> dict:
    # Check ownership before explaining unsupported features, avoiding an oracle.
    owner = _scoped_owner(request)
    service = _service(request)
    await _call(service._storage("get", session_id, owner))
    raise HTTPException(409, detail="hosted_browser_disabled_pending_action_policy")


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/content")
@require_permission("runs", "read")
async def artifact_content(session_id: str, artifact_id: str, request: Request) -> Response:
    owner = _scoped_owner(request)
    content = await _call(_service(request).artifact(owner, session_id, artifact_id))
    # Treat provider-generated files as downloads, never executable same-origin HTML.
    return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": 'attachment; filename="momobot-artifact"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
