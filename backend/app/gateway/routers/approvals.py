"""Approvals inbox API: review, edit, approve or reject actions agents proposed.

Reads are owner-scoped (``user_id`` + active organization, via the repository;
a foreign row is a 404). Edit/approve/reject additionally need an active
organization owner/admin, since approving is what releases an outbound action.
Only the caller that wins the pending->approved compare-and-set runs the
adapter, so a double click or two reviewers can never send twice.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.approval_adapters import execute_approved
from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user_from_request, get_pending_action_repo, record_audit_event
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.routers.clients import _is_active_org_admin
from deerflow.approvals import InvalidPayloadError
from deerflow.factcheck import Evidence, check_for_filing, draft_text, verify_draft
from deerflow.persistence.approvals.corrections import ClientCorrectionRepository
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.runtime.user_context import resolve_organization_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/approvals", tags=["approvals"])

LOOP_FILING_SCOPE = "approvals:propose"
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
    fact_check: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]


class ApprovalEditRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    target: str | None = Field(default=None, max_length=512)
    payload: dict[str, Any] | None = None


class EvidenceIn(BaseModel):
    source: str = Field(max_length=255)
    text: str = Field(max_length=20_000)


class LoopFilingRequest(BaseModel):
    """A draft the Client Loop already made (Gmail/Slack draft exists) and wants reviewed here."""

    client: str = Field(min_length=1, max_length=128)
    action_type: Literal["slack_message", "email", "ad_change", "other"]
    title: str = Field(max_length=255)
    target: str = Field(max_length=512)
    payload: dict[str, Any]
    source_link: str = Field(default="", max_length=1024)
    draft_ref: dict[str, Any] | str | None = None
    thread: str | None = Field(default=None, max_length=128)
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=20)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Approval not found")


def _out(row: dict) -> ApprovalResponse:
    out = {k: row.get(k) for k in ApprovalResponse.model_fields}
    if out["fact_check"]:  # stored run evidence is for re-checks only, not for the page
        out["fact_check"] = {k: v for k, v in out["fact_check"].items() if k != "evidence"}
    return ApprovalResponse(**out)


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


@router.post("/propose", response_model=ApprovalResponse, status_code=201)
async def file_loop_action(body: LoopFilingRequest, request: Request) -> ApprovalResponse:
    """File a pending action for the delegation's owner. Internal delegated callers only; never sends.

    Same validation and fact check as the ``propose_action`` tool, with the caller's source text as evidence.
    The row stays pending until an owner/admin approves, edits or rejects it in the inbox.
    """
    # No route permission exists for this: the delegation itself must carry the ``approvals:propose`` scope,
    # which is not a user or PAT permission, so no browser session, PAT or other delegation can file this way.
    repo = get_pending_action_repo(request)
    delegation_id = getattr(request.state, "delegation_id", None)
    if get_trusted_internal_owner_user_id(request) is None or await OrganizationDelegationRepository(repo.session_factory).resolve_delegation_by_id(delegation_id, scope=LOOP_FILING_SCOPE) is None:
        raise HTTPException(status_code=403, detail="Only an internal caller with an approvals:propose delegation can file actions this way.")
    refusal, fact_check, _gate = check_for_filing(body.title, body.payload, [Evidence(e.source, e.text) for e in body.evidence])
    if refusal:
        raise HTTPException(status_code=422, detail=f"The draft contradicts its own sources: {refusal}.")
    payload = {**body.payload, "loop": {"client": body.client, "source_link": body.source_link, "draft_ref": body.draft_ref}}
    try:
        row = await repo.create(action_type=body.action_type, target=body.target, payload=payload, title=body.title, thread_id=body.thread, agent_name=body.client, fact_check=fact_check)
    except InvalidPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _audit(request, "approvals.proposed", str(request.state.actor_user_id), row["id"], "success", {"action_type": body.action_type, "client": body.client})
    return _out(row)


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


async def _recheck_if_edited(repo, row: dict) -> None:
    """Fact-check an edited payload before it is approved: contradicted refuses, unsupported updates the stored flag."""
    if row["status"] != "pending" or row["payload"] == row["original_payload"]:
        return
    stored = row.get("fact_check") or {}
    evidence = [Evidence(str(e.get("source", "")), str(e.get("text", ""))) for e in stored.get("evidence", []) if isinstance(e, dict)]
    report = verify_draft(draft_text(row["title"], row["payload"]), evidence)
    if report.blocked:
        bad = [c for c in report.to_dict()["claims"] if c["verdict"] == "contradicted"]
        raise HTTPException(status_code=422, detail="The edited text contradicts evidence from the original run: " + "; ".join(f'"{c["text"]}" ({c["reason"]})' for c in bad) + ". Fix or remove those claims, then approve again.")
    new = {**report.to_dict(), "evidence": stored.get("evidence", [])} if report.claims else None
    if new != row.get("fact_check"):
        await repo.set_fact_check(row["id"], new)


async def _record_correction(repo, approved: dict, reviewer: str) -> None:
    """Keep what the reviewer changed so later drafts for this client learn from it. Never blocks the approval."""
    try:
        await ClientCorrectionRepository(repo.session_factory).record_for_approval(approved, approver=reviewer)
    except Exception:
        logger.warning("could not record client correction for %s", approved.get("id"), exc_info=True)


@router.post("/{action_id}/approve", response_model=ApprovalResponse)
@require_permission("approvals", "write")
async def approve_action(action_id: str, request: Request) -> ApprovalResponse:
    reviewer = await _require_reviewer(request)
    repo = get_pending_action_repo(request)
    current = await repo.get(action_id)
    if current is None:
        raise _not_found()
    await _recheck_if_edited(repo, current)
    approved = await repo.decide(action_id, approve=True, decided_by=reviewer)
    if approved is None:
        raise HTTPException(status_code=409, detail="This action was already decided")
    await _audit(request, "approvals.approved", reviewer, action_id, "success", {"action_type": approved["action_type"], "target": approved["target"]})
    await _record_correction(repo, approved, reviewer)
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
