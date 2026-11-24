"""Workspace-scoped Reports & Leads API.

Provides read-only KPI summaries, named-lead match-back rows, Plane 0 read
connector health, and Google Doc review/approval state transitions strictly
isolated to the caller's active workspace (``organization_id``).

Invariants:
- Staff-only access: external client contacts receive 403 (fail closed).
- Strict workspace isolation: every query filters by the server-resolved active
  ``organization_id``; cross-workspace IDs return 404.
- Integer-only verified leads (forms, calls, appointments) -- clicks and other
  non-lead engagement signals are excluded by schema and aggregation.
- Missing, pending, or unavailable feeds return ``None`` totals with an explicit
  ``pending`` or ``unavailable`` state -- never fabricated zeros.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.gateway.client_boundary import CLIENT_ROLE
from app.gateway.deps import get_current_user_from_request, record_audit_event
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.persistence.reports import ReportsRepository
from deerflow.reports.schema import (
    ConnectorKey,
    ConnectorStatus,
    DataState,
    LeadCategory,
    MatchConfidence,
    MatchStatus,
    ReportingPeriod,
    ReviewDocStatus,
    validate_google_doc_url,
    validate_lead_category,
)
from deerflow.runtime.user_context import resolve_organization_id


async def _staff_reports_only(request: Request) -> None:
    from app.gateway.client_workspace import is_client_contact

    user = await get_current_user_from_request(request)
    if getattr(user, "system_role", None) == CLIENT_ROLE or await is_client_contact(user):
        raise HTTPException(status_code=403, detail="Staff reporting access required")


router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(_staff_reports_only)])


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadKpiResponse(BaseModel):
    total_leads: int | None = None
    forms: int | None = None
    calls: int | None = None
    appointments: int | None = None
    appointment_label: str
    matched_leads: int | None = None
    data_state: DataState
    connected_lead_sources: list[str]
    pending_lead_sources: list[str]
    unavailable_lead_sources: list[str]
    excluded_non_lead_signals: list[str]


class ConnectorsSummaryResponse(BaseModel):
    connected: int
    stale: int
    pending: int
    unavailable: int


class ReviewDocsSummaryResponse(BaseModel):
    total: int
    pending_review: int
    approved: int
    needs_edits: int


class ReportSummaryResponse(BaseModel):
    workspace_id: str
    workspace_name: str | None = None
    period: ReportingPeriod
    window_start: str
    window_end: str
    kpis: LeadKpiResponse
    connectors_summary: ConnectorsSummaryResponse
    review_docs_summary: ReviewDocsSummaryResponse


class LeadRecordResponse(BaseModel):
    id: str
    workspace_id: str
    lead_name: str
    lead_type: LeadCategory
    channel: str
    source_connector: ConnectorKey
    campaign_name: str
    external_lead_id: str | None = None
    match_status: MatchStatus
    match_confidence: MatchConfidence
    occurred_at: str
    notes: str
    created_at: str


class ReportLeadsResponse(BaseModel):
    workspace_id: str
    period: ReportingPeriod
    data_state: DataState
    total_count: int
    leads: list[LeadRecordResponse]


class ConnectorHealthResponse(BaseModel):
    connector_key: ConnectorKey
    display_name: str
    status: ConnectorStatus
    provides_leads: bool
    capability_summary: str
    external_account_ref: str | None = None
    last_synced_at: str | None = None
    detail: str
    required_credential_refs: list[str]


class ReportConnectorsResponse(BaseModel):
    workspace_id: str
    connectors: list[ConnectorHealthResponse]


class ReviewDocCommentResponse(BaseModel):
    id: str
    author_id: str
    author_label: str
    body: str
    created_at: str


class ReviewDocResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    doc_url: str
    period_key: ReportingPeriod
    status: ReviewDocStatus
    created_by: str
    decided_by: str | None = None
    decided_at: str | None = None
    comments: list[ReviewDocCommentResponse]
    created_at: str
    updated_at: str


class ReviewDocListResponse(BaseModel):
    workspace_id: str
    review_docs: list[ReviewDocResponse]


class CreateReviewDocRequest(_StrictBody):
    title: str = Field(min_length=1, max_length=255)
    doc_url: str = Field(min_length=1, max_length=1024)
    period_key: ReportingPeriod = "last_30d"

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title must not be blank")
        return cleaned

    @field_validator("doc_url")
    @classmethod
    def _validate_doc_url(cls, value: str) -> str:
        return validate_google_doc_url(value)


class UpdateReviewDocRequest(_StrictBody):
    status: ReviewDocStatus | None = None
    comment: str | None = Field(default=None, max_length=4000)


def _get_reports_repo(request: Request) -> ReportsRepository:
    repo = getattr(request.app.state, "reports_repo", None)
    if repo is not None:
        return repo
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Reports persistence is unavailable")
    return ReportsRepository(sf)


async def _workspace_context(request: Request) -> tuple[str, str, str]:
    """Return ``(actor_user_id, actor_label, active_workspace_id)`` or fail closed."""
    user = await get_current_user_from_request(request)
    workspace_id = resolve_organization_id()
    if not workspace_id:
        raise HTTPException(status_code=403, detail="Active workspace membership required")
    expected = request.headers.get("X-Reports-Workspace")
    if expected is not None and expected.strip() and expected.strip() != workspace_id:
        raise HTTPException(status_code=409, detail="Workspace changed; reload reports")
    actor_id = str(user.id)
    actor_label = (getattr(user, "display_name", None) or getattr(user, "email", None) or "Team member").strip()
    return actor_id, actor_label, workspace_id


async def _workspace_name(repo: ReportsRepository, workspace_id: str) -> str | None:
    async with repo.session_factory() as session:
        org = await session.get(OrganizationRow, workspace_id)
    return org.name if org is not None else None


@router.get("/summary", response_model=ReportSummaryResponse)
async def get_report_summary(
    request: Request,
    period: ReportingPeriod = Query(default="last_30d"),
) -> ReportSummaryResponse:
    _actor_id, _actor_label, workspace_id = await _workspace_context(request)
    repo = _get_reports_repo(request)
    summary = await repo.get_summary(workspace_id, period=period)
    summary["workspace_name"] = await _workspace_name(repo, workspace_id)
    return ReportSummaryResponse(**summary)


@router.get("/leads", response_model=ReportLeadsResponse)
async def list_report_leads(
    request: Request,
    period: ReportingPeriod = Query(default="last_30d"),
    lead_type: str | None = Query(default=None),
    match_status: MatchStatus | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReportLeadsResponse:
    _actor_id, _actor_label, workspace_id = await _workspace_context(request)
    validated_type: LeadCategory | None = None
    if lead_type is not None and lead_type.strip():
        try:
            validated_type = validate_lead_category(lead_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo = _get_reports_repo(request)
    summary = await repo.get_summary(workspace_id, period=period)
    leads, total_count = await repo.list_leads(
        workspace_id,
        period=period,
        lead_type=validated_type,
        match_status=match_status,
        channel=channel,
        limit=limit,
        offset=offset,
    )
    return ReportLeadsResponse(
        workspace_id=workspace_id,
        period=period,
        data_state=summary["kpis"]["data_state"],
        total_count=total_count,
        leads=[LeadRecordResponse(**item) for item in leads],
    )


@router.get("/connectors", response_model=ReportConnectorsResponse)
async def list_report_connectors(request: Request) -> ReportConnectorsResponse:
    _actor_id, _actor_label, workspace_id = await _workspace_context(request)
    repo = _get_reports_repo(request)
    connectors = await repo.list_connectors(workspace_id)
    return ReportConnectorsResponse(
        workspace_id=workspace_id,
        connectors=[ConnectorHealthResponse(**item) for item in connectors],
    )


@router.get("/review-docs", response_model=ReviewDocListResponse)
async def list_review_docs(
    request: Request,
    period: ReportingPeriod | None = Query(default=None),
    status: Literal["pending_review", "approved", "needs_edits"] | None = Query(default=None),
) -> ReviewDocListResponse:
    _actor_id, _actor_label, workspace_id = await _workspace_context(request)
    repo = _get_reports_repo(request)
    docs = await repo.list_review_docs(workspace_id, period=period, status=status)
    return ReviewDocListResponse(
        workspace_id=workspace_id,
        review_docs=[ReviewDocResponse(**doc) for doc in docs],
    )


@router.post("/review-docs", response_model=ReviewDocResponse, status_code=201)
async def create_review_doc(body: CreateReviewDocRequest, request: Request) -> ReviewDocResponse:
    actor_id, _actor_label, workspace_id = await _workspace_context(request)
    repo = _get_reports_repo(request)
    try:
        created = await repo.create_review_doc(
            workspace_id,
            title=body.title,
            doc_url=body.doc_url,
            period_key=body.period_key,
            created_by=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await record_audit_event(
        request,
        action="reports.review_doc.created",
        outcome="success",
        actor_user_id=actor_id,
        organization_id=workspace_id,
        target_type="report_review_doc",
        target_id=created["id"],
        details={"period_key": created["period_key"]},
    )
    return ReviewDocResponse(**created)


@router.patch("/review-docs/{doc_id}", response_model=ReviewDocResponse)
async def update_review_doc(doc_id: str, body: UpdateReviewDocRequest, request: Request) -> ReviewDocResponse:
    actor_id, actor_label, workspace_id = await _workspace_context(request)
    repo = _get_reports_repo(request)
    try:
        updated = await repo.update_review_doc(
            workspace_id,
            doc_id,
            actor_id=actor_id,
            actor_label=actor_label,
            status=body.status,
            comment=body.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Review document not found")
    await record_audit_event(
        request,
        action="reports.review_doc.updated",
        outcome="success",
        actor_user_id=actor_id,
        organization_id=workspace_id,
        target_type="report_review_doc",
        target_id=updated["id"],
        details={
            "status": updated["status"],
            "comment_added": bool(body.comment and body.comment.strip()),
        },
    )
    return ReviewDocResponse(**updated)
