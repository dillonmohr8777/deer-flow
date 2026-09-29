"""Pure authorization tests for EXECUTIVE.md's Hiring section (queue item e12).

``deerflow.hiring.workflow`` has no I/O -- these tests exercise
``assert_can_hire``/``assert_can_retire`` directly, one check at a time,
mirroring ``test_board_workflow.py``'s "unit test the pure function" shape.
Persistence and the tool layer that resolves the facts these functions need
are covered by ``test_hire_tools.py``.
"""

from __future__ import annotations

import pytest

from deerflow.hiring.workflow import (
    HireBudgetError,
    HireDepthCapError,
    HireHeadcountCapError,
    HirePrivateDataError,
    HireToolEscalationError,
    RetireAuthorizationError,
    RetireHasActiveReportsError,
    RetireTransitionError,
    assert_can_hire,
    assert_can_retire,
)
from deerflow.persistence.hiring.model import HireStatus


def _kwargs(**overrides) -> dict:
    """A baseline set of args that passes every check, with overrides layered on."""
    base = dict(
        manager_depth=1,
        max_org_depth=3,
        manager_tool_groups=None,
        requested_tool_groups=["file:read", "bash"],
        known_tool_groups=None,
        manager_cleared_for_private_data=False,
        requested_model_family="muse",
        requested_private_data=False,
        manager_weekly_token_budget=1000,
        carved_budget_so_far=0,
        requested_weekly_token_budget=200,
        existing_headcount=0,
        headcount_cap=20,
    )
    base.update(overrides)
    return base


def test_a_passing_hire_raises_nothing():
    assert_can_hire(**_kwargs())  # must not raise


# --- tool subset of the manager ---


def test_depth_one_manager_has_no_tracked_tool_ceiling():
    """A ratified seat holder (depth 1) has no tracked tool_groups; no subset restriction applies yet."""
    assert_can_hire(**_kwargs(manager_tool_groups=None, requested_tool_groups=["file:read", "bash", "team", "exec"]))


def test_hire_manager_grants_only_its_own_tools():
    assert_can_hire(**_kwargs(manager_depth=2, manager_tool_groups=["file:read", "bash"], requested_tool_groups=["file:read", "bash"]))


def test_hire_manager_cannot_escalate_beyond_its_own_tools():
    with pytest.raises(HireToolEscalationError):
        assert_can_hire(**_kwargs(manager_depth=2, manager_tool_groups=["file:read"], requested_tool_groups=["file:read", "bash"]))


def test_an_unknown_tool_group_is_rejected_even_with_no_manager_ceiling():
    """review finding (medium 5): a depth-1 manager with no tracked ceiling
    could otherwise grant a made-up group name. known_tool_groups closes
    that off independently of manager_tool_groups."""
    with pytest.raises(HireToolEscalationError):
        assert_can_hire(**_kwargs(manager_tool_groups=None, known_tool_groups=frozenset({"file:read", "bash", "team", "exec", "hire"}), requested_tool_groups=["file:read", "made-up-group"]))


def test_a_known_tool_group_passes_with_no_manager_ceiling():
    assert_can_hire(**_kwargs(manager_tool_groups=None, known_tool_groups=frozenset({"file:read", "bash"}), requested_tool_groups=["file:read", "bash"]))


# --- private-data lane only from a Luna manager ---


def test_private_data_requires_a_manager_cleared_for_it():
    with pytest.raises(HirePrivateDataError):
        assert_can_hire(**_kwargs(manager_cleared_for_private_data=False, requested_private_data=True, requested_model_family="luna"))


def test_private_data_also_requires_the_hire_itself_be_luna():
    with pytest.raises(HirePrivateDataError):
        assert_can_hire(**_kwargs(manager_cleared_for_private_data=True, requested_private_data=True, requested_model_family="muse"))


def test_a_cleared_manager_may_hire_a_luna_report_into_private_data():
    assert_can_hire(**_kwargs(manager_cleared_for_private_data=True, requested_private_data=True, requested_model_family="luna"))


def test_a_muse_hire_with_no_private_data_needs_no_cleared_manager():
    assert_can_hire(**_kwargs(manager_cleared_for_private_data=False, requested_private_data=False, requested_model_family="muse"))


def test_a_luna_but_uncleared_manager_still_cannot_hire_into_private_data():
    """review finding (high 1): being a Luna model is not the same as being
    cleared for private data -- a Luna hire that was never itself granted
    private_data=True must not be able to grant it to its own report."""
    with pytest.raises(HirePrivateDataError):
        assert_can_hire(**_kwargs(manager_cleared_for_private_data=False, requested_private_data=True, requested_model_family="luna"))


