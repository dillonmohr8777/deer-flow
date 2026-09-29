"""Tests for the fleet-agent ``exec`` tool group (queue item e9, exec-seats).

Covers the #exec-wiring slice named in QUEUE.md's e9 next step: claim,
ratify (by the CEO holder, and by the owner when no CEO has been ratified
yet), owner veto (reopen), organization isolation, the Momentum-staff gate,
and the ``exec`` tool-group opt-in on ``get_available_tools``. Persistence
and pure workflow logic are covered by ``test_agent_seats.py``; this file is
the tool layer that resolves actor identity and calls that workflow.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, acting_as, org_world  # noqa: F401

from deerflow.persistence.exec_seats import AgentSeatStatus
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.exec_seat_tools import CEO_SEAT, _exec_claim_seat_impl, _exec_ratify_seat_impl, _exec_reopen_seat_impl
from deerflow.tools.tools import get_available_tools

CMO_SEAT = "CMO"


class _DummyRuntime(SimpleNamespace):
    context: dict


def _runtime(agent_name: str | None, *, momentum_staff: bool = True) -> _DummyRuntime:
    context: dict = {"momentum_staff": momentum_staff}
    if agent_name is not None:
        context["agent_name"] = agent_name
    return _DummyRuntime(context=context)


@pytest.mark.asyncio
async def test_tools_refuse_without_the_momentum_staff_flag(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        claimed = await _exec_claim_seat_impl(CMO_SEAT, "content", "qualified leads", 1000, runtime=_runtime("cmo-agent", momentum_staff=False))
    assert claimed == {"error": "Agent seat tools are restricted to Momentum staff."}


@pytest.mark.asyncio
async def test_claim_creates_a_claimed_seat_and_announces_it(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(org_world)
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)

        claimed = await _exec_claim_seat_impl(CMO_SEAT, "content, SEO/AEO", "qualified leads", 1000, runtime=_runtime("cmo-agent"))
        assert claimed["status"] == AgentSeatStatus.CLAIMED
        assert claimed["seat"] == CMO_SEAT
        assert claimed["agent_name"] == "cmo-agent"

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert any("[cmo-agent] claimed CMO" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_claim_on_an_already_claimed_seat_is_rejected(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        first = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        assert "error" not in first

        second = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("rival-agent"))
    assert "error" in second


@pytest.mark.asyncio
async def test_owner_ratifies_the_first_ceo_claim(org_world):  # noqa: F811
    """Bootstrap case: nobody holds the ratified CEO seat yet, so the owner ratifies."""
    with acting_as(USER_A, ORG_S):
        seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))

        # USER_A is ORG_S's owner (org_isolation_fixtures.MEMBERSHIPS).
        ratified = await _exec_ratify_seat_impl(seat["id"], runtime=_runtime("ceo-agent"))
    assert ratified["status"] == AgentSeatStatus.RATIFIED
    assert ratified["ratified_by_user_id"] == USER_A


@pytest.mark.asyncio
async def test_ceo_holder_ratifies_a_non_ceo_claim(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        ceo_seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))
        await _exec_ratify_seat_impl(ceo_seat["id"], runtime=_runtime("ceo-agent"))

        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        # The acting agent is not an org owner/admin, but it is the ratified CEO holder.
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("ceo-agent"))
    assert ratified["status"] == AgentSeatStatus.RATIFIED
    assert ratified["ratified_by_user_id"] == USER_A  # storage attribution, not the seat holder's identity


@pytest.mark.asyncio
async def test_ratify_by_neither_ceo_nor_owner_is_rejected(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))

    # USER_B is an outsider with no membership in ORG_S at all.
    with acting_as(USER_B):
        rejected = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("intruder-agent"))
    assert "error" in rejected

    # The rejected attempt never wrote anything: still claimed.
    with acting_as(USER_A, ORG_S):
        from deerflow.persistence.exec_seats import AgentSeatRepository

        still = await AgentSeatRepository(org_world).get_seat(cmo_seat["id"])
    assert still["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_owner_veto_reopens_a_ratified_seat_regardless_of_holder(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("cmo-agent"))
        assert ratified["status"] == AgentSeatStatus.RATIFIED

        reopened = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
    assert reopened["status"] == AgentSeatStatus.REOPENED

    # The seat can be claimed again after the veto.
    with acting_as(USER_A, ORG_S):
        reclaimed = await _exec_claim_seat_impl(CMO_SEAT, "content v2", "leads", 0, runtime=_runtime("new-cmo-agent"))
    assert "error" not in reclaimed


@pytest.mark.asyncio
async def test_non_owner_veto_is_rejected(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("cmo-agent"))
        assert ratified["status"] == AgentSeatStatus.RATIFIED

    # USER_B has no membership in ORG_S at all -- reopen is owner/admin-only
    # (EXECUTIVE.md rule 4), mirroring `_is_active_org_admin`'s owner-or-admin
    # convention in `app/gateway/routers/board.py`.
    with acting_as(USER_B):
        rejected = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("intruder-agent"))
    assert "error" in rejected

    with acting_as(USER_A, ORG_S):
        from deerflow.persistence.exec_seats import AgentSeatRepository

        unchanged = await AgentSeatRepository(org_world).get_seat(cmo_seat["id"])
    assert unchanged["status"] == AgentSeatStatus.RATIFIED


@pytest.mark.asyncio
async def test_active_org_admin_may_also_veto(org_world):  # noqa: F811
    """USER_C is an active ORG_S admin, not the owner. `_is_active_org_admin`'s
    owner-or-admin convention (mirrored from `board.py`/`clients.py`) allows it,
    same as an org admin can approve/reply on the Momo Board."""
    with acting_as(USER_A, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("cmo-agent"))

    with acting_as(USER_C, ORG_S):
        reopened = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("admin-agent"))
    assert reopened["status"] == AgentSeatStatus.REOPENED


@pytest.mark.asyncio
async def test_org_isolation_a_seat_in_one_org_is_invisible_from_another(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))

    with acting_as(USER_B):
        foreign_ratify = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("intruder"))
        foreign_reopen = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("intruder"))
    assert "error" in foreign_ratify
    assert "error" in foreign_reopen


def _tool_group_config():
    tools = [
        SimpleNamespace(name="read_file", group="file:read", use="deerflow.sandbox.tools:read_file_tool"),
        SimpleNamespace(name="exec_claim_seat", group="exec", use="deerflow.tools.exec_seat_tools:exec_claim_seat"),
        SimpleNamespace(name="exec_ratify_seat", group="exec", use="deerflow.tools.exec_seat_tools:exec_ratify_seat"),
        SimpleNamespace(name="exec_reopen_seat", group="exec", use="deerflow.tools.exec_seat_tools:exec_reopen_seat"),
    ]
    return SimpleNamespace(
        tools=tools,
        models=[],
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", allow_host_bash=False),
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )


def test_default_agent_does_not_get_the_exec_tools():
    """``groups=None`` (no agent config) must not mean "every configured group"
    for ``exec``, the same as f71 established for ``team``."""
    config = _tool_group_config()
    names = {t.name for t in get_available_tools(groups=None, include_mcp=False, subagent_enabled=False, app_config=config)}
    assert "read_file" in names
    assert not any(name.startswith("exec_") for name in names)


def test_an_agent_that_lists_exec_gets_the_exec_tools():
    config = _tool_group_config()
    names = {t.name for t in get_available_tools(groups=["file:read", "exec"], include_mcp=False, subagent_enabled=False, app_config=config)}
    assert {"exec_claim_seat", "exec_ratify_seat", "exec_reopen_seat"} <= names
