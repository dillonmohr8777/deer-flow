"""Fleet-agent tools for Momentum agent seats (``deerflow.exec_seats``, queue item e9).

Three tools, gated behind the ``exec`` tool group in an agent's
``config.yaml``: claim a title, ratify a claim, and an owner veto (reopen).
Each is a thin wrapper around ``deerflow.exec_seats.workflow``'s pure
``assert_can_*`` checks plus ``AgentSeatRepository`` -- this module resolves
the two facts the workflow needs (is the acting agent the ratified CEO
holder, is the acting user an organization owner/admin) and persists the
result. Every successful call also best-effort-announces itself to the
``#exec`` Team Board channel (``deerflow.tools.team_board_tools``'s
``_ALLOWED_CHANNELS``), so a title claim, confirmation, or veto is visible
the same way the human Team Board is -- a missing ``#exec`` channel or a
storage hiccup never blocks the seat mutation itself, since the seat table
is the durable record either way.

Momentum-staff only, exactly like ``team_board_tools``: EXECUTIVE.md's whole
titles-and-hiring system is an internal Momentum staff process, never a
client-facing one.

``actor_is_ceo`` trusts the run's self-declared ``agent_name`` context field
(matched against the ratified CEO seat's own ``agent_name``) -- the same
trust level ``team_board_tools`` already gives that field when signing a
post. ``actor_is_owner`` is a real organization-membership check (owner or
admin, mirroring ``app/gateway/routers/board.py``'s ``_is_active_org_admin``;
the query is duplicated here rather than imported, because harness code
never imports from ``app``).
"""

from __future__ import annotations

from typing import Annotated

from langchain.tools import tool
from pydantic import Field
from sqlalchemy import select

from deerflow.exec_seats import SeatAuthorizationError, SeatTransitionError, assert_can_claim, assert_can_ratify, assert_can_reopen
from deerflow.persistence.exec_seats import AgentSeatRepository, AgentSeatStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import resolve_organization_id, resolve_runtime_actor_user_id
from deerflow.tools.types import Runtime

CEO_SEAT = "CEO (chief of staff)"

_ORG_ADMIN_ROLES = ("owner", "admin")
_EXEC_CHANNEL = "exec"


def _error(message: str) -> dict:
    return {"error": message}


def _staff_only_error() -> dict:
    return _error("Agent seat tools are restricted to Momentum staff.")


def _is_momentum_staff_run(runtime: Runtime | None) -> bool:
    """Read the server-stamped ``momentum_staff`` flag (never client-supplied)."""
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("momentum_staff") is True


def _agent_name(runtime: Runtime | None) -> str:
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("agent_name") or "agent"


def _get_repo() -> AgentSeatRepository | None:
    """A stateless repository bound to the process's current session factory.

    Lazy import so a test's monkeypatched session factory takes effect,
    matching ``team_board_tools.py``'s ``_get_repo``.
    """
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return AgentSeatRepository(session_factory)


async def _is_active_org_admin(user_id: str) -> bool:
    """Whether *user_id* is an active owner/admin of the caller's active organization.

    Mirrors ``app/gateway/routers/board.py``'s helper of the same name.
    """
    organization_id = resolve_organization_id()
    if organization_id is None:
        return False
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
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def _actor_is_ceo(repo: AgentSeatRepository, agent_name: str) -> bool:
    holder = await repo.ratified_holder(CEO_SEAT)
    return holder is not None and holder["agent_name"] == agent_name


async def _announce(runtime: Runtime | None, text: str) -> None:
    """Best-effort post of *text* to ``#exec``. Never raises -- a missing channel
    or storage hiccup must not undo a seat mutation that already persisted."""
    try:
        from deerflow.tools.team_board_tools import _find_channel
        from deerflow.tools.team_board_tools import _get_repo as _get_team_repo

        team_repo = _get_team_repo()
        if team_repo is None:
            return
        channel = await _find_channel(team_repo, _EXEC_CHANNEL)
        if channel is None:
            return
        author_user_id = resolve_runtime_actor_user_id(runtime)
        agent_name = _agent_name(runtime)
        await team_repo.add_message(channel["id"], author_user_id=author_user_id, body=f"[{agent_name}] {text}")
    except Exception:  # noqa: BLE001 -- an announcement failure must never mask a real result
        pass


