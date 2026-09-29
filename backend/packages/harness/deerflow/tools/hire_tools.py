"""Fleet-agent tools for EXECUTIVE.md's Hiring section (queue item e12, hiring).

Two tools, gated behind the ``hire`` tool group in an agent's ``config.yaml``:
hire a new report, and retire one. Mirrors ``exec_seat_tools.py``'s shape
exactly -- Momentum-staff only, resolves the two facts
``deerflow.hiring.workflow``'s pure ``assert_can_*`` checks need, persists
the result, and best-effort-announces every mutation to ``#exec``.

"Any titled employee can hire and retire its own reports. No approval
needed." -- so unlike an agent seat's claim/ratify state machine, a hire
takes effect immediately once the workflow checks pass; there is no ratify
step. The hiring manager is resolved from the run's own declared identity
(``runtime.context["agent_name"]``, the same trust level
``exec_seat_tools.py``/``team_board_tools.py`` already give that field): it
must be either a ratified ``agent_seats`` holder (a titled employee, depth 1)
or one of that system's own active hires (depth 2+) -- anyone else gets
``HireAuthorizationError``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain.tools import tool
from pydantic import Field

from deerflow.config import get_app_config
from deerflow.hiring import HireError, RetireError, assert_can_hire, assert_can_retire
from deerflow.persistence.hiring import HiredAgentRepository
from deerflow.runtime.user_context import resolve_organization_id, resolve_runtime_actor_user_id
from deerflow.tools.exec_seat_tools import _agent_name, _announce, _is_active_org_admin, _is_momentum_staff_run
from deerflow.tools.types import Runtime


def _error(message: str) -> dict:
    return {"error": message}


def _staff_only_error() -> dict:
    return _error("Agent hiring tools are restricted to Momentum staff.")


def _no_organization_error() -> dict:
    return _error("Agent hiring tools require an organization context.")


def _get_seat_repo():
    """Lazy import so a test's monkeypatched session factory takes effect."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.exec_seats import AgentSeatRepository

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return AgentSeatRepository(session_factory)


def _get_hire_repo() -> HiredAgentRepository | None:
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return HiredAgentRepository(session_factory)


async def _resolve_manager(seat_repo, hire_repo: HiredAgentRepository, manager_agent_name: str) -> dict | None:
    """The hiring manager's depth/model/tool-ceiling/budget facts, or ``None`` if it may not hire at all.

    A ratified seat holder is depth 1 with no tracked tool ceiling (titled
    employees are real, already-vetted Momentum staff -- "no escalation" only
    starts to bite once a hire itself starts hiring). An active hire is
    whatever depth/model/tools/budget it was itself hired with.
    """
    seat = await seat_repo.ratified_seat_for_agent(manager_agent_name)
    if seat is not None:
        return {
            "depth": 1,
            "model_family": seat.get("model_family") or "muse",
            "tool_groups": None,
            "weekly_token_budget": seat["weekly_token_budget"],
        }
    hire = await hire_repo.get_active_hire_by_agent_name(manager_agent_name)
    if hire is not None:
        return {
            "depth": hire["depth"],
            "model_family": hire["model_family"],
            "tool_groups": hire["tool_groups"],
            "weekly_token_budget": hire["weekly_token_budget"],
        }
    return None


async def _hire_report_impl(
    agent_name: str,
    title: str,
    job: str,
    kpi: str,
    tool_groups: list[str],
    weekly_token_budget: int,
    model_family: str,
    private_data: bool,
    runtime: Runtime | None = None,
) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    if resolve_organization_id() is None:
        return _no_organization_error()
    seat_repo = _get_seat_repo()
    hire_repo = _get_hire_repo()
    if seat_repo is None or hire_repo is None:
        return _error("Agent hiring storage is unavailable.")

    manager_agent_name = _agent_name(runtime)
    manager = await _resolve_manager(seat_repo, hire_repo, manager_agent_name)
    if manager is None:
        return _error("Only a titled employee or one of its own active reports may hire.")

    existing = await hire_repo.get_active_hire_by_agent_name(agent_name)
    if existing is not None:
        return _error(f"{agent_name!r} is already an active report in this organization.")

    hiring_config = get_app_config().hiring
    carved_budget_so_far = await hire_repo.total_carved_budget(manager_agent_name)
    existing_headcount = await hire_repo.count_active()

    try:
        assert_can_hire(
            manager_depth=manager["depth"],
            max_org_depth=hiring_config.max_org_depth,
            manager_tool_groups=manager["tool_groups"],
            requested_tool_groups=tool_groups,
            manager_model_family=manager["model_family"],
            requested_model_family=model_family,
            requested_private_data=private_data,
            manager_weekly_token_budget=manager["weekly_token_budget"],
            carved_budget_so_far=carved_budget_so_far,
            requested_weekly_token_budget=weekly_token_budget,
            existing_headcount=existing_headcount,
            headcount_cap=hiring_config.headcount_cap,
        )
    except HireError as exc:
        return _error(str(exc))

    hired_by_user_id = resolve_runtime_actor_user_id(runtime)
    hired = await hire_repo.create_hire(
        agent_name=agent_name,
        title=title,
        manager_agent_name=manager_agent_name,
        depth=manager["depth"] + 1,
        job=job,
        kpi=kpi,
        model_family=model_family,
        tool_groups=tool_groups,
        private_data=private_data,
        weekly_token_budget=weekly_token_budget,
        hired_by_user_id=hired_by_user_id,
    )
    await _announce(
        runtime,
        f"hired {hired['agent_name']} as {title} (manager: {manager_agent_name}, model: {model_family}, kpi: {kpi}, weekly budget: {weekly_token_budget})",
    )
    return hired


