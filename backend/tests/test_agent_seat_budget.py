"""Tests for weekly seat token-budget enforcement (queue item e10, seat-budgets).

Covers the accept bar directly: a seat over its weekly token budget gets
paused, and one back under budget (a new week rolling the old burn out of the
trailing window) resumes -- both announced to ``#exec`` via
``deerflow.tools.exec_seat_tools.announce_to_exec``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, acting_as, org_world  # noqa: F401

from deerflow.exec_seats.budget import evaluate_all_seat_budgets, evaluate_seat_budget, is_over_budget
from deerflow.persistence.exec_seats import EFFECTIVE_AGENT_NAME_METADATA_KEY, AgentSeatRepository, AgentSeatStatus
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.exec_seat_tools import announce_to_exec

CMO_SEAT = "CMO"
_DEFAULT_ASSISTANT_ID = "lead_agent"


def test_is_over_budget_pure():
    assert is_over_budget(1500, 1000) is True
    assert is_over_budget(1000, 1000) is True  # at cap counts as over
    assert is_over_budget(999, 1000) is False
    assert is_over_budget(1_000_000, 0) is False  # 0 == unlimited


async def _spend(session_factory, *, organization_id: str, agent_name: str, total_tokens: int, created_at: datetime) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-{agent_name}-{created_at.timestamp()}",
                thread_id=f"thread-{agent_name}",
                assistant_id=agent_name,
                organization_id=organization_id,
                status="success",
                total_tokens=total_tokens,
                created_at=created_at,
                updated_at=created_at,
            )
        )


async def _spend_via_context_agent_name(session_factory, *, organization_id: str, agent_name: str, total_tokens: int, created_at: datetime) -> None:
    """A run that only ever named its agent through ``context.agent_name``.

    ``assistant_id`` stays the default lead agent -- the gap queue item f95
    left open: ``start_run`` stamps the resolved identity onto run metadata
    instead, which ``token_burn_since`` must also match against.
    """
    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-ctx-{agent_name}-{created_at.timestamp()}",
                thread_id=f"thread-ctx-{agent_name}",
                assistant_id=_DEFAULT_ASSISTANT_ID,
                organization_id=organization_id,
                status="success",
                total_tokens=total_tokens,
                metadata_json={EFFECTIVE_AGENT_NAME_METADATA_KEY: agent_name},
                created_at=created_at,
                updated_at=created_at,
            )
        )


async def _spend_with_divergent_identity(session_factory, *, organization_id: str, assistant_id: str, effective_agent_name: str, total_tokens: int, created_at: datetime) -> None:
    """A run whose raw ``assistant_id`` and stamped ``effective_agent_name`` disagree.

    ``assistant_id`` is client-chosen; the agent that actually ran is the
    stamped identity (f98 review of f97). This must count once, toward the
    stamped identity only -- never toward the raw ``assistant_id`` too.
    """
    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-divergent-{assistant_id}-{created_at.timestamp()}",
                thread_id=f"thread-divergent-{assistant_id}",
                assistant_id=assistant_id,
                organization_id=organization_id,
                status="success",
                total_tokens=total_tokens,
                metadata_json={EFFECTIVE_AGENT_NAME_METADATA_KEY: effective_agent_name},
                created_at=created_at,
                updated_at=created_at,
            )
        )


@pytest.mark.asyncio
async def test_seat_over_budget_is_paused_and_announced(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=1500, created_at=now - timedelta(days=1))

        updated = await evaluate_seat_budget(repo, seat, now=now, announce=announce_to_exec)

        assert updated["paused_at"] is not None
        assert updated["status"] == AgentSeatStatus.RATIFIED  # budget pause never touches the claim state machine

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert any("blocked" in m["body"] and "CMO" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_seat_under_budget_is_never_paused(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=200, created_at=now - timedelta(days=1))

        updated = await evaluate_seat_budget(repo, seat, now=now)

    assert updated["paused_at"] is None


@pytest.mark.asyncio
async def test_seat_resumes_once_old_burn_rolls_out_of_the_week(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=1500, created_at=now - timedelta(days=1))
        paused = await evaluate_seat_budget(repo, seat, now=now, announce=announce_to_exec)
        assert paused["paused_at"] is not None

        # Eight days later: the old spend has rolled out of the trailing week, no new spend since.
        later = now + timedelta(days=8)
        resumed = await evaluate_seat_budget(repo, paused, now=later, announce=announce_to_exec)

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert resumed["paused_at"] is None
    assert resumed["status"] == AgentSeatStatus.RATIFIED
    assert any("resumed" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_only_claimed_or_ratified_seats_are_evaluated(org_world):  # noqa: F811
    """A reopened (no active holder) seat is left alone -- nobody is running under its name."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        reopened = await repo.patch_seat(seat["id"], status=AgentSeatStatus.REOPENED)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=5000, created_at=now - timedelta(hours=1))

        untouched = await evaluate_seat_budget(repo, reopened, now=now)

    assert untouched["paused_at"] is None
    assert untouched is reopened


