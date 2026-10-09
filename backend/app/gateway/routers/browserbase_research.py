"""Authenticated, workspace-fenced read-only public Browserbase research."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.browserbase_service import BrowserbaseError, BrowserbaseResearchService, public_https_url
from app.gateway.paid_run_entitlement import require_paid_run_entitlement
from deerflow.config.paths import get_paths

router = APIRouter(prefix="/api/browserbase", tags=["browserbase-research"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(min_length=1, max_length=3)
    title: str = Field(default="Public browser research", min_length=1, max_length=120)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, urls: list[str]) -> list[str]:
        try:
            return [public_https_url(url) for url in urls]
        except BrowserbaseError as error:
            raise ValueError(error.code) from None


def _identity(request: Request) -> tuple[str, str]:
    auth = get_auth_context(request)
    if auth is None or not auth.is_authenticated:
        raise HTTPException(401, detail="Authentication required")
    actor = str(auth.actor_user_id or auth.require_user().id)
    values = [actor, auth.organization_id, auth.storage_user_id or actor]
    scope = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return actor, scope


def _owner(request: Request) -> str:
    _actor, scope = _identity(request)
    expected = request.headers.get("X-Expected-Browserbase-Scope", "")
    if not hmac.compare_digest(expected.encode(), scope.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    return scope


def _service(request: Request) -> BrowserbaseResearchService:
    service = getattr(request.app.state, "browserbase_service", None)
    if service is None:
        service = BrowserbaseResearchService(get_paths().base_dir / "browserbase-research.sqlite")
        request.app.state.browserbase_service = service
    return service


async def _call(awaitable):
    try:
        return await awaitable
    except BrowserbaseError as error:
        raise HTTPException(error.status_code, detail=error.code) from None


@router.get("/status")
@require_permission("runs", "read")
async def status(request: Request) -> dict:
    actor, scope = _identity(request)
    if not hmac.compare_digest(request.headers.get("X-Expected-User-Id", "").encode(), actor.encode()):
        raise HTTPException(409, detail="workspace_scope_changed")
    result = await _call(_service(request).status())
    return {**result, "owner_scope": scope}


@router.get("/research")
@require_permission("runs", "read")
async def list_research(request: Request) -> dict:
    owner = _owner(request)
    return {"data": await _call(_service(request).list_runs(owner))}


@router.post("/research")
@require_permission("runs", "create")
@require_paid_run_entitlement
async def create_research(body: ResearchRequest, request: Request, idempotency_key: IdempotencyKey) -> dict:
    owner = _owner(request)
    return await _call(_service(request).create(owner, body.urls, body.title, idempotency_key))


@router.get("/research/{run_id}")
@require_permission("runs", "read")
async def get_research(run_id: str, request: Request) -> dict:
    owner = _owner(request)
    return await _call(_service(request).snapshot(owner, run_id))


@router.post("/research/{run_id}/cancel")
@require_permission("runs", "cancel")
async def cancel_research(run_id: str, request: Request) -> dict:
    owner = _owner(request)
    return await _call(_service(request).cancel(owner, run_id))


@router.get("/research/{run_id}/pages/{index}/screenshot")
@require_permission("runs", "read")
async def screenshot(run_id: str, index: int, request: Request) -> Response:
    owner = _owner(request)
    content = await _call(_service(request).screenshot(owner, run_id, index))
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": 'inline; filename="public-source.png"'})