# --- budget carved from the manager ---


def test_a_hire_budget_within_the_managers_remaining_budget_passes():
    assert_can_hire(**_kwargs(manager_weekly_token_budget=1000, carved_budget_so_far=400, requested_weekly_token_budget=600))


def test_a_hire_budget_exceeding_the_managers_remaining_budget_is_rejected():
    with pytest.raises(HireBudgetError):
        assert_can_hire(**_kwargs(manager_weekly_token_budget=1000, carved_budget_so_far=400, requested_weekly_token_budget=601))


def test_a_hire_cannot_request_unlimited_budget_from_a_capped_manager():
    with pytest.raises(HireBudgetError):
        assert_can_hire(**_kwargs(manager_weekly_token_budget=1000, carved_budget_so_far=0, requested_weekly_token_budget=0))


def test_an_unlimited_manager_may_grant_any_requested_budget():
    """manager_weekly_token_budget == 0 means unlimited -- no slice math applies."""
    assert_can_hire(**_kwargs(manager_weekly_token_budget=0, carved_budget_so_far=0, requested_weekly_token_budget=0))
    assert_can_hire(**_kwargs(manager_weekly_token_budget=0, carved_budget_so_far=0, requested_weekly_token_budget=999_999))


# --- owner-set headcount cap ---


def test_a_hire_under_the_headcount_cap_passes():
    assert_can_hire(**_kwargs(existing_headcount=19, headcount_cap=20))


def test_a_hire_at_the_headcount_cap_is_rejected():
    with pytest.raises(HireHeadcountCapError):
        assert_can_hire(**_kwargs(existing_headcount=20, headcount_cap=20))


def test_headcount_cap_zero_means_unlimited():
    assert_can_hire(**_kwargs(existing_headcount=10_000, headcount_cap=0))


# --- org depth cap ---


def test_a_hire_within_the_depth_cap_passes():
    assert_can_hire(**_kwargs(manager_depth=2, max_org_depth=3))  # new hire would be depth 3


def test_a_hire_exceeding_the_depth_cap_is_rejected():
    with pytest.raises(HireDepthCapError):
        assert_can_hire(**_kwargs(manager_depth=3, max_org_depth=3))  # new hire would be depth 4


def test_depth_one_manager_can_always_hire_under_a_cap_of_at_least_two():
    assert_can_hire(**_kwargs(manager_depth=1, max_org_depth=2))


# --- retire: own reports only ---


def test_the_hiring_manager_can_retire_its_own_report():
    assert_can_retire(hire_status=HireStatus.ACTIVE, hire_manager_agent_name="cmo-agent", actor_agent_name="cmo-agent", actor_is_owner=False)  # must not raise


def test_a_different_agent_cannot_retire_someone_elses_report():
    with pytest.raises(RetireAuthorizationError):
        assert_can_retire(hire_status=HireStatus.ACTIVE, hire_manager_agent_name="cmo-agent", actor_agent_name="cfo-agent", actor_is_owner=False)


def test_the_owner_can_retire_any_report():
    assert_can_retire(hire_status=HireStatus.ACTIVE, hire_manager_agent_name="cmo-agent", actor_agent_name="owner-agent", actor_is_owner=True)  # must not raise


def test_an_already_retired_hire_cannot_be_retired_again():
    with pytest.raises(RetireTransitionError):
        assert_can_retire(hire_status=HireStatus.RETIRED, hire_manager_agent_name="cmo-agent", actor_agent_name="cmo-agent", actor_is_owner=False)


def test_a_hire_with_active_reports_cannot_be_retired():
    """review finding (high 4): retiring a manager must not orphan its
    reports or silently free the budget it carved out for them."""
    with pytest.raises(RetireHasActiveReportsError):
        assert_can_retire(hire_status=HireStatus.ACTIVE, hire_manager_agent_name="cmo-agent", actor_agent_name="cmo-agent", actor_is_owner=False, has_active_reports=True)


def test_even_the_owner_cannot_retire_a_hire_with_active_reports():
    with pytest.raises(RetireHasActiveReportsError):
        assert_can_retire(hire_status=HireStatus.ACTIVE, hire_manager_agent_name="cmo-agent", actor_agent_name="owner-agent", actor_is_owner=True, has_active_reports=True)