@pytest.mark.asyncio
async def test_token_burn_is_scoped_to_the_seats_own_organization(org_world):  # noqa: F811
    """A same-named agent burning tokens in another org must never pause this org's seat."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

    # Foreign org's own "cmo-agent" seat burns plenty -- must not leak into ORG_A's seat.
    await _spend(org_world, organization_id=ORG_B, agent_name="cmo-agent", total_tokens=50_000, created_at=now - timedelta(hours=1))

    with acting_as(USER_A, ORG_A):
        updated = await evaluate_seat_budget(repo, seat, now=now)

    assert updated["paused_at"] is None


@pytest.mark.asyncio
async def test_evaluate_all_seat_budgets_covers_every_seat_in_the_org(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        over = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        over = await repo.patch_seat(over["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        under = await repo.claim_seat(seat="CTO", agent_name="cto-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        under = await repo.patch_seat(under["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=2000, created_at=now - timedelta(hours=1))
        await _spend(org_world, organization_id=ORG_A, agent_name="cto-agent", total_tokens=50, created_at=now - timedelta(hours=1))

        results = await evaluate_all_seat_budgets(repo, now=now)

    by_seat = {r["seat"]: r for r in results}
    assert by_seat["CMO"]["paused_at"] is not None
    assert by_seat["CTO"]["paused_at"] is None


@pytest.mark.asyncio
async def test_context_agent_name_run_counts_toward_seat_burn_with_default_assistant_id(org_world):  # noqa: F811
    """f95's own left-open gap: a run naming its agent only via context.agent_name
    (assistant_id stays the default lead agent) must still count toward that
    agent's seat burn, via the metadata start_run now stamps on every run."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend_via_context_agent_name(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=1500, created_at=now - timedelta(days=1))

        updated = await evaluate_seat_budget(repo, seat, now=now)

    assert updated["paused_at"] is not None


@pytest.mark.asyncio
async def test_token_burn_since_sums_both_assistant_id_and_context_agent_name_runs(org_world):  # noqa: F811
    """Both a direct custom-agent run and a context-only run must be counted,
    without double-counting a run that happens to carry both."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=100, created_at=now - timedelta(hours=1))
        await _spend_via_context_agent_name(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=50, created_at=now - timedelta(hours=1))

        burn = await repo.token_burn_since(organization_id=ORG_A, agent_name="cmo-agent", since=now - timedelta(days=7))

    assert burn == 150


@pytest.mark.asyncio
async def test_token_burn_since_matches_case_and_underscore_variants(org_world):  # noqa: F811
    """f97 review of f95/PR #85: burn accounting and pause matching must agree
    on name casing. A seat titled ``cmo-agent`` must still see the spend from
    a raw ``assistant_id`` of ``CMO_Agent`` and a ``context.agent_name`` of
    ``CMO-Agent`` (stamped into ``effective_agent_name`` metadata) -- the same
    normalization ``paused_seat_for_agent`` already applies when deciding
    whether to block those exact same variants."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _spend(org_world, organization_id=ORG_A, agent_name="CMO_Agent", total_tokens=900, created_at=now - timedelta(hours=1))
        await _spend_via_context_agent_name(org_world, organization_id=ORG_A, agent_name="CMO-Agent", total_tokens=600, created_at=now - timedelta(hours=1))

        burn = await repo.token_burn_since(organization_id=ORG_A, agent_name="cmo-agent", since=now - timedelta(days=7))

    assert burn == 1500


