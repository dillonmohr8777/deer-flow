"""Tests for the fleet-agent ``hire`` tool group (queue item e12, hiring).

Covers the tool layer that resolves a hiring manager's identity (a ratified
``agent_seats`` holder, or one of its own active hires) and calls
``deerflow.hiring.workflow``'s checks: end-to-end coverage for tool subset,
private-data lane, budget carve, headcount cap, and org depth, plus
retire-own-reports-only, organization isolation, the Momentum-staff gate, and
the ``hire`` tool-group opt-in on ``get_available_tools``. Pure workflow
logic is unit-tested directly in ``test_hiring_workflow.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_C, acting_as, org_world  # noqa: F401
from sqlalchemy import func, select

import deerflow.tools.hire_tools as hire_tools_module
from deerflow.config.agents_config import AgentConfig
from deerflow.persistence.hiring import HiredAgentRepository
from deerflow.persistence.hiring.model import HiredAgentRow
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.persistence.user.model import UserRow
from deerflow.tools.exec_seat_tools import _exec_claim_seat_impl, _exec_ratify_seat_impl
from deerflow.tools.hire_tools import _hire_report_impl, _retire_report_impl
from deerflow.tools.tools import get_available_tools

CEO_SEAT = "CEO (chief of staff)"
USER_D = "user-d"


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id* for this test only.

    Mirrors ``test_exec_seat_tools.py``'s helper of the same name.
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


_KNOWN_TOOL_GROUPS = ("file:read", "bash", "team", "exec", "hire")


def _hiring_config(**overrides):
    base = {"headcount_cap": 20, "max_org_depth": 3}
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_hiring_config(monkeypatch, **overrides) -> None:
    tools = [SimpleNamespace(group=g) for g in _KNOWN_TOOL_GROUPS]
    monkeypatch.setattr(hire_tools_module, "get_app_config", lambda: SimpleNamespace(hiring=_hiring_config(**overrides), tools=tools))


@pytest.fixture(autouse=True)
def _default_hiring_config(monkeypatch):
    """Every test gets the default caps unless it calls ``_patch_hiring_config`` itself.

    Avoids every other test needing a real ``config.yaml`` on disk just to
    read ``get_app_config().hiring``.
    """
    _patch_hiring_config(monkeypatch)
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: AgentConfig(name=name))


async def _ratify_ceo(owner_user_id: str, agent_name: str = "ceo-agent", *, model_family: str = "muse", weekly_token_budget: int = 0) -> dict:
    """Claim the CEO seat in ORG_S as *agent_name*, then ratify it as *owner_user_id*.

    Claim and ratify run under distinct actors (USER_C claims, *owner_user_id*
    ratifies) since f84 refuses a same-user self-ratify -- mirrors
    ``test_exec_seat_tools.py``'s ``test_owner_ratifies_the_first_ceo_claim``
    bootstrap pattern. Callers of this helper are already inside an
    ``acting_as`` block for *owner_user_id*; this switches actor for the
    claim step only, then restores it for the ratify.
    """
    with acting_as(USER_C, ORG_S):
        claimed = await _exec_claim_seat_impl(CEO_SEAT, "run the company", "objectives hit", weekly_token_budget, runtime=_runtime(agent_name), model_family=model_family)
    with acting_as(owner_user_id, ORG_S):
        return await _exec_ratify_seat_impl(claimed["id"], runtime=_runtime("owner-agent"))


async def _assert_hiring_ledger_empty(session_factory) -> None:
    """No row of any status or organization may be inserted on policy failure."""
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(HiredAgentRow)) == 0


@pytest.mark.asyncio
async def test_tools_refuse_without_the_momentum_staff_flag(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["file:read"], 0, "muse", False, runtime=_runtime("ceo-agent", momentum_staff=False))
    assert result == {"error": "Agent hiring tools are restricted to Momentum staff."}


@pytest.mark.asyncio
async def test_an_agent_with_no_title_and_no_active_hire_cannot_hire(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["file:read"], 0, "muse", False, runtime=_runtime("nobody-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_titled_employee_hires_a_report_and_announces_it(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(org_world)
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        await _ratify_ceo(USER_A)

        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["file:read"], 500, "muse", False, runtime=_runtime("ceo-agent"))
        assert hired["status"] == "active"
        assert hired["agent_name"] == "writer-1"
        assert hired["manager_agent_name"] == "ceo-agent"
        assert hired["depth"] == 2

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert any("[ceo-agent] hired writer-1 as Writer" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_hiring_the_same_agent_name_twice_is_rejected(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        first = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert "error" not in first
        second = await _hire_report_impl("writer-1", "Writer 2", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in second


# --- tool subset of the manager ---


@pytest.mark.asyncio
async def test_a_hire_cannot_escalate_tools_beyond_its_hiring_managers(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        manager_hire = await _hire_report_impl("cmo-report", "CMO report", "content strategy", "leads", ["file:read"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert manager_hire["status"] == "active"

        escalated = await _hire_report_impl("sub-report", "Sub report", "writing", "posts/week", ["file:read", "bash"], 0, "muse", False, runtime=_runtime("cmo-report"))
    assert "error" in escalated


@pytest.mark.asyncio
async def test_a_hire_may_hire_within_its_own_tools(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        await _hire_report_impl("cmo-report", "CMO report", "content strategy", "leads", ["file:read"], 0, "muse", False, runtime=_runtime("ceo-agent"))

        sub = await _hire_report_impl("sub-report", "Sub report", "writing", "posts/week", ["file:read"], 0, "muse", False, runtime=_runtime("cmo-report"))
    assert sub["status"] == "active"
    assert sub["depth"] == 3


@pytest.mark.asyncio
async def test_a_depth_one_manager_cannot_grant_an_unknown_tool_group(org_world):  # noqa: F811
    """review finding (medium 5): a depth-1 manager has no tracked tool
    ceiling, so with no other check a made-up group name would sail
    through. known_tool_groups (the org's real config.tools catalog)
    refuses it regardless."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["file:read", "made-up-group"], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_depth_one_manager_with_a_real_agent_config_cannot_exceed_its_own_tool_groups(org_world, monkeypatch):  # noqa: F811
    """review finding (medium 5, follow-up): known_tool_groups alone still let a
    seat holder whose own agent config really does restrict its tools (e.g. to
    ["file:read"]) hire a report with any other known group (e.g. "bash").
    When a real AgentConfig is found for the seat's agent_name, its own
    tool_groups becomes an additional ceiling."""
    seat_config = SimpleNamespace(tool_groups=["file:read"])
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: seat_config if name == "ceo-agent" else None)
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        escalated = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert "error" in escalated

        within_ceiling = await _hire_report_impl("writer-2", "Writer", "content", "posts/week", ["file:read"], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert within_ceiling["status"] == "active"


@pytest.mark.asyncio
async def test_a_depth_one_manager_with_no_real_agent_config_keeps_no_extra_ceiling(org_world, monkeypatch):  # noqa: F811
    """The common case: an EXECUTIVE.md seat with no real custom-agent record
    behind it. A lookup miss must never block hiring -- known_tool_groups
    alone still applies."""
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: (_ for _ in ()).throw(FileNotFoundError(name)))
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: SimpleNamespace(exists=lambda name: False))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert hired["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [PermissionError("sensitive detail"), ValueError("sensitive detail"), RuntimeError("sensitive detail")])
async def test_manager_config_failure_blocks_hiring_without_a_ledger_insert(org_world, monkeypatch, failure):  # noqa: F811
    def fail_load(name, **_kwargs):
        raise failure

    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", fail_load)
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _assert_hiring_ledger_empty(org_world)
    assert "cannot verify tool permissions" in result["error"]
    assert "Repair" in result["error"]
    assert "sensitive detail" not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ceiling", ["bash", {"bash": True}, [123]])
async def test_malformed_manager_ceiling_cannot_create_a_hire(org_world, monkeypatch, ceiling):  # noqa: F811
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: SimpleNamespace(tool_groups=ceiling))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _assert_hiring_ledger_empty(org_world)
    assert "cannot verify tool permissions" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("record_exists", [True, None])
