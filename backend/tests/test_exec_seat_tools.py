"""Tests for the fleet-agent ``exec`` tool group (queue item e9, exec-seats).

Covers the #exec-wiring slice named in QUEUE.md's e9 next step: claim,
ratify (by the CEO holder, and by the owner when no CEO has been ratified
yet), owner veto (reopen), organization isolation, the Momentum-staff gate,
and the ``exec`` tool-group opt-in on ``get_available_tools``. Persistence
and pure workflow logic are covered by ``test_agent_seats.py``; this file is
the tool layer that resolves actor identity and calls that workflow.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, acting_as, org_world  # noqa: F401

from deerflow.persistence.exec_seats import AgentSeatStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context
from deerflow.tools.exec_seat_tools import CEO_SEAT, _exec_claim_seat_impl, _exec_ratify_seat_impl, _exec_reopen_seat_impl
from deerflow.tools.tools import get_available_tools


@contextmanager
def _acting_with_no_organization(actor: str):
    """Internal / auth-disabled / IM-channel shape: a real actor, no org at all.

    Mirrors ``test_team_board_tools.py``'s helper of the same name (f72).
    """
    token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor, organization_id=None, storage_user_id=actor, role=None))
    try:
        yield
    finally:
        reset_storage_context(token)


CMO_SEAT = "CMO"
USER_D = "user-d"


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id* for this test only.

    Mirrors ``test_board_router.py``'s helper of the same name.
    """
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


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
    """Bootstrap case: nobody holds the ratified CEO seat yet, so the owner ratifies.

    Ratified by a genuinely different human (USER_A, the owner) than whoever
    claimed it (USER_C, an admin) -- f84 (review follow-up): a same-user
    ratify is refused regardless of which agent name the run declares, so a
    real bootstrap needs a distinct *actor*, not just a distinct agent name.
    """
    with acting_as(USER_C, ORG_S):
        seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))

    # USER_A is ORG_S's owner (org_isolation_fixtures.MEMBERSHIPS).
    with acting_as(USER_A, ORG_S):
        ratified = await _exec_ratify_seat_impl(seat["id"], runtime=_runtime("owner-agent"))
    assert ratified["status"] == AgentSeatStatus.RATIFIED
    assert ratified["ratified_by_user_id"] == USER_A


@pytest.mark.asyncio
async def test_ceo_holder_ratifies_a_non_ceo_claim(org_world):  # noqa: F811
    with acting_as(USER_C, ORG_S):
        ceo_seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))
    with acting_as(USER_A, ORG_S):
        # Bootstrap ratification by a genuinely different actor than the claimant
        # (f84 review follow-up: same-user ratify is refused, whatever name it declares).
        await _exec_ratify_seat_impl(ceo_seat["id"], runtime=_runtime("owner-agent"))

        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
    with acting_as(USER_C, ORG_S):
        # The acting agent is not an org owner/admin, but it is the ratified CEO
        # holder -- and a different actor than whoever claimed cmo_seat (USER_A).
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("ceo-agent"))
    assert ratified["status"] == AgentSeatStatus.RATIFIED
    assert ratified["ratified_by_user_id"] == USER_C


