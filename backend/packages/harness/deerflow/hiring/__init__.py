"""Domain logic for EXECUTIVE.md's Hiring section (queue item e12), sibling to
``deerflow.persistence.hiring`` -- the same split as ``deerflow.exec_seats``
next to ``deerflow.persistence.exec_seats``.
"""

from deerflow.hiring.workflow import (
    HireAuthorizationError,
    HireBudgetError,
    HireDepthCapError,
    HireError,
    HireHeadcountCapError,
    HirePrivateDataError,
    HireToolEscalationError,
    RetireAuthorizationError,
    RetireError,
    RetireTransitionError,
    assert_can_hire,
    assert_can_retire,
)

__all__ = [
    "HireAuthorizationError",
    "HireBudgetError",
    "HireDepthCapError",
    "HireError",
    "HireHeadcountCapError",
    "HirePrivateDataError",
    "HireToolEscalationError",
    "RetireAuthorizationError",
    "RetireError",
    "RetireTransitionError",
    "assert_can_hire",
    "assert_can_retire",
]
