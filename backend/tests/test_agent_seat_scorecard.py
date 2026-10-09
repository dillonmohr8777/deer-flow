"""Tests for the weekly agent-seat scorecard sweep (queue item e11, friday-scorecards).

EXECUTIVE.md rule 3: "Every Friday, each employee posts a scorecard. Two
missed weeks and the title reopens." Covers the accept bar with a stubbed
model (``generate``): a successful scorecard posts to ``#exec`` and resets
the miss counter, a completed blank one counts as an evaluated miss, and
the second consecutive evaluated miss reopens the seat. Infrastructure,
model and delivery failures preserve the employee's record.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, acting_as, org_world  # noqa: F401

from deerflow.exec_seats import scorecard
from deerflow.exec_seats.scorecard import evaluate_all_seat_scorecards, evaluate_seat_scorecard
from deerflow.persistence.exec_seats import AgentSeatRepository, AgentSeatStatus
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.exec_seat_tools import announce_to_exec

CMO_SEAT = "CMO"


async def _spend(session_factory, *, organization_id: str, agent_name: str, total_tokens: int, created_at: datetime) -> None:
    """Mirrors test_agent_seat_budget.py's own helper of the same name."""
    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-{agent_name}-{organization_id}-{created_at.timestamp()}",
                thread_id=f"thread-{agent_name}",
                assistant_id=agent_name,
                organization_id=organization_id,
                status="success",
                total_tokens=total_tokens,
                created_at=created_at,
                updated_at=created_at,
            )
        )


async def _succeed(_seat: dict) -> str:
    return "Shipped the Q4 landing page refresh; three qualified leads booked this week."


async def _blank(_seat: dict) -> str | None:
    return "   "


async def _confirmed(_text: str) -> bool:
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "model_creation", "model_call", "missing_content", "null_content", "invalid_content"])
async def test_generation_distinguishes_a_completed_blank_from_a_model_outage(monkeypatch, failure):
    class Model:
        async def ainvoke(self, _messages, *, config):
            if failure == "model_call":
                raise RuntimeError("provider unavailable")
            if failure == "missing_content":
                return SimpleNamespace()
            if failure == "null_content":
                return SimpleNamespace(content=None)
            if failure == "invalid_content":
                return SimpleNamespace(content=123)
            return SimpleNamespace(content="   ")

    def _create(**_kwargs):
        if failure == "model_creation":
            raise RuntimeError("model configuration unavailable")
        return Model()

    monkeypatch.setattr(scorecard, "create_chat_model", _create)
    body = await scorecard.generate_scorecard_body({"agent_name": "cmo-agent", "seat": CMO_SEAT}, app_config=SimpleNamespace())
    assert body == ("" if failure is None else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["generation_none", "generation_exception", "usage_exception", "delivery_false", "delivery_exception"])
