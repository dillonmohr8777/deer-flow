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
from app.gateway.deps import get_agent_seat_repo, get_board_repo, get_ceo_desk_digest_repo, get_current_user_from_request, record_audit_event
from deerflow.board.workflow import latest_momo_draft_body
from deerflow.exec_seats import SeatTransitionError, assert_can_ratify, assert_can_reopen
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.persistence.exec_seats.model import AgentSeatStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import resolve_organization_id
from deerflow.tools.exec_seat_tools import announce_to_exec

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
    status: str
    draft_body: str | None
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


class SeatActionResponse(BaseModel):
    seat_id: str
    seat: str
    agent_name: str
    status: str


class DailyDigest(BaseModel):
    digest_text: str
    shipped_count: int
    stuck_count: int
    needs_my_yes_drafts: int
    needs_my_yes_ratifications: int
    created_at: str


class DailyDigestResponse(BaseModel):
    digest: DailyDigest | None


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


def _seat_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="No such seat claim in this organization")


@router.get("/needs-my-yes", response_model=NeedsMyYesResponse)
@require_permission("ceo", "read")
async def get_needs_my_yes(request: Request) -> NeedsMyYesResponse:
    """A ``drafted`` thread needs an Approve; an ``approved`` one still needs its
    explicit Send (``assert_can_reply``'s own separate owner action) -- both stay
    in the queue, with Momo's draft body attached, so a yes doesn't require a trip
    to the Board.
    """
    await _require_admin(request)
    board_repo = get_board_repo(request)
    seat_repo = get_agent_seat_repo(request)
    drafts = await board_repo.list_threads(status=BoardThreadStatus.DRAFTED)
    approved = await board_repo.list_threads(status=BoardThreadStatus.APPROVED)
    claims = await seat_repo.list_seats(status=AgentSeatStatus.CLAIMED)
    threads_awaiting_action = [*drafts, *approved]
    board_drafts = []
    for t in threads_awaiting_action:
        messages = await board_repo.list_messages(t["id"]) or []
        board_drafts.append(
            BoardDraftAwaitingApproval(
                thread_id=t["id"],
                client_id=t.get("client_id"),
                kind=t["kind"],
                subject=t.get("subject", ""),
                status=t["status"],
                draft_body=latest_momo_draft_body(messages),
                updated_at=t.get("updated_at", ""),
            )
        )
    return NeedsMyYesResponse(
        board_drafts=board_drafts,
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


@router.post("/seats/{seat_id}/ratify", response_model=SeatActionResponse)
@require_permission("ceo", "write")
async def ratify_seat(seat_id: str, request: Request) -> SeatActionResponse:
    """One-tap confirm of a claimed seat from the needs-my-yes queue.

    Mirrors ``deerflow.tools.exec_seat_tools.exec_ratify_seat``'s rules, minus
    the ``actor_is_ceo`` path: an HTTP caller has no agent identity to check,
    so ratifying here is always the organization-owner/admin path
    ``assert_can_ratify`` already grants (``_require_admin`` has confirmed
    that by the time this runs). The self-ratification refusal still applies:
    the admin who claimed the seat cannot also be the one who confirms it.
    """
    user_id = await _require_admin(request)
    seat_repo = get_agent_seat_repo(request)
    seat = await seat_repo.get_seat(seat_id)
    if seat is None:
        raise _seat_not_found()
    if seat.get("claimed_by_user_id") is not None and seat["claimed_by_user_id"] == user_id:
        await record_audit_event(request, action="ceo.seat.ratify", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="agent_seat", target_id=seat_id)
        raise HTTPException(status_code=403, detail="An admin cannot ratify a seat they claimed themselves; ratification requires an independent actor.")
    try:
        # actor_is_owner is always True here: _require_admin has already
        # confirmed it, and an HTTP caller has no agent identity for the
        # actor_is_ceo path, so SeatAuthorizationError can never fire.
        assert_can_ratify(seat["status"], actor_is_ceo=False, actor_is_owner=True)
    except SeatTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    ratified = await seat_repo.patch_seat(seat_id, status=AgentSeatStatus.RATIFIED, ratified_by_user_id=user_id)
    if ratified is None:
        raise _seat_not_found()
    await record_audit_event(request, action="ceo.seat.ratify", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="agent_seat", target_id=seat_id)
    # Best-effort, matches exec_ratify_seat's own #exec announcement wording;
    # a missing channel or storage hiccup must never undo the ratification
    # that already persisted above.
    await announce_to_exec(f"ratified {ratified['seat']} for {ratified['agent_name']} (model: {ratified.get('model_family') or 'muse'}) via CEO Desk")
    return SeatActionResponse(seat_id=ratified["id"], seat=ratified["seat"], agent_name=ratified["agent_name"], status=ratified["status"])


@router.post("/seats/{seat_id}/reopen", response_model=SeatActionResponse)
@require_permission("ceo", "write")
async def reopen_seat(seat_id: str, request: Request) -> SeatActionResponse:
    """One-tap veto of a claimed or ratified seat from the needs-my-yes queue.

    Owner/admin-only override (EXECUTIVE.md rule 4), mirroring
    ``deerflow.tools.exec_seat_tools.exec_reopen_seat``: ``_require_admin``
    has already confirmed the caller before this runs, so ``assert_can_reopen``
    is always called with ``actor_is_owner=True``.
    """
    user_id = await _require_admin(request)
    seat_repo = get_agent_seat_repo(request)
    seat = await seat_repo.get_seat(seat_id)
    if seat is None:
        raise _seat_not_found()
    try:
        assert_can_reopen(seat["status"], actor_is_owner=True)
    except SeatTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    reopened = await seat_repo.patch_seat(seat_id, status=AgentSeatStatus.REOPENED)
    if reopened is None:
        raise _seat_not_found()
    await record_audit_event(request, action="ceo.seat.reopen", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="agent_seat", target_id=seat_id)
    # Best-effort, matches exec_reopen_seat's own #exec announcement wording.
    await announce_to_exec(f"reopened {reopened['seat']} (was held by {reopened['agent_name']}) via CEO Desk")
    return SeatActionResponse(seat_id=reopened["id"], seat=reopened["seat"], agent_name=reopened["agent_name"], status=reopened["status"])


@router.get("/digest", response_model=DailyDigestResponse)
@require_permission("ceo", "read")
async def get_digest(request: Request) -> DailyDigestResponse:
    """The most recent generated daily digest, or ``None`` before the first one runs.

    Read-only: this endpoint never generates a digest itself, only reads
    what the background sweep (``deerflow.ceo_desk.digest.run_ceo_desk_digest``,
    gated by ``config.ceo_desk.digest_enabled``) has already recorded.
    """
    await _require_admin(request)
    digest_repo = get_ceo_desk_digest_repo(request)
    latest = await digest_repo.latest_digest()
    if latest is None:
        return DailyDigestResponse(digest=None)
    return DailyDigestResponse(
        digest=DailyDigest(
            digest_text=latest.get("digest_text", ""),
            shipped_count=latest.get("shipped_count", 0),
            stuck_count=latest.get("stuck_count", 0),
            needs_my_yes_drafts=latest.get("needs_my_yes_drafts", 0),
            needs_my_yes_ratifications=latest.get("needs_my_yes_ratifications", 0),
            created_at=latest.get("created_at", ""),
        )
    )