async def test_missing_config_for_an_existing_or_unverifiable_record_blocks_hiring(org_world, monkeypatch, record_exists):  # noqa: F811
    def exists(name):
        if record_exists is None:
            raise PermissionError("store unavailable")
        return record_exists

    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: (_ for _ in ()).throw(FileNotFoundError(name)))
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: SimpleNamespace(exists=exists))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _assert_hiring_ledger_empty(org_world)
    assert "cannot verify tool permissions" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ceiling,requested,allowed", [(None, ["bash"], True), ([], ["bash"], False), ([], [], True), (["file:read"], ["file:read"], True), (["file:read"], ["bash"], False)])
async def test_configured_manager_ceiling_preserves_none_empty_and_subset_semantics(org_world, monkeypatch, ceiling, requested, allowed):  # noqa: F811
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: AgentConfig(name=name, tool_groups=ceiling))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", requested, 0, "muse", False, runtime=_runtime("ceo-agent"))
        persisted = await HiredAgentRepository(org_world).get_active_hire_by_agent_name("writer-1")
    assert ("error" not in result) is allowed
    assert (persisted is not None) is allowed
    if allowed:
        assert persisted["tool_groups"] == requested


@pytest.mark.asyncio
async def test_invalid_stored_yaml_ceiling_is_blocked_before_hiring(org_world, monkeypatch, tmp_path):  # noqa: F811
    from deerflow.config.paths import Paths
    from deerflow.persistence.agents.file import FileAgentStore

    paths = Paths(tmp_path)
    config_dir = paths.user_agent_dir("storage-s", "ceo-agent")
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("name: ceo-agent\ntool_groups: {bash: true}\n", encoding="utf-8")
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: FileAgentStore())
    # Exercise the actual file loader, overriding the ordinary test's valid
    # unrestricted config instead of replacing validation with a stub.
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **kwargs: FileAgentStore().get(name, **kwargs))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _assert_hiring_ledger_empty(org_world)
    assert "cannot verify tool permissions" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_name", ["CEO-Agent", "ceo_agent"])