@pytest.mark.asyncio
async def test_case_variant_context_agent_name_run_pauses_the_seat(org_world):  # noqa: F811
    """The exact repro from the f97 review: a seat for cmo-agent (budget 1000)
    plus a 1500-token run stamped CMO-Agent must pause -- before the fix,
    token_burn_since returned 0 for this case even though
    paused_seat_for_agent("CMO-Agent") already matched the seat."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend_via_context_agent_name(org_world, organization_id=ORG_A, agent_name="CMO-Agent", total_tokens=1500, created_at=now - timedelta(hours=1))

        updated = await evaluate_seat_budget(repo, seat, now=now)

    assert updated["paused_at"] is not None


@pytest.mark.asyncio
async def test_token_burn_since_uses_the_stamped_identity_not_the_raw_assistant_id(org_world):  # noqa: F811
    """f98 review of f97: the exact repro. A run POSTed with
    ``assistant_id="CMO_Agent"`` but ``configurable.agent_name="other-agent"``
    is really run by ``other-agent`` -- the stamped identity, not the raw
    client-chosen ``assistant_id`` -- so its burn must count once, toward
    ``other-agent`` only. Before the fix, the ``or_`` match counted it toward
    both names."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _spend_with_divergent_identity(org_world, organization_id=ORG_A, assistant_id="CMO_Agent", effective_agent_name="other-agent", total_tokens=5000, created_at=now - timedelta(hours=1))

        cmo_burn = await repo.token_burn_since(organization_id=ORG_A, agent_name="cmo-agent", since=now - timedelta(days=7))
        other_burn = await repo.token_burn_since(organization_id=ORG_A, agent_name="other-agent", since=now - timedelta(days=7))

    assert cmo_burn == 0
    assert other_burn == 5000


@pytest.mark.asyncio
async def test_token_burn_since_still_matches_a_legacy_row_with_no_stamp(org_world):  # noqa: F811
    """A run written before the f95 metadata stamp existed has no
    ``effective_agent_name`` key at all (``metadata_json`` defaults to
    ``{}``) -- ``coalesce`` must fall back to ``assistant_id`` for it, not
    drop it from the ledger."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=700, created_at=now - timedelta(hours=1))

        burn = await repo.token_burn_since(organization_id=ORG_A, agent_name="cmo-agent", since=now - timedelta(days=7))

    assert burn == 700


@pytest.mark.asyncio
async def test_token_burn_since_with_no_organization_never_sums_across_orgs(org_world):  # noqa: F811
    """f99: a caller with no resolved organization must never see the union of
    every organization's spend for a same-named agent. Before the fix,
    ``organization_id=None`` skipped the org filter entirely and this probe
    summed ORG_A's 100 plus ORG_B's 200 into 300."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=100, created_at=now - timedelta(hours=1))
    with acting_as(USER_A, ORG_B):
        await _spend(org_world, organization_id=ORG_B, agent_name="cmo-agent", total_tokens=200, created_at=now - timedelta(hours=2))

    burn = await repo.token_burn_since(organization_id=None, agent_name="cmo-agent", since=now - timedelta(days=7))

    assert burn == 0


@pytest.mark.asyncio
async def test_token_burn_since_counts_a_null_org_seats_own_burn(org_world):  # noqa: F811
    """f123 (review of the f99 fix): a seat claimed with no active org (auth-disabled
    or an internal caller -- ``organization_for_write``'s quarantine marker, a real,
    not hypothetical, state) is itself stored with ``organization_id=None``. Its own
    burn must still count toward its own budget -- the f99 fix must not zero every
    null-org seat's burn just to stop it from summing *other* orgs' burn too."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    await _spend(org_world, organization_id=None, agent_name="cmo-agent", total_tokens=1500, created_at=now - timedelta(hours=1))
    with acting_as(USER_A, ORG_A):
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=999_000, created_at=now - timedelta(hours=2))

    burn = await repo.token_burn_since(organization_id=None, agent_name="cmo-agent", since=now - timedelta(days=7))

    assert burn == 1500
