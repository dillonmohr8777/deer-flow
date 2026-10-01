"""Pure authorization and budget checks for the ``deliberate`` tool (queue item e13).

OpenRouter's Fusion panel sends the prompt to several third-party providers,
so ``deliberate`` is gated like ``team_board_tools``/``exec_seat_tools``
(Momentum staff only) plus two deliberation-specific rules: never on a
thread tagged with client data unless an organization owner overrides it,
and at most one call per conversational turn. Kept dependency-free (no DB,
no model client) so the rules themselves are covered without any I/O.
"""

from __future__ import annotations


class DeliberateAuthorizationError(Exception):
    """Raised when the caller may not run the deliberation panel at all."""


class DeliberateBudgetError(Exception):
    """Raised when a deliberation call would exceed a rate limit or budget."""


def assert_can_deliberate(*, is_momentum_staff: bool, thread_has_client_data: bool, owner_override: bool) -> None:
    """Raise :class:`DeliberateAuthorizationError` unless the call is allowed.

    ``owner_override`` must already be verified as coming from a real
    organization owner/admin (see ``deliberate_tools.py``'s ``_is_active_org_admin``
    check) -- this function trusts the flag, it does not derive it.
    """
    if not is_momentum_staff:
        raise DeliberateAuthorizationError("Deliberation is restricted to Momentum staff.")
    if thread_has_client_data and not owner_override:
        raise DeliberateAuthorizationError(
            "This thread carries client data. The deliberation panel sends the prompt to several outside providers, outside MomoBot's Luna-only private-data lane, so an organization owner must override to run it here."
        )


def assert_call_budget(*, calls_this_turn: int, max_calls_per_turn: int, seat_paused: bool) -> None:
    """Raise :class:`DeliberateBudgetError` unless another call is still allowed this turn."""
    if seat_paused:
        raise DeliberateBudgetError("This seat is over its weekly token budget; deliberation is paused until it resets.")
    if calls_this_turn >= max_calls_per_turn:
        raise DeliberateBudgetError(f"Deliberation is limited to {max_calls_per_turn} call(s) per turn.")
