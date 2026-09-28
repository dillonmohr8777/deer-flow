"""Tests for the fleet-agent ``team`` tool group (queue item e8, fleet-board).

Covers: organization isolation (a channel in another organization is
indistinguishable from a missing one), the ``team`` tool-group gate on
``get_available_tools``, the 2,000-character post cap, and a fleet-builder ->
independent-verifier handoff round trip through the same Team Board tables
the human ``/api/team`` routes use (see ``test_team_board_router.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, acting_as, org_world  # noqa: F401

from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.team_board_tools import _MAX_BODY_CHARS, _team_post_message_impl, _team_read_messages_impl
from deerflow.tools.tools import get_available_tools


class _DummyRuntime(SimpleNamespace):
    context: dict


def _runtime(agent_name: str | None) -> _DummyRuntime:
    """A minimal stand-in for ``ToolRuntime`` — only ``.context`` is read."""
    return _DummyRuntime(context={"agent_name": agent_name} if agent_name is not None else {})


async def _create_fleet_channel(org_world) -> None:  # noqa: F811
    """The one-time setup step: an owner creates #fleet in Momentum's own org."""
    repo = TeamBoardRepository(org_world)
    with acting_as(USER_A, ORG_S):
        created = await repo.create_channel(slug="fleet", name="Fleet", topic="Fleet agents talk shop here")
    assert created is not None


@pytest.mark.asyncio
async def test_org_isolation_channel_from_another_org_is_invisible(org_world):  # noqa: F811
    await _create_fleet_channel(org_world)

    with acting_as(USER_A, ORG_S):
        posted = await _team_post_message_impl("fleet", "hello from momentum", runtime=_runtime("fleet-builder"))
    assert "error" not in posted

    # USER_B's own private organization has no #fleet channel: read and post
    # both fail exactly like a channel that never existed anywhere.
    with acting_as(USER_B):
        foreign_read = await _team_read_messages_impl("fleet")
        foreign_post = await _team_post_message_impl("fleet", "leaking in from another org", runtime=_runtime("intruder"))
        truly_missing = await _team_read_messages_impl("no-such-channel")
    assert "error" in foreign_read
    assert "error" in foreign_post
    assert "error" in truly_missing
    # Same failure shape for "wrong org" and "never existed" — no oracle.
    assert set(foreign_read) == set(truly_missing) == {"error"}

    # Momentum's own channel is unaffected by the foreign org's attempt.
    with acting_as(USER_A, ORG_S):
        after = await _team_read_messages_impl("fleet")
    assert [m["body"] for m in after["messages"]] == ["[fleet-builder] hello from momentum"]


@pytest.mark.asyncio
async def test_read_and_post_fail_closed_before_the_channel_exists(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        read_result = await _team_read_messages_impl("fleet")
        post_result = await _team_post_message_impl("fleet", "too early", runtime=_runtime("fleet-builder"))
    assert "error" in read_result
    assert "error" in post_result


@pytest.mark.asyncio
async def test_leading_hash_and_case_are_normalized(org_world):  # noqa: F811
    await _create_fleet_channel(org_world)
    with acting_as(USER_A, ORG_S):
        posted = await _team_post_message_impl("#FLEET", "shouted channel name", runtime=_runtime("fleet-builder"))
        assert posted["channel"] == "fleet"
        read_result = await _team_read_messages_impl(" #Fleet ")
    assert read_result["channel"] == "fleet"
    assert len(read_result["messages"]) == 1


@pytest.mark.asyncio
async def test_post_message_length_cap(org_world):  # noqa: F811
    await _create_fleet_channel(org_world)
    with acting_as(USER_A, ORG_S):
        at_cap = await _team_post_message_impl("fleet", "x" * _MAX_BODY_CHARS, runtime=_runtime("fleet-builder"))
        assert "error" not in at_cap

        over_cap = await _team_post_message_impl("fleet", "x" * (_MAX_BODY_CHARS + 1), runtime=_runtime("fleet-builder"))
        assert "error" in over_cap
        assert str(_MAX_BODY_CHARS) in over_cap["error"]

        empty = await _team_post_message_impl("fleet", "   ", runtime=_runtime("fleet-builder"))
        assert "error" in empty

        # The rejected post never reached the channel; only the valid one did.
        after = await _team_read_messages_impl("fleet")
    assert len(after["messages"]) == 1
    assert after["messages"][0]["body"] == f"[fleet-builder] {'x' * _MAX_BODY_CHARS}"


@pytest.mark.asyncio
async def test_fleet_builder_handoff_round_trip_via_independent_verifier(org_world):  # noqa: F811
    await _create_fleet_channel(org_world)

    with acting_as(USER_A, ORG_S):
        posted = await _team_post_message_impl(
            "fleet",
            "Handoff: e8 fleet-board tools ready for review.",
            runtime=_runtime("fleet-builder"),
        )
        assert "error" not in posted

        # independent-verifier reads the same channel back; the read tool
        # takes no agent identity because reads aren't signed.
        verifier_view = await _team_read_messages_impl("fleet")

    assert verifier_view["channel"] == "fleet"
    [message] = verifier_view["messages"]
    assert message["body"] == "[fleet-builder] Handoff: e8 fleet-board tools ready for review."
    # Both fleet agents post/read as the same Momentum storage principal;
    # the "[agent-name]" prefix is what tells readers who actually wrote it.
    assert message["author"] == posted["author"]


def _tool_group_config():
    tools = [
        SimpleNamespace(name="read_file", group="file:read", use="deerflow.sandbox.tools:read_file_tool"),
        SimpleNamespace(name="team_read_messages", group="team", use="deerflow.tools.team_board_tools:team_read_messages"),
        SimpleNamespace(name="team_post_message", group="team", use="deerflow.tools.team_board_tools:team_post_message"),
    ]
    return SimpleNamespace(
        tools=tools,
        models=[],
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", allow_host_bash=False),
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )


def test_agent_without_team_group_does_not_get_the_team_tools():
    config = _tool_group_config()
    names = {t.name for t in get_available_tools(groups=["file:read"], include_mcp=False, subagent_enabled=False, app_config=config)}
    assert "read_file" in names
    assert "team_read_messages" not in names
    assert "team_post_message" not in names


def test_agent_with_team_group_gets_the_team_tools():
    config = _tool_group_config()
    names = {t.name for t in get_available_tools(groups=["file:read", "team"], include_mcp=False, subagent_enabled=False, app_config=config)}
    assert "team_read_messages" in names
    assert "team_post_message" in names
