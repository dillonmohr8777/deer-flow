"""Tests for the ``draft_board_thread`` fleet-agent tool (queue item e13, the
"Plan a big project" starter's payoff).

Covers the Momentum-staff-only gate, input validation, the org-scoped client
lookup (a client from another organization is indistinguishable from a
missing one, mirroring ``ClientRepository.get``), and that a successful call
lands the thread directly in ``drafted`` with a single ``momo``-authored
message -- the same shape ``POST /api/board/threads/{id}/draft`` produces,
so it appears in the owner's existing approvals queue unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, acting_as, org_world  # noqa: F401

from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository
from deerflow.tools.board_draft_tools import _draft_board_thread_impl


class _DummyRuntime(SimpleNamespace):
    context: dict


def _runtime(*, momentum_staff: bool = True) -> _DummyRuntime:
    return _DummyRuntime(context={"momentum_staff": momentum_staff})


# --- staff gate ---


@pytest.mark.asyncio
async def test_refuses_without_momentum_staff_flag(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("client-1", "Plan", "Body text", runtime=_runtime(momentum_staff=False))
    assert result == {"error": "Board draft tools are restricted to Momentum staff."}


@pytest.mark.asyncio
async def test_refuses_with_no_runtime(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("client-1", "Plan", "Body text", runtime=None)
    assert result == {"error": "Board draft tools are restricted to Momentum staff."}


# --- input validation ---


@pytest.mark.asyncio
async def test_requires_client_id(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("   ", "Plan", "Body text", runtime=_runtime())
    assert result == {"error": "client_id is required."}


@pytest.mark.asyncio
async def test_requires_body(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("client-1", "Plan", "   ", runtime=_runtime())
    assert result == {"error": "body is required."}


@pytest.mark.asyncio
async def test_subject_too_long_is_refused(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("client-1", "x" * 201, "Body", runtime=_runtime())
    assert result["error"].startswith("subject is too long")


@pytest.mark.asyncio
async def test_body_too_long_is_refused(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("client-1", "Plan", "x" * 20001, runtime=_runtime())
    assert result["error"].startswith("body is too long")


# --- client resolution ---


@pytest.mark.asyncio
async def test_unknown_client_is_refused(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _draft_board_thread_impl("no-such-client", "Plan", "Body", runtime=_runtime())
    assert result == {"error": "No such client in this organization."}


@pytest.mark.asyncio
async def test_client_from_another_organization_is_refused(org_world):  # noqa: F811
    session_factory = org_world
    client_repo = ClientRepository(session_factory)
    with acting_as(USER_A, ORG_S):
        client = await client_repo.create(display_name="Acme")
    with acting_as(USER_A, ORG_A):
        result = await _draft_board_thread_impl(client["id"], "Plan", "Body", runtime=_runtime())
    assert result == {"error": "No such client in this organization."}


# --- success path ---


@pytest.mark.asyncio
async def test_creates_a_drafted_thread_with_a_single_momo_message(org_world):  # noqa: F811
    session_factory = org_world
    client_repo = ClientRepository(session_factory)
    board_repo = BoardRepository(session_factory)
    with acting_as(USER_A, ORG_S):
        client = await client_repo.create(display_name="Acme")
        result = await _draft_board_thread_impl(client["id"], "Q4 rollout plan", "Here is the plan...", runtime=_runtime())

        assert result["status"] == "drafted"
        thread_id = result["thread_id"]

        thread = await board_repo.get_thread(thread_id)
        assert thread["client_id"] == client["id"]
        assert thread["kind"] == "post"
        assert thread["status"] == "drafted"

        messages = await board_repo.list_messages(thread_id)
        assert len(messages) == 1
        assert messages[0]["author_kind"] == "momo"
        assert messages[0]["author_user_id"] is None
        assert messages[0]["body"] == "Here is the plan..."
