"""Authenticated workflow catalog and owner-scoped durable run operations."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.jevbox_evidence import MAX_PACKET_BYTES, JevboxEvidenceError, prepare_jevbox_evidence
from app.gateway.jevbox_preparation_binding import JevboxPreparationBinding
from app.gateway.paid_run_entitlement import require_paid_run_entitlement
from app.gateway.workflow_service import WorkflowService, WorkflowServiceError


async def _private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/workflows", tags=["workflows"], dependencies=[Depends(_private_response)])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    inputs: dict = Field(default_factory=dict)
    framework: Literal["langgraph", "crewai", "mastra", "deepagents", "agno", "agentkit"] = "langgraph"
    supervisor: bool = Field(default=False, strict=True)


def _identity(request: Request):
    auth = get_auth_context(request)
    if auth is None or not auth.is_authenticated:
        raise HTTPException(401, detail="Authentication required")
    actor = str(auth.actor_user_id or auth.require_user().id)
    storage = auth.storage_user_id or actor
    scope = hashlib.sha256(json.dumps([actor, auth.organization_id, storage], separators=(",", ":")).encode()).hexdigest()
    return actor, auth.organization_id, storage, scope


def _owner(request: Request):
    actor, organization, storage, scope = _identity(request)
    if not hmac.compare_digest(request.headers.get("X-Expected-Workflow-Scope", "").encode(), scope.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    return actor, organization, storage, scope


def _service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        raise HTTPException(503, detail="not_enabled")
    return service


async def _call(awaitable):
    try:
        return await awaitable
    except WorkflowServiceError as error:
        raise HTTPException(error.status_code, detail=error.code) from None


@router.get("/status")
@require_permission("runs", "read")
async def status(request: Request):
    actor, _org, _storage, scope = _identity(request)
    if not hmac.compare_digest(request.headers.get("X-Expected-User-Id", "").encode(), actor.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    return {**await _call(_service(request).status(scope)), "owner_scope": scope}


@router.get("/catalog")
@require_permission("runs", "read")
async def catalog(request: Request):
    _owner(request)
    from deerflow.workflows.catalog import list_workflows

    definitions = list_workflows()
    return {"workflows": [definition.model_dump() if hasattr(definition, "model_dump") else dict(definition) for definition in definitions], "total": len(definitions)}


@router.get("/jevbox/status")
@require_permission("runs", "read")
async def jevbox_preparation_status(request: Request):
    """Return only scope-bound preparation availability metadata."""
    actor, organization, storage, scope = _identity(request)
    if not hmac.compare_digest(request.headers.get("X-Expected-User-Id", "").encode(), actor.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    binding = getattr(request.app.state, "jevbox_preparation_binding", None)
    if not isinstance(binding, JevboxPreparationBinding):
        return {
            "owner_scope": scope,
            "preparation_available": False,
            "current_review": False,
            "dispatch_enabled": False,
        }
    context = binding.context
    available = (actor, organization, storage) == (
        context.actor_user_id,
        context.momo_organization_id,
        context.storage_user_id,
    )
    now = datetime.now(UTC)
    current_review = bool(available and context.expected_reviewed_at <= now <= context.review_expires_at)
    return {
        "owner_scope": scope,
        "preparation_available": bool(available),
        "current_review": current_review,
        "dispatch_enabled": False,
    }


async def _bounded_body(request: Request) -> bytes:
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdigit():
            raise HTTPException(400, detail="content_length_invalid")
        try:
            declared = int(length)
        except ValueError:
            raise HTTPException(400, detail="content_length_invalid") from None
        if declared > MAX_PACKET_BYTES:
            raise HTTPException(413, detail="packet_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PACKET_BYTES:
            raise HTTPException(413, detail="packet_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/jevbox/prepare")
@require_permission("runs", "read")
async def prepare_jevbox(request: Request):
    """Return an unsent proposal from one pinned review; never create a run."""
    binding = getattr(request.app.state, "jevbox_preparation_binding", None)
    if type(binding) is not JevboxPreparationBinding:
        raise HTTPException(404, detail="preparation_unavailable")
    actor, organization, storage, _scope = _owner(request)
    context = binding.context
    if (actor, organization, storage) != (
        context.actor_user_id,
        context.momo_organization_id,
        context.storage_user_id,
    ):
        raise HTTPException(403, detail="preparation_scope_mismatch")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, detail="application_json_required")
    packet = await _bounded_body(request)
    try:
        return prepare_jevbox_evidence(packet, admission=context, now=datetime.now(UTC))
    except JevboxEvidenceError as error:
        code = str(error)
        status_code = 409 if code == "review_not_current" else 422
        raise HTTPException(status_code, detail=code) from None


@router.post("/runs")
@require_permission("runs", "create")
@require_paid_run_entitlement
async def create(body: WorkflowRequest, request: Request, idempotency_key: IdempotencyKey):
    actor, organization, storage, scope = _owner(request)
    return await _call(_service(request).create(scope, body.workflow_id, body.inputs, body.framework, idempotency_key, actor=actor, organization=organization, storage_user=storage, supervisor=body.supervisor))


@router.get("/runs")
@require_permission("runs", "read")
async def list_runs(request: Request):
    return {"runs": await _call(_service(request).list_runs(_owner(request)[3]))}


@router.get("/runs/{run_id}")
@require_permission("runs", "read")
async def snapshot(run_id: str, request: Request):
    return await _call(_service(request).snapshot(_owner(request)[3], run_id))


@router.post("/runs/{run_id}/cancel")
@require_permission("runs", "cancel")
async def cancel(run_id: str, request: Request):
    return await _call(_service(request).cancel(_owner(request)[3], run_id))


@router.post("/runs/{run_id}/resume")
@require_permission("runs", "create")
@require_paid_run_entitlement
async def resume(run_id: str, request: Request):
    return await _call(_service(request).resume(_owner(request)[3], run_id))


@router.get("/runs/{run_id}/artifact")
@require_permission("runs", "read")
async def artifact(run_id: str, request: Request):
    content = await _call(_service(request).artifact(_owner(request)[3], run_id))
    return Response(content, media_type="application/json", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": 'attachment; filename="workflow-result.json"'})
