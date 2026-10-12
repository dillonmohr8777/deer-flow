"""State machine for a Momo Board thread's reply lifecycle (Workspace Phase 4
item b4): ``new``/``triaged`` -> ``drafted`` -> ``approved`` -> ``replied``.

Pure decision logic, no I/O: callers (the ``/api/board`` router) resolve the
thread's current status and the actor's owner/admin standing, then call one
of the ``assert_can_*`` functions before writing. ``approved`` and
``replied`` both require an org owner/admin actor -- mirroring
``board.py``'s existing ``_is_active_org_admin`` check -- so that only the
owner can move a drafted reply forward; a non-owner (even one with client
access) is rejected regardless of the thread's status.
"""

from __future__ import annotations

from deerflow.persistence.board.model import BoardThreadStatus

_DRAFT_FROM: frozenset[str] = frozenset({BoardThreadStatus.NEW, BoardThreadStatus.TRIAGED})
_APPROVE_FROM: frozenset[str] = frozenset({BoardThreadStatus.DRAFTED})
_REPLY_FROM: frozenset[str] = frozenset({BoardThreadStatus.APPROVED})


class BoardTransitionError(Exception):
    """A requested status transition is not allowed from the thread's current status."""


class BoardOwnerRequiredError(BoardTransitionError):
    """A transition that requires an org owner/admin actor was attempted by someone else."""


def assert_can_draft(current_status: str, *, actor_is_owner: bool) -> None:
    """Momo drafts from ``new`` or ``triaged`` only, and only for an org owner/admin actor.

    There is no separate internal "Momo" service caller yet -- drafting rides
    the same HTTP endpoint any org member could otherwise reach, so it is
    gated the same way ``approve``/``reply`` are until one exists.
    """
    if not actor_is_owner:
        raise BoardOwnerRequiredError("Only an organization owner/admin may draft a reply")
    if current_status not in _DRAFT_FROM:
        raise BoardTransitionError(f"Cannot draft a reply from status {current_status!r}")


def assert_can_approve(current_status: str, *, actor_is_owner: bool) -> None:
    """Only an org owner/admin may approve a drafted reply, and only from ``drafted``."""
    if not actor_is_owner:
        raise BoardOwnerRequiredError("Only an organization owner/admin may approve a drafted reply")
    if current_status not in _APPROVE_FROM:
        raise BoardTransitionError(f"Cannot approve from status {current_status!r}")


def assert_can_reply(current_status: str, *, actor_is_owner: bool) -> None:
    """Sending the reply is a second, explicit owner action, and only from ``approved``."""
    if not actor_is_owner:
        raise BoardOwnerRequiredError("Only an organization owner/admin may send a reply")
    if current_status not in _REPLY_FROM:
        raise BoardTransitionError(f"Cannot send a reply from status {current_status!r}")


def latest_momo_draft_body(messages: list[dict]) -> str | None:
    """The body of the most recent ``momo``-authored message in *messages*, or ``None``.

    Shared by ``board.py``'s own reply-verbatim check and ``ceo_desk.py``'s
    needs-my-yes queue, which both need "what did Momo actually draft" from
    an already-fetched message list.
    """
    for message in reversed(messages):
        if message["author_kind"] == "momo":
            return message.get("body")
    return None