async def test_seat_alias_resolves_the_persisted_managers_config_ceiling(org_world, monkeypatch, caller_name):  # noqa: F811
    lookups = []

    def load(name, **_kwargs):
        lookups.append(name)
        if name != "ceo-agent":
            raise FileNotFoundError(name)
        return AgentConfig(name=name, tool_groups=["file:read"])

    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", load)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: SimpleNamespace(exists=lambda name: name == "ceo-agent"))
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, agent_name="ceo-agent")
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime(caller_name))
        await _assert_hiring_ledger_empty(org_world)
    assert lookups == ["ceo-agent"]
    assert "subset" in result["error"]


@pytest.mark.asyncio
async def test_named_manager_loader_returning_none_is_not_an_unrestricted_policy(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda name, **_kwargs: None)
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        result = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", ["bash"], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _assert_hiring_ledger_empty(org_world)
    assert "cannot verify tool permissions" in result["error"]


# --- private-data lane only from a Luna manager ---


@pytest.mark.asyncio
async def test_a_muse_manager_cannot_hire_into_private_data(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)  # defaults to model_family="muse"
        result = await _hire_report_impl("analyst-1", "Analyst", "client analysis", "insights", [], 0, "luna", True, runtime=_runtime("ceo-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_luna_manager_hires_a_luna_report_into_private_data(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, model_family="luna")

        hired = await _hire_report_impl("analyst-1", "Analyst", "client analysis", "insights", [], 0, "luna", True, runtime=_runtime("ceo-agent"))
    assert hired["status"] == "active"
    assert hired["private_data"] is True


@pytest.mark.asyncio
async def test_a_luna_hire_never_itself_granted_private_data_cannot_hire_into_it(org_world):  # noqa: F811
    """review finding (high 1): a Luna model_family alone is not the same as
    being cleared for private data. A Luna CEO hires a Luna report with
    private_data=False; that report must not be able to grant private-data
    access to its own report just because it happens to be a Luna model."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, model_family="luna")
        luna_but_uncleared = await _hire_report_impl("luna-report", "Luna report", "job", "kpi", [], 0, "luna", False, runtime=_runtime("ceo-agent"))
        assert luna_but_uncleared["status"] == "active"
        assert luna_but_uncleared["private_data"] is False

        escalated = await _hire_report_impl("sub-analyst", "Sub analyst", "client work", "kpi", [], 0, "luna", True, runtime=_runtime("luna-report"))
    assert "error" in escalated


# --- budget carved from the manager ---


@pytest.mark.asyncio
async def test_a_hire_budget_cannot_exceed_the_managers_remaining_budget(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, weekly_token_budget=1000)

        first = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 700, "muse", False, runtime=_runtime("ceo-agent"))
        assert first["status"] == "active"

        over_budget = await _hire_report_impl("writer-2", "Writer", "content", "posts/week", [], 400, "muse", False, runtime=_runtime("ceo-agent"))
        assert "error" in over_budget

        under_remaining = await _hire_report_impl("writer-3", "Writer", "content", "posts/week", [], 300, "muse", False, runtime=_runtime("ceo-agent"))
    assert under_remaining["status"] == "active"


@pytest.mark.asyncio
async def test_a_manager_declaring_a_case_variant_name_cannot_double_the_budget(org_world):  # noqa: F811
    """review finding (high 2): ratified_seat_for_agent matches case/
    underscore-insensitively, but the carved-budget query used to compare
    exactly -- a manager declaring "CEO-Agent" the second time around a
    "ceo-agent" claim read a carved budget of 0 and doubled it."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, agent_name="ceo-agent", weekly_token_budget=1000)

        first = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 1000, "muse", False, runtime=_runtime("ceo-agent"))
        assert first["status"] == "active"

        second = await _hire_report_impl("writer-2", "Writer", "content", "posts/week", [], 1000, "muse", False, runtime=_runtime("CEO-Agent"))
    assert "error" in second


@pytest.mark.asyncio
async def test_a_hire_cannot_take_a_name_already_held_by_a_titled_employee(org_world):  # noqa: F811
    """review finding (high 2): a hire may not take an agent_name a ratified
    seat already holds, case/underscore-insensitively."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, agent_name="ceo-agent")

        result = await _hire_report_impl("CEO_Agent", "Impersonator", "job", "kpi", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_hire_cannot_take_a_case_variant_of_an_existing_active_hires_name(org_world):  # noqa: F811
    """f118(b): create_hire_atomic's own hire_conflict check (not just the
    seat_conflict one above) must compare normalized, not raw, names."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        first = await _hire_report_impl("Writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert first["status"] == "active"

        collision = await _hire_report_impl("writer_1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in collision


@pytest.mark.asyncio
async def test_create_hire_atomic_issues_a_write_lock_before_reading_the_racy_aggregates(org_world, monkeypatch):  # noqa: F811
    """f118(c): the SQLite BEGIN IMMEDIATE (or, on Postgres, the advisory
    lock) is what actually closes the concurrent-overspend race (high 3) --
    assert it is really issued, since a true concurrency test isn't
    practical against this fixture's single-connection StaticPool (see the
    PR's own review reply for why)."""
    import deerflow.persistence.hiring.sql as hiring_sql_module

    issued: list[str] = []
    original_text = hiring_sql_module.text

    def _spy_text(value):
        issued.append(value)
        return original_text(value)

    monkeypatch.setattr(hiring_sql_module, "text", _spy_text)

    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert hired["status"] == "active"
    assert any("BEGIN IMMEDIATE" in stmt for stmt in issued)


# --- owner-set headcount cap ---


@pytest.mark.asyncio
async def test_headcount_cap_is_enforced_org_wide(org_world, monkeypatch):  # noqa: F811
    _patch_hiring_config(monkeypatch, headcount_cap=1)
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        first = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert first["status"] == "active"

        second = await _hire_report_impl("writer-2", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in second


# --- org depth cap ---


@pytest.mark.asyncio
async def test_org_depth_cap_is_enforced(org_world, monkeypatch):  # noqa: F811
    _patch_hiring_config(monkeypatch, max_org_depth=2)
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        depth_two = await _hire_report_impl("report-1", "Report", "job", "kpi", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert depth_two["status"] == "active"
        assert depth_two["depth"] == 2

        depth_three = await _hire_report_impl("report-2", "Report", "job", "kpi", [], 0, "muse", False, runtime=_runtime("report-1"))
    assert "error" in depth_three


# --- retire: own reports only ---


@pytest.mark.asyncio
async def test_the_hiring_manager_retires_its_own_report_and_announces_it(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        team_repo = TeamBoardRepository(org_world)
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

        retired = await _retire_report_impl(hired["id"], runtime=_runtime("ceo-agent"))
        assert retired["status"] == "retired"

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert any("[ceo-agent] retired writer-1" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_a_hire_with_active_reports_cannot_be_retired(org_world):  # noqa: F811
    """review finding (high 4): retiring a manager must not orphan its
    reports or silently free the budget it carved out for them."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A, weekly_token_budget=1000)
        manager_hire = await _hire_report_impl("mid", "Mid", "job", "kpi", [], 1000, "muse", False, runtime=_runtime("ceo-agent"))
        await _hire_report_impl("leaf", "Leaf", "job", "kpi", [], 1000, "muse", False, runtime=_runtime(manager_hire["agent_name"]))

        result = await _retire_report_impl(manager_hire["id"], runtime=_runtime("ceo-agent"))
        assert "error" in result

        # The blocked retirement must not have freed any budget: the CEO's
        # 1000-token budget is still fully carved by "mid", so a second
        # 1000-token hire is refused.
        still_blocked = await _hire_report_impl("mid2", "Mid2", "job", "kpi", [], 1000, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in still_blocked


@pytest.mark.asyncio
async def test_a_report_cannot_retire_its_own_siblings(org_world):  # noqa: F811
    """A mismatched agent_name alone must not be enough -- proven with a
    non-owner, non-admin human actor (USER_D), so the owner override
    (actor_is_owner, keyed off the real acting human, not the declared agent
    name) cannot silently paper over the mismatch."""
    with acting_as(USER_A, ORG_S):
        await _add_plain_member(org_world, USER_D, ORG_S)
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

    with acting_as(USER_D, ORG_S):
        result = await _retire_report_impl(hired["id"], runtime=_runtime("rival-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_manager_cannot_retire_its_reports_own_reports_directly(org_world):  # noqa: F811
    """Retirement is not transitive: "own reports" means direct reports only.

    Proven with a non-owner, non-admin human actor for the same reason as
    ``test_a_report_cannot_retire_its_own_siblings``.
    """
    with acting_as(USER_A, ORG_S):
        await _add_plain_member(org_world, USER_D, ORG_S)
        await _ratify_ceo(USER_A)
        manager_hire = await _hire_report_impl("cmo-report", "CMO report", "content strategy", "leads", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        sub_hire = await _hire_report_impl("sub-report", "Sub report", "writing", "posts/week", [], 0, "muse", False, runtime=_runtime(manager_hire["agent_name"]))

    with acting_as(USER_D, ORG_S):
        result = await _retire_report_impl(sub_hire["id"], runtime=_runtime("ceo-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_the_owner_can_retire_any_report_directly(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

        # USER_A is ORG_S's owner (org_isolation_fixtures.MEMBERSHIPS).
        retired = await _retire_report_impl(hired["id"], runtime=_runtime("owner-agent"))
    assert retired["status"] == "retired"


@pytest.mark.asyncio
async def test_an_org_admin_can_retire_via_the_owner_override(org_world):  # noqa: F811
    """actor_is_owner reuses _is_active_org_admin, matching assert_can_reopen's
    existing "owner or admin" convention (f102(c))."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

    with acting_as(USER_C, ORG_S):
        # USER_C is ORG_S's admin (org_isolation_fixtures.MEMBERSHIPS), not
        # the hiring manager.
        retired = await _retire_report_impl(hired["id"], runtime=_runtime("some-other-agent"))
    assert retired["status"] == "retired"


@pytest.mark.asyncio
async def test_a_plain_member_cannot_retire_someone_elses_report(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _add_plain_member(org_world, USER_D, ORG_S)
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

    with acting_as(USER_D, ORG_S):
        result = await _retire_report_impl(hired["id"], runtime=_runtime("some-other-agent"))
    assert "error" in result


# --- suspected findings: manager retired mid-flight, double retire ---


@pytest.mark.asyncio
async def test_create_hire_atomic_refuses_stale_manager_facts_from_a_retired_hire(org_world):  # noqa: F811
    """review finding (suspected): a depth-2+ manager's facts (depth/tools/
    budget) are resolved before create_hire_atomic's lock is taken; if that
    manager was retired in the window between the read and the lock, the
    lock must catch it rather than hire under a manager that no longer
    exists. Exercised directly against create_hire_atomic with stale facts,
    since the real TOCTOU window needs true concurrency to hit naturally."""
    from deerflow.hiring import HireAuthorizationError
    from deerflow.persistence.hiring import HiredAgentRepository

    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        manager_hire = await _hire_report_impl("cmo-report", "CMO report", "content strategy", "leads", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        await _retire_report_impl(manager_hire["id"], runtime=_runtime("ceo-agent"))

        repo = HiredAgentRepository(org_world)
        with pytest.raises(HireAuthorizationError):
            await repo.create_hire_atomic(
                agent_name="sub-report",
                title="Sub report",
                manager_agent_name="cmo-report",
                manager_depth=manager_hire["depth"],  # stale: read before the retirement above
                max_org_depth=3,
                manager_tool_groups=None,
                known_tool_groups=None,
                manager_cleared_for_private_data=False,
                manager_weekly_token_budget=0,
                headcount_cap=20,
            )


@pytest.mark.asyncio
async def test_retire_is_a_no_op_on_an_already_retired_hire(org_world):  # noqa: F811
    """review finding (suspected): retire() must not silently overwrite an
    already-retired row's retired_at/retired_by_user_id on a second call."""
    from deerflow.persistence.hiring import HiredAgentRepository

    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

        repo = HiredAgentRepository(org_world)
        first = await repo.retire(hired["id"], retired_by_user_id=USER_A)
        assert first is not None

        second = await repo.retire(hired["id"], retired_by_user_id="someone-else")
    assert second is None
    assert first["retired_by_user_id"] == USER_A


# --- organization isolation ---


@pytest.mark.asyncio
async def test_a_hire_is_invisible_and_unretireable_from_another_organization(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        hired = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))

    with acting_as(USER_A, ORG_A):
        result = await _retire_report_impl(hired["id"], runtime=_runtime("ceo-agent"))
    assert "error" in result


@pytest.mark.asyncio
async def test_a_manager_in_another_org_with_the_same_agent_name_cannot_hire_as_someone_elses_manager(org_world):  # noqa: F811
    """ORG_A's CEO seat is claimed independently of ORG_S's -- no cross-org authority leaks."""
    with acting_as(USER_A, ORG_S):
        await _ratify_ceo(USER_A)
        s_hire = await _hire_report_impl("writer-1", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
        assert s_hire["status"] == "active"

    with acting_as(USER_A, ORG_A):
        # No seat has ever been claimed in ORG_A -- the same agent_name
        # ("ceo-agent") carries no authority here.
        result = await _hire_report_impl("writer-2", "Writer", "content", "posts/week", [], 0, "muse", False, runtime=_runtime("ceo-agent"))
    assert "error" in result


# --- tool-group opt-in ---


def test_hire_tools_are_opted_in_by_group():
    config = SimpleNamespace(
        tools=[
            SimpleNamespace(name="read_file", group="file:read", use="deerflow.sandbox.tools:read_file_tool"),
            SimpleNamespace(name="hire_report", group="hire", use="deerflow.tools.hire_tools:hire_report"),
            SimpleNamespace(name="retire_report", group="hire", use="deerflow.tools.hire_tools:retire_report"),
        ],
        models=[],
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", allow_host_bash=False),
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )
    names_default = {t.name for t in get_available_tools(groups=None, include_mcp=False, subagent_enabled=False, app_config=config)}
    assert "hire_report" not in names_default
    assert "retire_report" not in names_default

    names_opted_in = {t.name for t in get_available_tools(groups=["file:read", "hire"], include_mcp=False, subagent_enabled=False, app_config=config)}
    assert "hire_report" in names_opted_in
    assert "retire_report" in names_opted_in