@pytest.mark.parametrize("body", ["posted scorecard", "   "])
async def test_infrastructure_failure_preserves_a_prior_miss_and_leaves_the_seat_due(org_world, monkeypatch, failure, body):  # noqa: F811
    """An outage after one genuine miss must not masquerade as the second missed week."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    announcements: list[str] = []

    async def _generate(_seat: dict) -> str | None:
        if failure == "generation_exception":
            raise RuntimeError("provider unavailable")
        return None if failure == "generation_none" else body

    async def _announce(text: str) -> bool:
        announcements.append(text)
        if failure == "delivery_exception":
            raise RuntimeError("storage unavailable")
        return failure != "delivery_false"

    async def _usage_unavailable(**_kwargs) -> int:
        raise RuntimeError("usage storage unavailable")

    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        seat = await repo.record_scorecard_result(seat["id"], success=False, now=now - timedelta(days=8))
        if failure == "usage_exception":
            monkeypatch.setattr(repo, "token_burn_since", _usage_unavailable)

        updated = await evaluate_seat_scorecard(repo, seat, now=now, announce=_announce, generate=_generate)
        persisted = await repo.get_seat(seat["id"])

    assert updated == seat
    assert persisted == seat
    assert updated["missed_scorecards"] == 1
    assert updated["status"] == AgentSeatStatus.RATIFIED
    assert not any("reopened" in text for text in announcements)


@pytest.mark.asyncio
async def test_no_announcement_route_is_inconclusive_without_calling_the_model(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    calls: list[dict] = []

    async def _tracked(seat: dict) -> str:
        calls.append(seat)
        return "scorecard"

    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        updated = await evaluate_seat_scorecard(repo, seat, generate=_tracked)
        persisted = await repo.get_seat(seat["id"])

    assert calls == []
    assert updated == persisted == seat


@pytest.mark.asyncio
async def test_successful_scorecard_posts_to_exec_and_resets_misses(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        seat = await repo.record_scorecard_result(seat["id"], success=False, now=now - timedelta(days=8))  # one prior miss, now stale

        updated = await evaluate_seat_scorecard(repo, seat, now=now, announce=announce_to_exec, generate=_succeed)
        persisted = await repo.get_seat(seat["id"])

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert updated["missed_scorecards"] == 0
    assert persisted == updated
    assert updated["status"] == AgentSeatStatus.RATIFIED
    assert updated["last_scorecard_at"] is not None
    assert any("weekly scorecard" in m["body"] and "Q4 landing page" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_first_miss_is_recorded_and_does_not_reopen(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        updated = await evaluate_seat_scorecard(repo, seat, now=now, announce=announce_to_exec, generate=_blank)

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert updated["missed_scorecards"] == 1
    assert updated["status"] == AgentSeatStatus.RATIFIED
    assert any("missed" in m["body"] and "1/2" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_a_blank_scorecard_counts_as_a_miss(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        updated = await evaluate_seat_scorecard(repo, seat, now=now, announce=_confirmed, generate=_blank)

    assert updated["missed_scorecards"] == 1


@pytest.mark.asyncio
async def test_second_consecutive_miss_reopens_the_seat(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        first_miss = now - timedelta(days=8)
        second_miss = now
        seat = await evaluate_seat_scorecard(repo, seat, now=first_miss, announce=announce_to_exec, generate=_blank)
        assert seat["missed_scorecards"] == 1
        assert seat["status"] == AgentSeatStatus.RATIFIED

        reopened = await evaluate_seat_scorecard(repo, seat, now=second_miss, announce=announce_to_exec, generate=_blank)
        persisted = await repo.get_seat(seat["id"])

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert reopened["status"] == AgentSeatStatus.REOPENED
    assert reopened["missed_scorecards"] == 2
    assert persisted == reopened
    assert any("reopened" in m["body"] and "missed two weekly scorecards" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_a_success_after_one_miss_resets_the_counter_instead_of_reopening(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        seat = await evaluate_seat_scorecard(repo, seat, now=now - timedelta(days=8), announce=announce_to_exec, generate=_blank)
        assert seat["missed_scorecards"] == 1

        recovered = await evaluate_seat_scorecard(repo, seat, now=now, announce=announce_to_exec, generate=_succeed)

    assert recovered["missed_scorecards"] == 0
    assert recovered["status"] == AgentSeatStatus.RATIFIED


@pytest.mark.asyncio
async def test_a_successful_draft_with_no_exec_channel_is_inconclusive(org_world):  # noqa: F811
    """Preserve confirmed-post success semantics without penalizing a missing route.

    This intentionally changes f107's earlier undelivered-draft-as-miss policy.
    An unposted draft can neither reset a genuine prior miss nor reopen the seat.
    """
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        # Deliberately no team_repo.ensure_default_channels() -- no #exec exists in this org.
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        seat = await repo.record_scorecard_result(seat["id"], success=False, now=now - timedelta(days=8))

        updated = await evaluate_seat_scorecard(repo, seat, now=now, announce=announce_to_exec, generate=_succeed)
        persisted = await repo.get_seat(seat["id"])

    assert updated == persisted == seat
    assert updated["missed_scorecards"] == 1
    assert updated["status"] == AgentSeatStatus.RATIFIED


@pytest.mark.asyncio
async def test_an_evaluated_miss_still_advances_last_scorecard_at(org_world):  # noqa: F811
    """Review finding (medium, test gap): a miss must still mark this week as checked, or two
    sweeps an hour apart (not two separate missed weeks) could reopen a seat. Mutation this
    guards: record_scorecard_result advancing last_scorecard_at only on success."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    calls: list[dict] = []

    async def _tracked_miss(seat: dict) -> str:
        calls.append(seat)
        return ""

    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        seat = await evaluate_seat_scorecard(repo, seat, now=now, announce=_confirmed, generate=_tracked_miss)
        assert seat["missed_scorecards"] == 1
        assert len(calls) == 1

        # One hour later: still the same trailing week, so this must not re-evaluate at all.
        untouched = await evaluate_seat_scorecard(repo, seat, now=now + timedelta(hours=1), announce=_confirmed, generate=_tracked_miss)

    assert untouched["missed_scorecards"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_seat_already_checked_this_week_is_not_re_evaluated(org_world):  # noqa: F811
    """last_scorecard_at within the trailing week means not due -- generate must never be called."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    calls: list[dict] = []

    async def _tracked(seat: dict) -> str:
        calls.append(seat)
        return "should not run"

    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        seat = await repo.record_scorecard_result(seat["id"], success=True, now=now - timedelta(days=2))

        untouched = await evaluate_seat_scorecard(repo, seat, now=now, generate=_tracked)

    assert calls == []
    assert untouched is seat


@pytest.mark.asyncio
async def test_only_ratified_seats_are_evaluated(org_world):  # noqa: F811
    """A still-claimed (unratified) or reopened seat owes no scorecard -- nobody's title is confirmed yet, or nobody holds it."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    calls: list[dict] = []

    async def _tracked(seat: dict) -> str:
        calls.append(seat)
        return "should not run"

    with acting_as(USER_A, ORG_A):
        claimed = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        ratified = await repo.patch_seat(claimed["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        reopened = await repo.patch_seat(ratified["id"], status=AgentSeatStatus.REOPENED)

        still_claimed = await repo.claim_seat(seat="CTO", agent_name="cto-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)

        untouched_reopened = await evaluate_seat_scorecard(repo, reopened, now=now, generate=_tracked)
        untouched_claimed = await evaluate_seat_scorecard(repo, still_claimed, now=now, generate=_tracked)

    assert calls == []
    assert untouched_reopened is reopened
    assert untouched_claimed is still_claimed


@pytest.mark.asyncio
async def test_evaluate_all_seat_scorecards_covers_every_ratified_seat(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        cmo = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        cmo = await repo.patch_seat(cmo["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        cto = await repo.claim_seat(seat="CTO", agent_name="cto-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        cto = await repo.patch_seat(cto["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)

        results = await evaluate_all_seat_scorecards(repo, now=now, announce=announce_to_exec, generate=_succeed)

    by_seat = {r["seat"]: r for r in results}
    assert by_seat["CMO"]["missed_scorecards"] == 0
    assert by_seat["CTO"]["missed_scorecards"] == 0
    assert by_seat["CMO"]["last_scorecard_at"] is not None
    assert by_seat["CTO"]["last_scorecard_at"] is not None


@pytest.mark.asyncio
async def test_generate_receives_the_seats_real_weekly_token_burn(org_world):  # noqa: F811
    """Review finding (f118a, test gap): the prompt's grounding data (weekly_token_burn) must
    actually reach generate's seat argument, and must be scoped to the seat's own organization
    -- a same-named agent's burn in a different org must never leak in."""
    repo = AgentSeatRepository(org_world)
    now = datetime.now(UTC)
    captured: list[dict] = []

    async def _capture(seat: dict) -> str:
        captured.append(seat)
        return "ok"

    with acting_as(USER_A, ORG_A):
        seat = await repo.claim_seat(seat=CMO_SEAT, agent_name="cmo-agent", weekly_token_budget=1000, claimed_by_user_id=USER_A)
        seat = await repo.patch_seat(seat["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
        await _spend(org_world, organization_id=ORG_A, agent_name="cmo-agent", total_tokens=250, created_at=now - timedelta(hours=1))

    await _spend(org_world, organization_id=ORG_B, agent_name="cmo-agent", total_tokens=99_999, created_at=now - timedelta(hours=1))

    with acting_as(USER_A, ORG_A):
        await evaluate_seat_scorecard(repo, seat, now=now, announce=_confirmed, generate=_capture)

    assert len(captured) == 1
    assert captured[0]["weekly_token_burn"] == 250
