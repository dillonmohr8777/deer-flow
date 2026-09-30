"""Tests for the CEO Desk daily digest (queue item e14, backend digest slice).

``build_digest_window`` is pure counting against real ``BoardRepository``/
``AgentSeatRepository`` state (mirrors ``test_agent_seat_scorecard.py``'s use
of real repos with a stubbed model). ``generate_daily_digest`` is covered
separately with a stubbed model, mirroring
``test_agent_seat_scorecard.py``'s ``test_generation_distinguishes_a_completed_blank_from_a_model_outage``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, acting_as, org_world  # noqa: F401

from deerflow.ceo_desk import digest
from deerflow.ceo_desk.digest import DigestWindow, build_digest_window, generate_daily_digest
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.board.model import BoardThreadRow
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.exec_seats import AgentSeatRepository

pytestmark = pytest.mark.asyncio


async def _age_thread(session_factory, thread_id: str, updated_at: datetime) -> None:
    """Force a thread's ``updated_at`` directly at the ORM layer.

    ``patch_thread`` always stamps ``updated_at=now()`` (see the model's
    ``onupdate``), so a test needing a thread that looks untouched since
    before the window has to set it here instead -- mirrors
    ``test_board_router.py``'s direct-ORM pattern for otherwise-unreachable
    states.
    """
    async with session_factory() as session, session.begin():
        row = await session.get(BoardThreadRow, thread_id)
        row.updated_at = updated_at


async def test_build_digest_window_counts_shipped_stuck_and_needs_my_yes(org_world):  # noqa: F811
    session_factory = org_world
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)

    with acting_as(USER_A, ORG_S):
        client_repo = ClientRepository(session_factory)
        board_repo = BoardRepository(session_factory)
        seat_repo = AgentSeatRepository(session_factory)

        acme = await client_repo.create(display_name="Acme")

        shipped = await board_repo.create_thread(client_id=acme["id"], kind="ticket", subject="Broken widget fixed")
        await board_repo.patch_thread(shipped["id"], status="replied")  # updated_at stamped to "now", inside the window

        stuck = await board_repo.create_thread(client_id=acme["id"], kind="concern", subject="Still waiting on a callback")
        await _age_thread(session_factory, stuck["id"], now - timedelta(days=3))

        # Drafted and new-but-recent threads: neither shipped nor stuck.
        recent_open = await board_repo.create_thread(client_id=acme["id"], kind="post", subject="Just opened")
        assert recent_open["status"] == "new"

        drafted = await board_repo.create_thread(client_id=acme["id"], kind="ticket", subject="Awaiting owner approval")
        await board_repo.patch_thread(drafted["id"], status="drafted")

        await seat_repo.claim_seat(seat="cmo", agent_name="cmo-agent", kpi="pipeline", weekly_token_budget=0, claimed_by_user_id=USER_A)

        window = await build_digest_window(board_repo, seat_repo, since=since, now=now)

    assert window.shipped_count == 1
    assert window.shipped_subjects == ["Broken widget fixed"]
    assert window.stuck_count == 1
    assert window.stuck_subjects == ["Still waiting on a callback"]
    assert window.needs_my_yes_drafts == 1
    assert window.needs_my_yes_ratifications == 1


async def test_build_digest_window_is_all_zero_with_nothing_recorded(org_world):  # noqa: F811
    session_factory = org_world
    with acting_as(USER_A, ORG_S):
        board_repo = BoardRepository(session_factory)
        seat_repo = AgentSeatRepository(session_factory)
        window = await build_digest_window(board_repo, seat_repo)

    assert window == DigestWindow(
        shipped_count=0,
        shipped_subjects=[],
        stuck_count=0,
        stuck_subjects=[],
        needs_my_yes_drafts=0,
        needs_my_yes_ratifications=0,
    )


@pytest.mark.parametrize("failure", [None, "model_creation", "model_call", "missing_content", "null_content", "invalid_content"])
async def test_generate_daily_digest_distinguishes_a_completed_blank_from_a_model_outage(monkeypatch, failure):
    window = DigestWindow(shipped_count=0, shipped_subjects=[], stuck_count=0, stuck_subjects=[], needs_my_yes_drafts=0, needs_my_yes_ratifications=0)

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

    monkeypatch.setattr(digest, "create_chat_model", _create)
    body = await generate_daily_digest(window, app_config=SimpleNamespace())
    assert body == ("" if failure is None else None)


async def test_generate_daily_digest_grounds_the_prompt_in_the_window_counts(monkeypatch):
    window = DigestWindow(
        shipped_count=2,
        shipped_subjects=["Site relaunch", "Q4 report sent"],
        stuck_count=1,
        stuck_subjects=["Billing dispute"],
        needs_my_yes_drafts=3,
        needs_my_yes_ratifications=1,
    )
    seen_prompt = {}

    class Model:
        async def ainvoke(self, messages, *, config):
            seen_prompt["text"] = messages[0]["content"]
            return SimpleNamespace(content="Shipped 2. Stuck on 1. 4 things need your yes.")

    monkeypatch.setattr(digest, "create_chat_model", lambda **_kwargs: Model())
    body = await generate_daily_digest(window, app_config=SimpleNamespace())

    assert body == "Shipped 2. Stuck on 1. 4 things need your yes."
    prompt = seen_prompt["text"]
    assert "2 board thread(s) closed out (Site relaunch, Q4 report sent)" in prompt
    assert "1 board thread(s) (Billing dispute)" in prompt
    assert "3 drafted board replies awaiting approval, 1 seat claim(s) awaiting ratification" in prompt
    assert "do not invent" in prompt.lower()
