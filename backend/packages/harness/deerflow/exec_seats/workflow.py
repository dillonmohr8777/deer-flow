"""State machine for a Momentum agent seat's claim/ratify/reopen lifecycle
(queue item e9, exec-seats): ``claimed`` -> ``ratified`` -> ``reopened``, and
``reopened`` -> ``claimed`` again for the next holder.

Pure decision logic, no I/O -- callers (a future ``#exec``-channel handler)
resolve the seat's current status and the actor's standing before calling one
of the ``assert_can_*`` functions. Titles grant no authority by themselves
(``EXECUTIVE.md``): ratifying a claim requires the actor to already hold the
ratified CEO seat, or to be the organization owner (also true when no CEO has
been ratified yet -- the owner breaks that bootstrap deadlock); reopening a
seat -- EXECUTIVE.md's owner-only override, "reassigning any title" -- is
always the owner alone, mirroring ``deerflow.board.workflow``'s
``actor_is_owner``-gated ``assert_can_approve``/``assert_can_reply``.
"""

from __future__ import annotations

from deerflow.persistence.exec_seats.model import AgentSeatStatus

_CLAIM_FROM: frozenset[str | None] = frozenset({None, AgentSeatStatus.REOPENED})
_RATIFY_FROM: frozenset[str] = frozenset({AgentSeatStatus.CLAIMED})
_REOPEN_FROM: frozenset[str] = frozenset({AgentSeatStatus.CLAIMED, AgentSeatStatus.RATIFIED})


class SeatTransitionError(Exception):
    """A requested seat transition is not allowed from its current status."""


class SeatAuthorizationError(SeatTransitionError):
    """The actor is not allowed to perform this transition."""


def assert_can_claim(current_status: str | None) -> None:
    """A seat may be claimed when it has never been claimed, or has been reopened.

    ``current_status`` is the *seat title's* current ratified/claimed status
    (a fresh claim on an already-claimed-but-unratified title is a separate
    row EXECUTIVE.md's "Confirm" step resolves, not blocked here), or ``None``
    for a title nobody has ever claimed.
    """
    if current_status not in _CLAIM_FROM:
        raise SeatTransitionError(f"Cannot claim a seat with status {current_status!r}")


def assert_can_ratify(current_status: str, *, actor_is_ceo: bool, actor_is_owner: bool) -> None:
    """Only the ratified CEO seat's holder, or the organization owner, may confirm a claim."""
    if not (actor_is_ceo or actor_is_owner):
        raise SeatAuthorizationError("Only the CEO seat holder or the organization owner may ratify a claim")
    if current_status not in _RATIFY_FROM:
        raise SeatTransitionError(f"Cannot ratify from status {current_status!r}")


def assert_can_reopen(current_status: str, *, actor_is_owner: bool) -> None:
    """Reassigning or vetoing a title is an owner-only override (EXECUTIVE.md rule 4)."""
    if not actor_is_owner:
        raise SeatAuthorizationError("Only the organization owner may reopen a seat")
    if current_status not in _REOPEN_FROM:
        raise SeatTransitionError(f"Cannot reopen from status {current_status!r}")
