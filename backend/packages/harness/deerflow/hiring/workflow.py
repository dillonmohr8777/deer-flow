"""Authorization checks for EXECUTIVE.md's Hiring section (queue item e12).

Pure decision logic, no I/O -- ``deerflow.tools.hire_tools`` resolves the
facts (who the hiring manager is, its depth/model/tools/budget, the
organization's current headcount and this manager's already-carved budget)
and calls :func:`assert_can_hire`/:func:`assert_can_retire`. Every branch maps
to one line of EXECUTIVE.md's Hiring section:

- "No escalation. A hire's tools and data access are a subset of its
  manager's." -> the tool-subset and private-data checks.
- "Only a Luna employee can hire into private data." -> the private-data
  check, both on the manager granting it and the hire itself.
- "Budget comes from the manager. A hire gets a slice of its manager's
  weekly token budget, never new money." -> the budget-carve check.
- "Caps. Headcount cap and org depth (3 levels) are Dillon's settings." ->
  the headcount and depth checks.
- "Any titled employee can hire and retire its own reports." -> retirement is
  refused for anyone but the hiring manager itself, or the organization owner
  (mirroring ``deerflow.exec_seats.workflow.assert_can_reopen``'s owner
  override).
"""

from __future__ import annotations

from deerflow.persistence.hiring.model import HireStatus

_RETIRE_FROM: frozenset[str] = frozenset({HireStatus.ACTIVE})


class HireError(Exception):
    """A requested hire is not allowed."""


class HireAuthorizationError(HireError):
    """The acting agent is not a titled employee or an active hire, so it cannot hire at all."""


class HireToolEscalationError(HireError):
    """The requested tools are not a subset of the manager's own tools."""


class HirePrivateDataError(HireError):
    """Private-data access was requested without a Luna manager, or for a non-Luna hire."""


class HireBudgetError(HireError):
    """The requested weekly token budget is not a valid slice of the manager's own budget."""


class HireHeadcountCapError(HireError):
    """The organization's owner-set headcount cap would be exceeded."""


class HireDepthCapError(HireError):
    """The hire would exceed the organization's owner-set org-depth cap."""


class RetireError(Exception):
    """A requested retirement is not allowed."""


class RetireAuthorizationError(RetireError):
    """Only the hiring manager or the organization owner may retire a report."""


class RetireTransitionError(RetireError):
    """The hire is not in a state that can be retired."""


def assert_can_hire(
    *,
    manager_depth: int,
    max_org_depth: int,
    manager_tool_groups: list[str] | None,
    requested_tool_groups: list[str],
    manager_model_family: str,
    requested_model_family: str,
    requested_private_data: bool,
    manager_weekly_token_budget: int,
    carved_budget_so_far: int,
    requested_weekly_token_budget: int,
    existing_headcount: int,
    headcount_cap: int,
) -> None:
    """Raise a :class:`HireError` subclass if this hire is not allowed; otherwise return.

    Args:
        manager_depth: The hiring manager's own depth (1 = a ratified titled
            employee; a hire's own depth is its manager's depth + 1).
        max_org_depth: Owner-set cap on how deep a hire chain may go.
        manager_tool_groups: The manager's own tool groups, or ``None`` when
            the manager is a depth-1 titled employee (no tracked ceiling --
            "no escalation" only bites once a hire itself starts hiring).
        requested_tool_groups: Tool groups requested for the new hire.
        manager_model_family: The manager's own model family ("luna"/"muse").
        requested_model_family: The model family requested for the new hire.
        requested_private_data: Whether the new hire needs private-data access.
        manager_weekly_token_budget: The manager's own weekly token budget
            (0 = unlimited, matching ``AgentSeatRepository.claim_seat``).
        carved_budget_so_far: Sum of the manager's other active reports'
            weekly_token_budget.
        requested_weekly_token_budget: Weekly token budget requested for the
            new hire (0 = unlimited).
        existing_headcount: The organization's current count of active hires.
        headcount_cap: Owner-set cap on active hires (0 = unlimited).
    """
    new_depth = manager_depth + 1
    if new_depth > max_org_depth:
        raise HireDepthCapError(f"Org depth cap is {max_org_depth} levels; a hire under this manager would reach depth {new_depth}")

    if manager_tool_groups is not None:
        escalated = sorted(set(requested_tool_groups) - set(manager_tool_groups))
        if escalated:
            raise HireToolEscalationError(f"A hire's tools must be a subset of its manager's; {escalated} would escalate beyond {sorted(manager_tool_groups)}")

    if requested_private_data:
        if manager_model_family != "luna":
            raise HirePrivateDataError("Only a Luna manager may hire into private data")
        if requested_model_family != "luna":
            raise HirePrivateDataError("A hire with private-data access must itself be a Luna employee")

    if manager_weekly_token_budget > 0:
        remaining = manager_weekly_token_budget - carved_budget_so_far
        if requested_weekly_token_budget <= 0 or requested_weekly_token_budget > remaining:
            raise HireBudgetError(f"A hire's budget is carved from its manager's; {max(remaining, 0)} tokens remain of a {manager_weekly_token_budget}-token weekly budget")

    if headcount_cap > 0 and existing_headcount + 1 > headcount_cap:
        raise HireHeadcountCapError(f"Headcount cap is {headcount_cap}; the organization already has {existing_headcount} active hires")


def assert_can_retire(*, hire_status: str, hire_manager_agent_name: str, actor_agent_name: str, actor_is_owner: bool) -> None:
    """ "Any titled employee can hire and retire its own reports" (EXECUTIVE.md) -- and only its own.

    The organization owner may also retire any report directly, the same
    override ``deerflow.exec_seats.workflow.assert_can_reopen`` gives for a
    title.
    """
    if hire_status not in _RETIRE_FROM:
        raise RetireTransitionError(f"Cannot retire a hire with status {hire_status!r}")
    if actor_is_owner:
        return
    if actor_agent_name != hire_manager_agent_name:
        raise RetireAuthorizationError("Only the hiring manager or the organization owner may retire this report")
