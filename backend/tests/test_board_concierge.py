"""Momo Board draft concierge (Workspace Phase 4 item e5).

``generate_draft_body`` tests mirror ``test_board_triage.py``'s fake-model
pattern (monkeypatch ``create_chat_model`` where it's imported into
``deerflow.board.concierge``, no real API calls).

``run_concierge_pass`` tests drive the real ``BoardRepository`` against an
in-memory sqlite database directly (no HTTP layer, no org context -- matching
how a background loop with no request runs, see
``deerflow.runtime.user_context.resolve_organization_id``'s "work outside a
request" case) with a stubbed draft generator, proving a pass drafts every
new/triaged thread and leaves everything else alone. The module has no code
path that calls ``assert_can_approve``/``assert_can_reply`` at all, so
"never approves or replies" is locked in by asserting a drafted thread's
status stops at ``drafted``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from deerflow.board.concierge import generate_draft_body, run_concierge_pass
from deerflow.persistence.base import Base
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.board.model import BoardThreadStatus


def _make_model_env(monkeypatch, response_content):
    config = SimpleNamespace()
    fake_response = SimpleNamespace(content=response_content)

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return fake_response

    model = FakeModel()

    def _fake_create_chat_model(**kwargs):
        model.create_kwargs = kwargs
        return model

    monkeypatch.setattr("deerflow.board.concierge.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.concierge.create_chat_model", _fake_create_chat_model)
    return model


# --- generate_draft_body ---


@pytest.mark.anyio
async def test_generate_draft_body_returns_model_text(monkeypatch):
    model = _make_model_env(monkeypatch, "Thanks for flagging this -- we'll take a look and confirm shortly.")

    result = await generate_draft_body("The checkout button is broken.", subject="Broken checkout")

    assert result == "Thanks for flagging this -- we'll take a look and confirm shortly."
    assert model.kwargs["config"] == {"run_name": "board_concierge_draft"}


@pytest.mark.anyio
async def test_generate_draft_body_returns_none_on_blank_response(monkeypatch):
    _make_model_env(monkeypatch, "   ")

    result = await generate_draft_body("Hello!")

    assert result is None


@pytest.mark.anyio
async def test_generate_draft_body_returns_none_on_model_failure(monkeypatch):
    config = SimpleNamespace()
    monkeypatch.setattr("deerflow.board.concierge.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.concierge.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await generate_draft_body("A message sent while the model is unavailable.")

    assert result is None


# --- run_concierge_pass ---


@pytest_asyncio.fixture()
async def board_repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield BoardRepository(session_factory)
    await engine.dispose()


async def _stub_draft(content, **kwargs):
    return f"Draft for: {content}"


async def _no_draft(*args, **kwargs):
    return None


@pytest.mark.anyio
async def test_run_concierge_pass_drafts_new_and_triaged_threads(board_repo):
    new_thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(new_thread["id"], author_kind="client", body="It's still broken.")

    triaged_thread = await board_repo.create_thread(client_id="c1", kind="concern", subject="Pricing question")
    await board_repo.patch_thread(triaged_thread["id"], status=BoardThreadStatus.TRIAGED)
    await board_repo.add_message(triaged_thread["id"], author_kind="client", body="What does the Pro plan cost?")

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_stub_draft)

    assert set(drafted_ids) == {new_thread["id"], triaged_thread["id"]}
    for thread_id, content in ((new_thread["id"], "It's still broken."), (triaged_thread["id"], "What does the Pro plan cost?")):
        row = await board_repo.get_thread(thread_id)
        assert row["status"] == BoardThreadStatus.DRAFTED
        messages = await board_repo.list_messages(thread_id)
        assert messages[-1]["author_kind"] == "momo"
        assert messages[-1]["body"] == f"Draft for: {content}"


@pytest.mark.anyio
async def test_run_concierge_pass_never_moves_a_thread_past_drafted(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="post", subject="Hello")
    await board_repo.add_message(thread["id"], author_kind="client", body="Just saying hi!")

    await run_concierge_pass(board_repo, generate_draft=_stub_draft)

    row = await board_repo.get_thread(thread["id"])
    assert row["status"] == BoardThreadStatus.DRAFTED
    assert row["status"] not in (BoardThreadStatus.APPROVED, BoardThreadStatus.REPLIED)


@pytest.mark.anyio
async def test_run_concierge_pass_skips_threads_outside_new_or_triaged(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="post", subject="Already drafted")
    await board_repo.add_message(thread["id"], author_kind="client", body="Hi.")
    await board_repo.add_message(thread["id"], author_kind="momo", body="An existing draft.")
    await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.DRAFTED)

    # Records rather than raises: a per-thread try/except elsewhere in the
    # pass must not be able to swallow evidence that this was called for a
    # thread whose status makes it ineligible.
    calls: list[str] = []

    async def _record_call(content, **kwargs):
        calls.append(content)
        return None

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_record_call)

    assert calls == []
    assert drafted_ids == []
    row = await board_repo.get_thread(thread["id"])
    assert row["status"] == BoardThreadStatus.DRAFTED


@pytest.mark.anyio
async def test_run_concierge_pass_leaves_thread_untouched_when_draft_generation_fails(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Needs a human")
    await board_repo.add_message(thread["id"], author_kind="client", body="Complicated question.")

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_no_draft)

    assert drafted_ids == []
    row = await board_repo.get_thread(thread["id"])
    assert row["status"] == BoardThreadStatus.NEW
    messages = await board_repo.list_messages(thread["id"])
    assert len(messages) == 1


@pytest.mark.anyio
async def test_run_concierge_pass_uses_latest_client_message_as_draft_content(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="dm", subject="Hey")
    await board_repo.add_message(thread["id"], author_kind="client", body="First message.")
    await board_repo.add_message(thread["id"], author_kind="client", body="Second message.")

    seen_content = []

    async def _record_draft(content, **kwargs):
        seen_content.append(content)
        return "A reply."

    await run_concierge_pass(board_repo, generate_draft=_record_draft)

    assert seen_content == ["Second message."]


@pytest.mark.anyio
async def test_run_concierge_pass_skips_thread_with_no_client_message(board_repo, caplog):
    """A thread created with only a subject (no message posted yet) has
    nothing for the concierge to draft against.

    Records rather than raises: f80 found the previous raising stub's
    AssertionError was swallowed by the pass's own per-thread try/except, so
    the test stayed green even with the ``last_client_index is None`` guard
    deleted. Recording alone has the same blind spot -- deleting the guard
    makes ``messages[last_client_index]`` (``messages[None]``) raise
    ``TypeError`` *before* ``generate_draft`` is ever called, which the
    try/except also swallows, so ``calls == []`` stays true either way. The
    added no-warning-logged assertion is what actually distinguishes "skipped
    cleanly" from "crashed and was swallowed" -- only the latter logs.
    """
    await board_repo.create_thread(client_id="c1", kind="post", subject="Just a subject")

    calls: list[str] = []

    async def _record_call(content, **kwargs):
        calls.append(content)
        return "A draft that must never be written."

    with caplog.at_level("WARNING"):
        drafted_ids = await run_concierge_pass(board_repo, generate_draft=_record_call)

    assert calls == []
    assert drafted_ids == []
    assert not any("failed to draft" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_run_concierge_pass_does_not_duplicate_a_rejected_draft(board_repo):
    """f61: an owner PATCHes a drafted thread back to triaged (rejecting the
    draft) with no new client message -- the next pass must not add a
    second momo draft next to the rejected one."""
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")
    await board_repo.add_message(thread["id"], author_kind="momo", body="A rejected draft.")
    await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.TRIAGED)

    calls: list[str] = []

    async def _record_call(content, **kwargs):
        calls.append(content)
        return "A duplicate draft that must never be written."

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_record_call)

    assert calls == []
    assert drafted_ids == []
    messages = await board_repo.list_messages(thread["id"])
    assert len(messages) == 2
    assert not any(m["body"] == "A duplicate draft that must never be written." for m in messages)


@pytest.mark.anyio
async def test_run_concierge_pass_drafts_a_reopened_thread_against_its_follow_up(board_repo):
    """f61: a thread with an old momo draft that's since had a genuine new
    client follow-up (e.g. reopened after PATCH replied -> triaged) drafts
    against the new message, not the stale one the old draft already answers."""
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")
    await board_repo.add_message(thread["id"], author_kind="momo", body="An old draft.")
    await board_repo.add_message(thread["id"], author_kind="client", body="Still broken, any update?")

    seen_content = []

    async def _record_draft(content, **kwargs):
        seen_content.append(content)
        return "A fresh reply."

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_record_draft)

    assert seen_content == ["Still broken, any update?"]
    assert drafted_ids == [thread["id"]]


@pytest.mark.anyio
async def test_run_concierge_pass_never_stomps_a_thread_that_raced_ahead(board_repo):
    """Reproduces a real race: draft generation for one thread is slow enough
    that another actor (or another concierge pass) drafts, approves and
    replies to the same thread before this pass's write lands. The write
    must be a no-op, not a reset back to ``drafted`` with a stale draft
    appended -- the exact bug a plain ``add_message`` + unconditional
    ``patch_thread(status=DRAFTED)`` would have.
    """
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    async def _race_then_draft(content, **kwargs):
        await board_repo.add_message(thread["id"], author_kind="momo", body="A human-triggered draft.")
        await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.DRAFTED)
        await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.APPROVED)
        await board_repo.add_message(thread["id"], author_kind="owner", body="Sent reply.")
        await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.REPLIED)
        return "A stale concierge draft that must never land."

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_race_then_draft)

    assert drafted_ids == []
    row = await board_repo.get_thread(thread["id"])
    assert row["status"] == BoardThreadStatus.REPLIED
    bodies = [m["body"] for m in await board_repo.list_messages(thread["id"])]
    assert "A stale concierge draft that must never land." not in bodies


@pytest.mark.anyio
async def test_run_concierge_pass_continues_after_one_thread_raises(board_repo):
    thread_a = await board_repo.create_thread(client_id="c1", kind="post", subject="A")
    await board_repo.add_message(thread_a["id"], author_kind="client", body="Message A")
    thread_b = await board_repo.create_thread(client_id="c1", kind="post", subject="B")
    await board_repo.add_message(thread_b["id"], author_kind="client", body="Message B")

    async def _fail_for_b(content, **kwargs):
        if content == "Message B":
            raise RuntimeError("model blew up")
        return f"Draft for: {content}"

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_fail_for_b)

    assert drafted_ids == [thread_a["id"]]
    row_a = await board_repo.get_thread(thread_a["id"])
    row_b = await board_repo.get_thread(thread_b["id"])
    assert row_a["status"] == BoardThreadStatus.DRAFTED
    assert row_b["status"] == BoardThreadStatus.NEW


@pytest.mark.anyio
async def test_run_concierge_pass_records_an_audit_event_per_draft(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    recorded = []

    class _FakeAuditRepo:
        async def record(self, **kwargs):
            recorded.append(kwargs)

    await run_concierge_pass(board_repo, generate_draft=_stub_draft, audit_repo=_FakeAuditRepo())

    assert len(recorded) == 1
    assert recorded[0]["action"] == "board.thread.concierge_drafted"
    assert recorded[0]["outcome"] == "success"
    assert recorded[0]["target_id"] == thread["id"]
    assert recorded[0]["actor_user_id"] is None


@pytest.mark.anyio
async def test_run_concierge_pass_does_not_mislabel_an_audit_failure_as_a_draft_failure(board_repo, caplog):
    """f64: a failure recording the audit event (after a successful draft
    write) must not log as if the draft itself failed."""
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    class _BrokenAuditRepo:
        async def record(self, **kwargs):
            raise RuntimeError("audit db is down")

    with caplog.at_level("WARNING"):
        drafted_ids = await run_concierge_pass(board_repo, generate_draft=_stub_draft, audit_repo=_BrokenAuditRepo())

    assert drafted_ids == [thread["id"]]
    row = await board_repo.get_thread(thread["id"])
    assert row["status"] == BoardThreadStatus.DRAFTED
    assert not any("failed to draft" in record.message for record in caplog.records)
    assert any("failed to record its audit event" in record.message for record in caplog.records)


# --- run_concierge_pass: f62 per-thread backoff on repeated failure ---


@pytest.mark.anyio
async def test_run_concierge_pass_backs_off_after_a_failed_draft(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    call_count = 0

    async def _always_none(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None

    state: dict = {}
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=0.0)
    assert call_count == 1

    # Immediately retrying (no time elapsed) must not call the model again --
    # this thread is backing off after its one failure.
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=1.0)
    assert call_count == 1

    # After the backoff window elapses, it is retried.
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=10_000.0)
    assert call_count == 2


@pytest.mark.anyio
async def test_run_concierge_pass_resets_backoff_on_a_new_client_message(board_repo):
    """f79: the reset must key on a genuine new client message, not
    ``BoardThreadRow.updated_at`` -- ``BoardRepository.add_message`` never
    touches that column, so a thread in backoff would otherwise sit out a
    real new client message for up to the full backoff window.
    """
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    call_count = 0

    async def _always_none(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None

    state: dict = {}
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=0.0)
    assert call_count == 1

    # A genuine new client message retries immediately despite the backoff,
    # even though it alone leaves the thread row's own updated_at untouched.
    await board_repo.add_message(thread["id"], author_kind="client", body="Any update?")
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=1.0)
    assert call_count == 2


@pytest.mark.anyio
async def test_run_concierge_pass_backoff_survives_a_thread_row_only_change(board_repo):
    """The converse of the above: a `board_threads` row change with no new
    client message (e.g. a subject edit) must not reset the backoff --
    otherwise an unrelated patch would defeat it just as easily as the old
    ``updated_at``-keyed version did in reverse.
    """
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    call_count = 0

    async def _always_none(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None

    state: dict = {}
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=0.0)
    assert call_count == 1

    await board_repo.patch_thread(thread["id"], subject="Broken widget (edited)")
    await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=1.0)
    assert call_count == 1  # still backing off -- no new client message


@pytest.mark.anyio
async def test_run_concierge_pass_logs_once_when_giving_up_on_a_thread(board_repo, caplog):
    thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget")
    await board_repo.add_message(thread["id"], author_kind="client", body="It's broken.")

    async def _always_none(*args, **kwargs):
        return None

    state: dict = {}
    t = 0.0
    with caplog.at_level("WARNING"):
        for _ in range(6):
            await run_concierge_pass(board_repo, generate_draft=_always_none, attempt_state=state, now=t)
            t += 10_000.0  # comfortably past any backoff window between attempts

    give_up_logs = [r for r in caplog.records if "giving up" in r.message]
    assert len(give_up_logs) == 1
