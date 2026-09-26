"""Pure state-machine tests for the Momo Board reply lifecycle (b4).

``deerflow.board.workflow`` has no I/O -- these tests exercise the
``assert_can_*`` functions directly, independent of the router and
repository, mirroring ``test_board_triage.py``'s "unit test the pure
function" shape for the sibling ``triage.py`` module.
"""

from __future__ import annotations

import pytest

from deerflow.board.workflow import (
    BoardOwnerRequiredError,
    BoardTransitionError,
    assert_can_approve,
    assert_can_draft,
    assert_can_reply,
)
from deerflow.persistence.board.model import BoardThreadStatus

# --- draft: new/triaged -> drafted, owner only ---


@pytest.mark.parametrize("status", [BoardThreadStatus.NEW, BoardThreadStatus.TRIAGED])
def test_owner_can_draft_from_new_or_triaged(status):
    assert_can_draft(status, actor_is_owner=True)  # must not raise


def test_non_owner_draft_is_rejected_even_from_new():
    with pytest.raises(BoardOwnerRequiredError):
        assert_can_draft(BoardThreadStatus.NEW, actor_is_owner=False)


@pytest.mark.parametrize(
    "status",
    [BoardThreadStatus.DRAFTED, BoardThreadStatus.APPROVED, BoardThreadStatus.REPLIED, BoardThreadStatus.CLOSED],
)
def test_owner_cannot_draft_outside_new_or_triaged(status):
    with pytest.raises(BoardTransitionError):
        assert_can_draft(status, actor_is_owner=True)


# --- approve: drafted -> approved, owner only ---


def test_owner_can_approve_drafted():
    assert_can_approve(BoardThreadStatus.DRAFTED, actor_is_owner=True)  # must not raise


def test_non_owner_approval_is_rejected_even_from_drafted():
    with pytest.raises(BoardOwnerRequiredError):
        assert_can_approve(BoardThreadStatus.DRAFTED, actor_is_owner=False)


@pytest.mark.parametrize(
    "status",
    [BoardThreadStatus.NEW, BoardThreadStatus.TRIAGED, BoardThreadStatus.APPROVED, BoardThreadStatus.REPLIED, BoardThreadStatus.CLOSED],
)
def test_owner_cannot_approve_outside_drafted(status):
    with pytest.raises(BoardTransitionError):
        assert_can_approve(status, actor_is_owner=True)


def test_owner_check_wins_over_status_check_when_both_fail():
    # A non-owner is rejected for lacking authority even when the status is
    # also wrong -- ownership is checked first, so the error names the real
    # blocker rather than a status message that would mislead a retry.
    with pytest.raises(BoardOwnerRequiredError):
        assert_can_approve(BoardThreadStatus.NEW, actor_is_owner=False)


# --- reply: approved -> replied, owner only, a separate action from approve ---


def test_owner_can_reply_from_approved():
    assert_can_reply(BoardThreadStatus.APPROVED, actor_is_owner=True)  # must not raise


def test_non_owner_reply_is_rejected_even_from_approved():
    with pytest.raises(BoardOwnerRequiredError):
        assert_can_reply(BoardThreadStatus.APPROVED, actor_is_owner=False)


def test_owner_cannot_reply_directly_from_drafted():
    # Approval is not implicit: reaching ``replied`` requires having passed
    # through ``approved`` first, a distinct owner action from ``reply``.
    with pytest.raises(BoardTransitionError):
        assert_can_reply(BoardThreadStatus.DRAFTED, actor_is_owner=True)


@pytest.mark.parametrize(
    "status",
    [BoardThreadStatus.NEW, BoardThreadStatus.TRIAGED, BoardThreadStatus.DRAFTED, BoardThreadStatus.REPLIED, BoardThreadStatus.CLOSED],
)
def test_owner_cannot_reply_outside_approved(status):
    with pytest.raises(BoardTransitionError):
        assert_can_reply(status, actor_is_owner=True)
