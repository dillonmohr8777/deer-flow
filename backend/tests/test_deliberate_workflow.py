"""Pure unit tests for ``deerflow.deliberate`` (queue item e13 authorization/budget checks)."""

from __future__ import annotations

import pytest

from deerflow.deliberate import DeliberateAuthorizationError, DeliberateBudgetError, assert_call_budget, assert_can_deliberate


def test_non_staff_is_refused():
    with pytest.raises(DeliberateAuthorizationError):
        assert_can_deliberate(is_momentum_staff=False, thread_has_client_data=False, owner_override=False)


def test_staff_with_no_client_data_is_allowed():
    assert_can_deliberate(is_momentum_staff=True, thread_has_client_data=False, owner_override=False)


def test_client_data_without_override_is_refused():
    with pytest.raises(DeliberateAuthorizationError):
        assert_can_deliberate(is_momentum_staff=True, thread_has_client_data=True, owner_override=False)


def test_client_data_with_owner_override_is_allowed():
    assert_can_deliberate(is_momentum_staff=True, thread_has_client_data=True, owner_override=True)


def test_paused_seat_is_refused_even_under_the_call_cap():
    with pytest.raises(DeliberateBudgetError):
        assert_call_budget(calls_this_turn=0, max_calls_per_turn=1, seat_paused=True)


def test_first_call_this_turn_is_allowed():
    assert_call_budget(calls_this_turn=0, max_calls_per_turn=1, seat_paused=False)


def test_second_call_this_turn_is_refused():
    with pytest.raises(DeliberateBudgetError):
        assert_call_budget(calls_this_turn=1, max_calls_per_turn=1, seat_paused=False)


def test_a_higher_configured_cap_allows_more_calls():
    assert_call_budget(calls_this_turn=1, max_calls_per_turn=2, seat_paused=False)
