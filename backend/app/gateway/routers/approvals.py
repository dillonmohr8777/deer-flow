"""Approvals inbox API: review, edit, approve or reject actions agents proposed.

Reads are owner-scoped (``user_id`` + active organization, via the repository;
a foreign row is a 404). Edit/approve/reject additionally need an active
organization owner/admin, since approving is what releases an outbound action.
Only the caller that wins the pending->approved compare-and-set runs the
adapter, so a double click or two reviewers can never send twice.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.approval_adapters import execute_approved
from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user_from_request, get_pending_action_repo, record_audit_event
from app.gateway.routers.clients import _is_active_org_admin
from deerflow.approvals import InvalidPayloadError
from deerflow.runtime.user_context import resolve_organization_id

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

ActionStatus = Literal["pending", "approved", "rejected", "executed", "failed"]


class ApprovalResponse(BaseModel):
    id: str
    action_type: str
    title: str
    target: str
    payload: dict[str, Any]
    original_payload: dict[str, Any]
    status: str
    thread_id: str | None = None
    run_id: str | None = None
    agent_name: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    executed_at: str | None = None
    execution_result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]


class ApprovalEditRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    target: str | None = Field(default=None, max_length=512)
    payload: dict[str, Any] | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Approval not found")


def _out(row: dict) -> ApprovalResponse:
    return ApprovalResponse(**{k: row.get(k) for k in ApprovalResponse.model_fields})


async def _require_reviewer(request: Request) -> str:
    user_id = str((await get_current_user_from_request(request)).id)
    if not await _is_active_org_admin(user_id):
        raise HTTPException(status_code=403, detail="Only an organization owner or admin can review outbound actions.")
    return user_id


async def _audit(request: Request, action: str, actor: str, action_id: str, outcome: str, details: dict | None) -> None:
    await record_audit_event(request, action=action, outcome=outcome, actor_user_id=actor, organization_id=resolve_organization_id(), target_type="pending_action", target_id=action_id, details=details)


@router.get("", response_model=ApprovalListResponse)
@require_permission("approvals", "read")
async def list_approvals(request: Request, status: ActionStatus | None = None, limit: int = Query(default=100, ge=1, le=200)) -> ApprovalListResponse:
    rows = await get_pending_action_repo(request).list(status=status, limit=limit)
    return ApprovalListResponse(approvals=[_out(r) for r in rows])


@router.get("/{action_id}", response_model=ApprovalResponse)
@require_permission("approvals", "read")
async def get_approval(action_id: str, request: Request) -> ApprovalResponse:
    row = await get_pending_action_repo(request).get(action_id)
    if row is None:
        raise _not_found()
    return _out(row)


@router.patch("/{action_id}", response_model=ApprovalResponse)
@require_permission("approvals", "write")
async def edit_approval(action_id: str, body: ApprovalEditRequest, request: Request) -> ApprovalResponse:
    await _require_reviewer(request)
    repo = get_pending_action_repo(request)
    if await repo.get(action_id) is None:
        raise _not_found()
    try:
        row = await repo.edit(action_id, title=body.title, target=body.target, payload=body.payload)
    except InvalidPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=409, detail="Only a pending action can be edited")
    return _out(row)


@router.post("/{action_id}/approve", response_model=ApprovalResponse)
@require_permission("approvals", "write")
async def approve_action(action_id: str, request: Request) -> ApprovalResponse:
    reviewer = await _require_reviewer(request)
    repo = get_pending_action_repo(request)
    if await repo.get(action_id) is None:
        raise _not_found()
    approved = await repo.decide(action_id, approve=True, decided_by=reviewer)
    if approved is None:
        raise HTTPException(status_code=409, detail="This action was already decided")
    await _audit(request, "approvals.approved", reviewer, action_id, "success", {"action_type": approved["action_type"], "target": approved["target"]})
    outcome = await execute_approved(approved)
    settled = await repo.record_outcome(action_id, status=outcome.status, result=outcome.detail, error=outcome.error)
    await _audit(request, "approvals.executed", reviewer, action_id, "success" if outcome.status != "failed" else "failure", {"status": outcome.status, "error": outcome.error})
    return _out(settled or approved)


@router.post("/{action_id}/reject", response_model=ApprovalResponse)
@require_permission("approvals", "write")
async def reject_action(action_id: str, request: Request) -> ApprovalResponse:
    reviewer = await _require_reviewer(request)
    repo = get_pending_action_repo(request)
    if await repo.get(action_id) is None:
        raise _not_found()
    rejected = await repo.decide(action_id, approve=False, decided_by=reviewer)
    if rejected is None:
        raise HTTPException(status_code=409, detail="This action was already decided")
    await _audit(request, "approvals.rejected", reviewer, action_id, "success", None)
    return _out(rejected)