async def _retire_report_impl(hire_id: str, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    if resolve_organization_id() is None:
        return _no_organization_error()
    hire_repo = _get_hire_repo()
    if hire_repo is None:
        return _error("Agent hiring storage is unavailable.")
    hire = await hire_repo.get_hire(hire_id)
    if hire is None:
        return _error("No such hire in this organization.")

    actor_agent_name = _agent_name(runtime)
    actor_user_id = resolve_runtime_actor_user_id(runtime)
    actor_is_owner = await _is_active_org_admin(actor_user_id)
    try:
        assert_can_retire(
            hire_status=hire["status"],
            hire_manager_agent_name=hire["manager_agent_name"],
            actor_agent_name=actor_agent_name,
            actor_is_owner=actor_is_owner,
        )
    except RetireError as exc:
        return _error(str(exc))

    retired = await hire_repo.retire(hire_id, retired_by_user_id=actor_user_id)
    if retired is None:
        return _error("No such hire in this organization.")
    await _announce(runtime, f"retired {retired['agent_name']} (was hired by {retired['manager_agent_name']})")
    return retired


@tool(parse_docstring=True)
async def hire_report(
    agent_name: str,
    title: str,
    job: str,
    kpi: str,
    tool_groups: list[str],
    runtime: Runtime,
    weekly_token_budget: Annotated[int, Field(ge=0)] = 0,
    model_family: Literal["luna", "muse"] = "muse",
    private_data: bool = False,
) -> dict:
    """Hire a new report under the calling agent, per EXECUTIVE.md's Hiring section.

    Momentum-staff only. The caller must already be a titled employee (a
    ratified agent-seat holder) or one of that system's own active hires --
    anyone else is refused. No approval needed: the hire takes effect
    immediately once every check passes (tools and data access are a subset
    of the caller's own; private-data access needs a Luna caller and a Luna
    hire; the requested budget is carved from the caller's own remaining
    budget; the organization's headcount cap and org-depth cap both hold).
    Announces the hire to #exec on success.

    Args:
        agent_name: Chosen identity for the new hire; must not already be an active report in this organization.
        title: Job title, e.g. "Content Writer".
        job: One-line job scope.
        kpi: The metric this hire is accountable for.
        tool_groups: Tool groups to grant; must be a subset of the caller's own.
        runtime: Injected tool runtime; supplies the hiring agent's name and acting user.
        weekly_token_budget: Requested weekly token budget, carved from the caller's own remaining budget (default 0 = unlimited, only valid under an unlimited caller).
        model_family: "muse" (default) or "luna". Only a Luna caller may set this to "luna" for private-data access.
        private_data: Whether this hire needs private client data. Requires a Luna caller and model_family="luna".

    Returns:
        The created hire ({"id", "agent_name", "status": "active", ...}), or {"error": ...}.
    """
    return await _hire_report_impl(agent_name, title, job, kpi, tool_groups, weekly_token_budget, model_family, private_data, runtime=runtime)


@tool(parse_docstring=True)
async def retire_report(
    hire_id: str,
    runtime: Runtime,
) -> dict:
    """Retire one of the calling agent's own reports, per EXECUTIVE.md's Hiring section.

    Momentum-staff only. Only the hire's own hiring manager, or the
    organization owner, may retire it -- "own reports" is not transitive: a
    manager cannot retire a report's own reports directly. Announces the
    retirement to #exec on success.

    Args:
        hire_id: The id of the hire row to retire.
        runtime: Injected tool runtime; used to check whether the caller is the hiring manager or an organization owner/admin.

    Returns:
        The updated hire ({"status": "retired", ...}), or {"error": ...}.
    """
    return await _retire_report_impl(hire_id, runtime=runtime)
