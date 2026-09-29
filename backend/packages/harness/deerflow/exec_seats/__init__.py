"""Domain logic for Momentum agent seats (queue item e9), sibling to
``deerflow.persistence.exec_seats`` -- the same split as ``deerflow.board``
next to ``deerflow.persistence.board``.
"""

from deerflow.exec_seats.workflow import (
    SeatAuthorizationError,
    SeatTransitionError,
    assert_can_claim,
    assert_can_ratify,
    assert_can_reopen,
)

__all__ = [
    "SeatAuthorizationError",
    "SeatTransitionError",
    "assert_can_claim",
    "assert_can_ratify",
    "assert_can_reopen",
]