@pytest.mark.asyncio
async def test_a_claimant_cannot_ratify_its_own_claim(org_world):  # noqa: F811
    """f84 (a): the same agent that claimed a seat cannot also ratify it,
    even though the run it's in belongs to the organization's owner -- the
    owner/admin standing on `actor_is_owner` must never stand in for a real,
    independent confirmation."""
    with acting_as(USER_A, ORG_S):
        seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))

        rejected = await _exec_ratify_seat_impl(seat["id"], runtime=_runtime("ceo-agent"))
        assert "error" in rejected

        from deerflow.persistence.exec_seats import AgentSeatRepository

        still = await AgentSeatRepository(org_world).get_seat(seat["id"])
    assert still["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_ceo_holder_cannot_ratify_its_own_second_claim(org_world):  # noqa: F811
    """f84 (b): once ``ceo-agent`` is the ratified CEO holder, `actor_is_ceo`
    grants it authority to ratify *other* agents' claims -- but not a second
    claim it made itself under its own agent name. Runs as a real ORG_S
    non-admin member (not an outsider), so the rejection is the self-ratify
    guard, not the plain staff-gate/org-admin check."""
    with acting_as(USER_C, ORG_S):
        ceo_seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))
    with acting_as(USER_A, ORG_S):
        await _exec_ratify_seat_impl(ceo_seat["id"], runtime=_runtime("owner-agent"))

        await _add_plain_member(org_world, USER_D, ORG_S)

    with acting_as(USER_D, ORG_S):
        second_claim = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("ceo-agent"))
        assert "error" not in second_claim

        rejected = await _exec_ratify_seat_impl(second_claim["id"], runtime=_runtime("ceo-agent"))
        assert "error" in rejected

        from deerflow.persistence.exec_seats import AgentSeatRepository

        still = await AgentSeatRepository(org_world).get_seat(second_claim["id"])
    assert still["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_ceo_holder_cannot_ratify_its_own_claim_under_a_different_name(org_world):  # noqa: F811
    """f84 review follow-up (high): the exact-name guard alone is bypassable --
    ``agent_name`` is a client-choosable context field, so the same person who
    claimed a seat as ``cmo-agent`` could rename their ratify run ``ceo-agent``
    and slip through the CEO-holder authority path unchanged. Reproduces the
    reviewer's exact repro: a real ORG_S non-admin member (USER_D) claims as
    ``cmo-agent``, then ratifies the very same claim as ``ceo-agent``."""
    with acting_as(USER_C, ORG_S):
        ceo_seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))
    with acting_as(USER_A, ORG_S):
        await _exec_ratify_seat_impl(ceo_seat["id"], runtime=_runtime("owner-agent"))

        await _add_plain_member(org_world, USER_D, ORG_S)

    with acting_as(USER_D, ORG_S):
        claimed = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        assert "error" not in claimed

        rejected = await _exec_ratify_seat_impl(claimed["id"], runtime=_runtime("ceo-agent"))
        assert "error" in rejected

        from deerflow.persistence.exec_seats import AgentSeatRepository

        still = await AgentSeatRepository(org_world).get_seat(claimed["id"])
    assert still["status"] == AgentSeatStatus.CLAIMED


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
    with acting_as(USER_C, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
    with acting_as(USER_A, ORG_S):
        # Ratified by a genuinely different actor than the claimant (f84 review
        # follow-up: same-user ratify is refused, whatever name it declares).
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
        assert ratified["status"] == AgentSeatStatus.RATIFIED

        reopened = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
    assert reopened["status"] == AgentSeatStatus.REOPENED

    # The seat can be claimed again after the veto.
    with acting_as(USER_A, ORG_S):
        reclaimed = await _exec_claim_seat_impl(CMO_SEAT, "content v2", "leads", 0, runtime=_runtime("new-cmo-agent"))
    assert "error" not in reclaimed


@pytest.mark.asyncio
async def test_non_owner_veto_is_rejected(org_world):  # noqa: F811
    with acting_as(USER_C, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
    with acting_as(USER_A, ORG_S):
        # Ratified by a genuinely different actor than the claimant (f84 review
        # follow-up: same-user ratify is refused, whatever name it declares).
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
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

    with acting_as(USER_C, ORG_S):
        # Ratified by a genuinely different actor than the claimant (f84 review
        # follow-up: same-user ratify is refused, whatever name it declares).
        await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
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


@pytest.mark.asyncio
async def test_null_organization_fails_closed_and_creates_no_rows(org_world):  # noqa: F811
    """f92: ``AgentSeatRepository._scope`` applies no filter when
    ``resolve_organization_id()`` is ``None`` (internal/auth-disabled/IM-channel
    runs), so every ``exec_*`` tool must fail closed itself -- team tools
    already do this for the same shape (f72)."""
    with acting_as(USER_A, ORG_S):
        seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
        assert "error" not in seat

    with _acting_with_no_organization(USER_B):
        claim_result = await _exec_claim_seat_impl("Rogue Seat", "scope", "kpi", 0, runtime=_runtime("rogue-agent"))
        ratify_result = await _exec_ratify_seat_impl(seat["id"], runtime=_runtime("rogue-agent"))
        reopen_result = await _exec_reopen_seat_impl(seat["id"], runtime=_runtime("rogue-agent"))
    assert set(claim_result) == {"error"}
    assert set(ratify_result) == {"error"}
    assert set(reopen_result) == {"error"}

    with acting_as(USER_A, ORG_S):
        from deerflow.persistence.exec_seats import AgentSeatRepository

        repo = AgentSeatRepository(org_world)
        seats = await repo.list_seats()
        unchanged = await repo.get_seat(seat["id"])
    assert [s["id"] for s in seats] == [seat["id"]]
    assert unchanged["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_null_organization_ratify_guard_blocks_cross_org_ceo_impersonation(org_world):  # noqa: F811
    """Review follow-up (medium) on f92: the generic null-org test above uses
    an agent name ("rogue-agent") that never matches a real seat, so deleting
    the ratify guard alone left every test green -- the rejection came from
    the ordinary CEO/owner check, not the guard. This reproduces the actual
    exploit the guard closes: ``AgentSeatRepository.get_seat``/``ratified_holder``
    apply no organization filter when ``resolve_organization_id()`` is
    ``None``, so a no-org run declaring the real ratified CEO's own
    ``agent_name`` would satisfy ``_actor_is_ceo`` and ratify ORG_S's own seat
    from entirely outside ORG_S, if this guard were ever removed."""
    with acting_as(USER_C, ORG_S):
        ceo_seat = await _exec_claim_seat_impl(CEO_SEAT, "weekly plan", "objectives hit", 0, runtime=_runtime("ceo-agent"))
    with acting_as(USER_A, ORG_S):
        await _exec_ratify_seat_impl(ceo_seat["id"], runtime=_runtime("owner-agent"))
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))

    with _acting_with_no_organization(USER_B):
        rejected = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("ceo-agent"))
    assert set(rejected) == {"error"}

    with acting_as(USER_A, ORG_S):
        from deerflow.persistence.exec_seats import AgentSeatRepository

        unchanged = await AgentSeatRepository(org_world).get_seat(cmo_seat["id"])
    assert unchanged["status"] == AgentSeatStatus.CLAIMED