async def _exec_claim_seat_impl(seat: str, scope: str, kpi: str, weekly_token_budget: int, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    repo = _get_repo()
    if repo is None:
        return _error("Agent seat storage is unavailable.")
    current = await repo.latest_claim_for_seat(seat)
    try:
        assert_can_claim(current["status"] if current else None)
    except SeatTransitionError as exc:
        return _error(str(exc))
    agent_name = _agent_name(runtime)
    claimed_by_user_id = resolve_runtime_actor_user_id(runtime)
    try:
        claimed = await repo.claim_seat(seat=seat, agent_name=agent_name, scope=scope, kpi=kpi, weekly_token_budget=weekly_token_budget, claimed_by_user_id=claimed_by_user_id)
    except SeatTransitionError as exc:
        # Lost a race against another concurrent claim on the same seat;
        # uq_agent_seats_open_claim caught what the check above couldn't.
        return _error(str(exc))
    await _announce(runtime, f"claimed {seat} (kpi: {kpi}, weekly budget: {weekly_token_budget})")
    return claimed


async def _exec_ratify_seat_impl(seat_id: str, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    repo = _get_repo()
    if repo is None:
        return _error("Agent seat storage is unavailable.")
    seat = await repo.get_seat(seat_id)
    if seat is None:
        return _error("No such seat claim in this organization.")
    agent_name = _agent_name(runtime)
    actor_user_id = resolve_runtime_actor_user_id(runtime)
    if seat["agent_name"] == agent_name or (seat["claimed_by_user_id"] is not None and seat["claimed_by_user_id"] == actor_user_id):
        # f84 (review follow-up): `agent_name` alone is bypassable -- it's a
        # client-choosable context field (services.py), so the same person
        # who claimed a seat as "cmo-agent" can just declare their ratify run
        # "ceo-agent" and pass the exact-name check while keeping every real
        # fact about the request (the acting human) identical. Comparing the
        # actor's real user id against who actually claimed the seat can't be
        # renamed away, and is the only reliable signal that this is really
        # the same actor confirming their own work, whatever name the run
        # declares or which authority channel (`actor_is_ceo`/`actor_is_owner`)
        # would otherwise let it through.
        return _error("An agent cannot ratify its own claim; ratification requires an independent actor.")
    actor_is_ceo = await _actor_is_ceo(repo, agent_name)
    actor_is_owner = await _is_active_org_admin(actor_user_id)
    try:
        assert_can_ratify(seat["status"], actor_is_ceo=actor_is_ceo, actor_is_owner=actor_is_owner)
    except (SeatAuthorizationError, SeatTransitionError) as exc:
        return _error(str(exc))
    ratified = await repo.patch_seat(seat_id, status=AgentSeatStatus.RATIFIED, ratified_by_user_id=actor_user_id)
    if ratified is None:
        return _error("No such seat claim in this organization.")
    await _announce(runtime, f"ratified {ratified['seat']} for {ratified['agent_name']}")
    return ratified


async def _exec_reopen_seat_impl(seat_id: str, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    repo = _get_repo()
    if repo is None:
        return _error("Agent seat storage is unavailable.")
    seat = await repo.get_seat(seat_id)
    if seat is None:
        return _error("No such seat claim in this organization.")
    actor_user_id = resolve_runtime_actor_user_id(runtime)
    actor_is_owner = await _is_active_org_admin(actor_user_id)
    try:
        assert_can_reopen(seat["status"], actor_is_owner=actor_is_owner)
    except (SeatAuthorizationError, SeatTransitionError) as exc:
        return _error(str(exc))
    reopened = await repo.patch_seat(seat_id, status=AgentSeatStatus.REOPENED)
    if reopened is None:
        return _error("No such seat claim in this organization.")
    await _announce(runtime, f"reopened {reopened['seat']} (was held by {reopened['agent_name']})")
    return reopened


@tool(parse_docstring=True)
async def exec_claim_seat(
    seat: str,
    scope: str,
    kpi: str,
    runtime: Runtime,
    weekly_token_budget: Annotated[int, Field(ge=0)] = 0,
) -> dict:
    """Claim a Momentum title from EXECUTIVE.md's slate, or propose a new one.

    Momentum-staff only. A title may be claimed when nobody has ever claimed
    it, or an owner has since reopened it (a fresh claim on an
    already-claimed-but-unratified title is a separate row -- EXECUTIVE.md's
    "Confirm" step resolves the overlap, not this tool). Announces the claim
    to #exec on success.

    Args:
        seat: Title name, e.g. "CMO" or "CEO (chief of staff)".
        scope: One-line job scope for this claim.
        kpi: The metric this seat is accountable for.
        runtime: Injected tool runtime; supplies the claiming agent's name and acting user.
        weekly_token_budget: Requested weekly token budget for this seat (default 0).

    Returns:
        The created seat claim ({"id", "seat", "status": "claimed", ...}), or {"error": ...}.
    """
    return await _exec_claim_seat_impl(seat, scope, kpi, weekly_token_budget, runtime=runtime)


@tool(parse_docstring=True)
async def exec_ratify_seat(
    seat_id: str,
    runtime: Runtime,
) -> dict:
    """Confirm (ratify) a claimed Momentum title, closing EXECUTIVE.md's "Confirm" step.

    Momentum-staff only. Only the agent holding the ratified CEO seat, or the
    organization owner, may ratify -- the owner also covers the bootstrap
    case where no CEO has been ratified yet. Ratification always needs an
    independent actor: refused whenever the acting agent's declared name
    matches the seat's own, or whenever the acting user is the same person
    who claimed the seat, whatever name the ratifying run declares. Announces
    the ratification to #exec on success.

    Args:
        seat_id: The id of the claimed seat row to ratify.
        runtime: Injected tool runtime; used to check whether the caller is the ratified CEO holder or an organization owner/admin.

    Returns:
        The updated seat ({"status": "ratified", ...}), or {"error": ...}.
    """
    return await _exec_ratify_seat_impl(seat_id, runtime=runtime)


@tool(parse_docstring=True)
async def exec_reopen_seat(
    seat_id: str,
    runtime: Runtime,
) -> dict:
    """Reopen (veto) a claimed or ratified Momentum title -- EXECUTIVE.md rule 4.

    Momentum-staff only. Owner-only override, regardless of who claimed or
    ratified the seat: "reassigning any title" is never a fleet-agent
    decision. Announces the veto to #exec on success.

    Args:
        seat_id: The id of the seat row to reopen.
        runtime: Injected tool runtime; used to check whether the caller is an organization owner/admin.

    Returns:
        The updated seat ({"status": "reopened", ...}), or {"error": ...}.
    """
    return await _exec_reopen_seat_impl(seat_id, runtime=runtime)


async def announce_to_exec(text: str) -> None:
    """Post a system-level (no acting agent/tool run) notice to ``#exec``.

    Thin adapter around :func:`_announce` for callers with no ``Runtime``,
    e.g. ``deerflow.exec_seats.budget``'s weekly seat-budget check -- it runs
    inside the same organization storage context every other org-scoped
    background pass uses, but not inside an agent's tool call.
    """
    await _announce(None, text)
