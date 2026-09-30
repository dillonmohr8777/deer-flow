"""Read-only CEO Desk API (queue item e14, backend slice 1).

Backs ``/workspace/ceo``'s "needs my yes" queue and agent-seat roster
(the daily digest and the frontend page itself are a later slice). Owner/admin
only, unlike the Momo Board's per-client access: a plain member or a client
sees the whole organization's queue and roster if let in at all, so a
non-admin gets a flat 403 here rather than ``board.py``'s "foreign looks
missing" 404.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.gateway.authz import require_permission
from app.gateway.deps import get_agent_seat_repo, get_board_repo, get_current_user_from_request
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.persistence.exec_seats.model import AgentSeatStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import resolve_organization_id

router = APIRouter(prefix="/api/ceo", tags=["ceo"])

_ORG_ADMIN_ROLES = ("owner", "admin")
# Matches deerflow.exec_seats.budget's trailing-week window, so the roster's
# burn figure is the same number that would pause the seat.
_BUDGET_WINDOW = timedelta(days=7)


class BoardDraftAwaitingApproval(BaseModel):
    thread_id: str
    client_id: str | None
    kind: str
    subject: str
    updated_at: str


class SeatAwaitingRatification(BaseModel):
    seat_id: str
    seat: str
    agent_name: str
    claimed_by_user_id: str | None
    created_at: str


class NeedsMyYesResponse(BaseModel):
    board_drafts: list[BoardDraftAwaitingApproval]
    seat_ratifications: list[SeatAwaitingRatification]


class SeatRosterEntry(BaseModel):
    seat_id: str
    seat: str
    agent_name: str
    kpi: str
    status: str
    weekly_token_budget: int
    burn_this_week: int
    paused: bool


class SeatRosterResponse(BaseModel):
    seats: list[SeatRosterEntry]


async def _is_active_org_admin(user_id: str) -> bool:
    """Whether *user_id* is an active owner/admin of the caller's active organization.

    Mirrors ``board.py``'s helper of the same name.
    """
    organization_id = resolve_organization_id()
    if organization_id is None:
        return False
    # Lazy import: resolved at call time so a test's
    # ``monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", ...)``
    # takes effect, matching ``board.py``.
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return False
    stmt = select(OrganizationMemberRow.user_id).where(
        OrganizationMemberRow.organization_id == organization_id,
        OrganizationMemberRow.user_id == user_id,
        OrganizationMemberRow.status == "active",
        OrganizationMemberRow.role.in_(_ORG_ADMIN_ROLES),
    )
    async with session_factory() as session:
        return (await session.execute(stmt)).scalars().first() is not None


async def _require_admin(request: Request) -> str:
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    if not await _is_active_org_admin(user_id):
        raise HTTPException(status_code=403, detail="The CEO Desk is for an organization owner/admin only")
    return user_id


@router.get("/needs-my-yes", response_model=NeedsMyYesResponse)
@require_permission("ceo", "read")
async def get_needs_my_yes(request: Request) -> NeedsMyYesResponse:
    await _require_admin(request)
    board_repo = get_board_repo(request)
    seat_repo = get_agent_seat_repo(request)
    drafts = await board_repo.list_threads(status=BoardThreadStatus.DRAFTED)
    claims = await seat_repo.list_seats(status=AgentSeatStatus.CLAIMED)
    return NeedsMyYesResponse(
        board_drafts=[
            BoardDraftAwaitingApproval(
                thread_id=t["id"],
                client_id=t.get("client_id"),
                kind=t["kind"],
                subject=t.get("subject", ""),
                updated_at=t.get("updated_at", ""),
            )
            for t in drafts
        ],
        seat_ratifications=[
            SeatAwaitingRatification(
                seat_id=s["id"],
                seat=s["seat"],
                agent_name=s["agent_name"],
                claimed_by_user_id=s.get("claimed_by_user_id"),
                created_at=s.get("created_at", ""),
            )
            for s in claims
        ],
    )


@router.get("/seats", response_model=SeatRosterResponse)
@require_permission("ceo", "read")
async def get_seat_roster(request: Request) -> SeatRosterResponse:
    await _require_admin(request)
    seat_repo = get_agent_seat_repo(request)
    seats = await seat_repo.list_seats()
    since = datetime.now(UTC) - _BUDGET_WINDOW
    entries = [
        SeatRosterEntry(
            seat_id=s["id"],
            seat=s["seat"],
            agent_name=s["agent_name"],
            kpi=s.get("kpi", ""),
            status=s["status"],
            weekly_token_budget=s.get("weekly_token_budget", 0),
            burn_this_week=await seat_repo.token_burn_since(organization_id=s["organization_id"], agent_name=s["agent_name"], since=since),
            paused=s.get("paused_at") is not None,
        )
        for s in seats
    ]
    return SeatRosterResponse(seats=entries)