@pytest.mark.asyncio
async def test_null_organization_reopen_guard_holds_even_if_admin_check_were_forced_true(org_world, monkeypatch):  # noqa: F811
    """Review follow-up (medium) on f92: ``_is_active_org_admin`` already
    returns ``False`` when there's no organization, so in practice the reopen
    guard is unreachable and its removal wouldn't fail any test. Forces
    ``actor_is_owner`` true (as the review asked) to isolate the guard's own
    contribution: even if the owner check ever changed to allow a null org,
    reopen must still refuse outside an organization."""
    with acting_as(USER_C, ORG_S):
        cmo_seat = await _exec_claim_seat_impl(CMO_SEAT, "content", "leads", 0, runtime=_runtime("cmo-agent"))
    with acting_as(USER_A, ORG_S):
        ratified = await _exec_ratify_seat_impl(cmo_seat["id"], runtime=_runtime("owner-agent"))
        assert ratified["status"] == AgentSeatStatus.RATIFIED

    import deerflow.tools.exec_seat_tools as exec_seat_tools

    async def _always_admin(_user_id: str) -> bool:
        return True

    monkeypatch.setattr(exec_seat_tools, "_is_active_org_admin", _always_admin)

    with _acting_with_no_organization(USER_B):
        rejected = await _exec_reopen_seat_impl(cmo_seat["id"], runtime=_runtime("intruder"))
    assert set(rejected) == {"error"}

    with acting_as(USER_A, ORG_S):
        from deerflow.persistence.exec_seats import AgentSeatRepository

        unchanged = await AgentSeatRepository(org_world).get_seat(cmo_seat["id"])
    assert unchanged["status"] == AgentSeatStatus.RATIFIED


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
