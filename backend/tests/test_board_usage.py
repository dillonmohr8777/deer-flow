"""Momo Board usage-ledger recording (Workspace Phase 4 item e7).

``record_board_model_usage`` writes directly into the same ``runs`` /
``run_events`` tables ``GET /api/console/usage-ledger``
(``app/gateway/routers/console.py::console_usage_ledger``) queries -- these
tests build a real in-memory SQLite database (matching
``test_board_concierge.py``'s ``board_repo`` fixture) and assert the exact
join that endpoint performs (``RunRow.run_id == RunEventRow.run_id and
RunRow.thread_id == RunEventRow.thread_id``, ``RunRow.operation_kind ==
"run"``, ``RunEventRow.event_type in ("llm.ai.response", "llm.error")``)
returns the recorded organization, with the client carried in the event's
own metadata (the ledger has no ``client_id`` column).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from deerflow.board.usage import record_board_model_usage
from deerflow.persistence.base import Base
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.run.model import RunRow


@pytest_asyncio.fixture()
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("deerflow.board.usage.get_session_factory", lambda: sf)
    yield sf
    await engine.dispose()


async def _usage_ledger_rows(sf) -> list[tuple[RunEventRow, RunRow]]:
    """The same join ``console_usage_ledger`` runs against ``runs``/``run_events``."""
    stmt = select(RunEventRow, RunRow).join(RunRow, (RunRow.run_id == RunEventRow.run_id) & (RunRow.thread_id == RunEventRow.thread_id)).where(RunRow.operation_kind == "run", RunEventRow.event_type.in_(("llm.ai.response", "llm.error")))
    async with sf() as session:
        return (await session.execute(stmt)).all()


@pytest.mark.anyio
async def test_records_a_successful_call_visible_to_the_usage_ledger_query(session_factory):
    response = SimpleNamespace(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        response_metadata={"model_name": "gpt-mini"},
    )

    await record_board_model_usage(
        caller="board_triage",
        attempt_status="success",
        organization_id="org-1",
        client_id="client-1",
        board_thread_id="thread-1",
        requested_model="gpt-mini-requested",
        response=response,
    )

    rows = await _usage_ledger_rows(session_factory)
    assert len(rows) == 1
    event, run = rows[0]
    assert run.organization_id == "org-1"
    assert run.assistant_id == "board_triage"
    assert event.event_type == "llm.ai.response"
    assert event.event_metadata["client_id"] == "client-1"
    assert event.event_metadata["board_thread_id"] == "thread-1"
    assert event.event_metadata["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert event.event_metadata["resolved_model"] == "gpt-mini"
    assert event.event_metadata["requested_model"] == "gpt-mini-requested"
    assert event.event_metadata["attempt_status"] == "success"


@pytest.mark.anyio
async def test_records_a_failed_call_as_an_llm_error_event(session_factory):
    await record_board_model_usage(
        caller="board_concierge",
        attempt_status="error",
        organization_id="org-2",
        client_id="client-2",
        board_thread_id="thread-2",
        requested_model="gpt-mini",
        error_type="RuntimeError",
    )

    rows = await _usage_ledger_rows(session_factory)
    assert len(rows) == 1
    event, run = rows[0]
    assert run.status == "error"
    assert event.event_type == "llm.error"
    assert event.event_metadata["error_type"] == "RuntimeError"
    assert event.event_metadata["client_id"] == "client-2"


@pytest.mark.anyio
async def test_multiple_calls_for_the_same_board_thread_all_appear(session_factory):
    await record_board_model_usage(caller="board_triage", attempt_status="success", organization_id="org-1", client_id="client-1", board_thread_id="thread-3", response=SimpleNamespace())
    await record_board_model_usage(caller="board_concierge", attempt_status="success", organization_id="org-1", client_id="client-1", board_thread_id="thread-3", response=SimpleNamespace())

    rows = await _usage_ledger_rows(session_factory)
    assert len(rows) == 2
    assert {event.event_metadata["caller"] for event, _ in rows} == {"board_triage", "board_concierge"}


@pytest.mark.anyio
async def test_no_op_on_memory_backend(monkeypatch):
    monkeypatch.setattr("deerflow.board.usage.get_session_factory", lambda: None)

    # Must not raise even though there is nowhere to write.
    await record_board_model_usage(caller="board_triage", attempt_status="success", organization_id="org-1", client_id="client-1")


@pytest.mark.anyio
async def test_swallows_a_broken_session_factory(monkeypatch):
    monkeypatch.setattr("deerflow.board.usage.get_session_factory", lambda: (_ for _ in ()).throw(RuntimeError("db is down")))

    # Must not raise -- a broken ledger write must never break triage/drafting.
    await record_board_model_usage(caller="board_triage", attempt_status="success", organization_id="org-1", client_id="client-1")
