"""Domain logic for Momentum agent seats (queue item e9), sibling to
``deerflow.persistence.exec_seats`` -- the same split as ``deerflow.board``
next to ``deerflow.persistence.board``.
"""

from deerflow.exec_seats.budget import evaluate_all_seat_budgets, evaluate_seat_budget, is_over_budget
from deerflow.exec_seats.scorecard import evaluate_all_seat_scorecards, evaluate_seat_scorecard, generate_scorecard_body
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
    "evaluate_all_seat_budgets",
    "evaluate_all_seat_scorecards",
    "evaluate_seat_budget",
    "evaluate_seat_scorecard",
    "generate_scorecard_body",
    "is_over_budget",
]
