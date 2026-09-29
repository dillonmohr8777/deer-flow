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
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context


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


# --- usage-ledger recording (Workspace Phase 4 item e7) ---


@pytest.mark.anyio
async def test_generate_draft_body_records_usage_on_success(monkeypatch):
    _make_model_env(monkeypatch, "Thanks -- we'll take a look.")
    calls = []

    async def _record(**kwargs):
        calls.append(kwargs)

    await generate_draft_body(
        "The checkout button is broken.",
        organization_id="org-1",
        client_id="client-1",
        board_thread_id="thread-1",
        record_usage=_record,
    )

    assert len(calls) == 1
    assert calls[0]["caller"] == "board_concierge"
    assert calls[0]["attempt_status"] == "success"
    assert calls[0]["organization_id"] == "org-1"
    assert calls[0]["client_id"] == "client-1"
    assert calls[0]["board_thread_id"] == "thread-1"
    assert calls[0]["response"] is not None


@pytest.mark.anyio
async def test_generate_draft_body_records_usage_as_success_even_on_a_blank_response(monkeypatch):
    """A blank draft is still a successful model call, not a model-call failure."""
    _make_model_env(monkeypatch, "   ")
    calls = []

    async def _record(**kwargs):
        calls.append(kwargs)

    result = await generate_draft_body("Hello!", record_usage=_record)

    assert result is None
    assert len(calls) == 1
    assert calls[0]["attempt_status"] == "success"


@pytest.mark.anyio
async def test_generate_draft_body_forwards_an_explicit_user_id_to_the_recorder(monkeypatch):
    _make_model_env(monkeypatch, "Thanks -- we'll take a look.")
    calls = []

    async def _record(**kwargs):
        calls.append(kwargs)

    await generate_draft_body("The checkout button is broken.", user_id="creator-1", record_usage=_record)

    assert calls[0]["user_id"] == "creator-1"


@pytest.mark.anyio
async def test_generate_draft_body_records_usage_as_error_when_the_model_call_fails(monkeypatch):
    config = SimpleNamespace()
    monkeypatch.setattr("deerflow.board.concierge.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.concierge.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    calls = []

    async def _record(**kwargs):
        calls.append(kwargs)

    await generate_draft_body(
        "A message sent while the model is unavailable.",
        organization_id="org-1",
        client_id="client-1",
        record_usage=_record,
    )

    assert len(calls) == 1
    assert calls[0]["attempt_status"] == "error"
    assert calls[0]["error_type"] == "RuntimeError"


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

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("generate_draft must not be called for a non-eligible thread")

    drafted_ids = await run_concierge_pass(board_repo, generate_draft=_fail_if_called)

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
async def test_run_concierge_pass_forwards_thread_org_client_and_creator_to_draft_generation(board_repo):
    # A real storage context, not no-context: organization_id must land as an
    # actual, non-None org id (a prior version of this test compared None == None,
    # which stayed green even with organization_id hard-coded to None in
    # concierge.py -- see review follow-up on PR #67).
    org_id = private_organization_id("creator-1")
    token = set_storage_context(WorkspaceStorageContext(actor_user_id="creator-1", organization_id=org_id, storage_user_id="creator-1"))
    try:
        thread = await board_repo.create_thread(client_id="c1", kind="ticket", subject="Broken widget", created_by_user_id="creator-1")
    finally:
        reset_storage_context(token)
    assert thread["organization_id"] == org_id  # sanity check the fixture actually exercises a real org
    await board_repo.add_message(thread["id"], author_kind="client", body="It's still broken.")

    seen_kwargs = []

    async def _record_kwargs(content, **kwargs):
        seen_kwargs.append(kwargs)
        return "A reply."

    await run_concierge_pass(board_repo, generate_draft=_record_kwargs)

    assert len(seen_kwargs) == 1
    assert seen_kwargs[0]["client_id"] == "c1"
    assert seen_kwargs[0]["board_thread_id"] == thread["id"]
    assert seen_kwargs[0]["organization_id"] == org_id
    assert seen_kwargs[0]["user_id"] == "creator-1"


@pytest.mark.anyio
async def test_run_concierge_pass_uses_first_message_as_draft_content(board_repo):
    thread = await board_repo.create_thread(client_id="c1", kind="dm", subject="Hey")
    await board_repo.add_message(thread["id"], author_kind="client", body="First message.")
    await board_repo.add_message(thread["id"], author_kind="client", body="Second message.")

    seen_content = []

    async def _record_draft(content, **kwargs):
        seen_content.append(content)
        return "A reply."

    await run_concierge_pass(board_repo, generate_draft=_record_draft)

    assert seen_content == ["First message."]
