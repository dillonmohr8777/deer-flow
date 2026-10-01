"""Offline lifecycle/security tests: no credentials or provider networking."""

import asyncio
import contextlib
import logging
import sqlite3
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APIStatusError

from app.gateway import openai_agent_service as agent_service
from app.gateway.openai_agent_service import AgentServiceError, OpenAIAgentService


def _api_status_error(status_code: int) -> APIStatusError:
    response = httpx.Response(status_code, request=httpx.Request("POST", "https://api.openai.com/v1/agents/sessions"))
    return APIStatusError("rejected", response=response, body=None)


class FakePage:
    def __init__(self, data):
        self.data = data

    def has_next_page(self):
        return False


class EndlessEmptyPage:
    """A provider list page that never completes: always another page, no matches.

    Exercises the `not more` guard on the stale-settle path: a search that is
    truncated at MAX_PAGES has not actually confirmed zero matches.
    """

    data: list = []

    def has_next_page(self):
        return True

    async def get_next_page(self):
        return self


class FakeClient:
    def __init__(self):
        self.turns = []
        self.items = []
        self.artifacts = []
        self.session = {"id": "sess_remote", "status": "idle", "required_actions": [], "usage": None}
        sessions = SimpleNamespace(
            create=AsyncMock(side_effect=lambda **kwargs: self.session),
            retrieve=AsyncMock(side_effect=lambda *args: self.session),
            list=AsyncMock(side_effect=lambda **kwargs: FakePage([self.session])),
            delete=AsyncMock(),
            turns=SimpleNamespace(list=AsyncMock(side_effect=lambda *args, **kwargs: FakePage(self.turns))),
            items=SimpleNamespace(list=AsyncMock(side_effect=lambda *args, **kwargs: FakePage(self.items))),
            artifacts=SimpleNamespace(list=AsyncMock(side_effect=lambda *args, **kwargs: FakePage(self.artifacts)), retrieve=AsyncMock(), content=AsyncMock()),
            events=SimpleNamespace(create=AsyncMock()),
        )
        self.beta = SimpleNamespace(agents=SimpleNamespace(sessions=sessions))


@pytest.fixture
def setup(tmp_path):
    client = FakeClient()
    service = OpenAIAgentService(tmp_path / "agents.sqlite", client_factory=lambda: client)
    return service, client


@pytest.mark.asyncio
async def test_create_is_private_durable_and_network_disabled(setup):
    service, client = setup
    result = await service.create("alice-org", "Compute 2+2", "My task", "create1")
    kwargs = client.beta.agents.sessions.create.call_args.kwargs
    assert kwargs["agent"]["model"] == "gpt-6.1-sol"
    assert kwargs["agent"]["multi_agent"]["max_concurrent_subagents"] == 3
    assert kwargs["environment"]["network"] == {"access": "disabled"}
    assert kwargs["agent"]["tools"] == []
    assert result["status"] == "idle" and result["turn"] is None
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    assert (await restarted.list_sessions("alice-org"))[0]["id"] == result["id"]
    assert await restarted.list_sessions("bob-org") == []
    with pytest.raises(AgentServiceError, match="not_found"):
        await restarted.snapshot("bob-org", result["id"])


@pytest.mark.asyncio
async def test_creation_idempotency_does_not_double_dispatch(setup):
    service, client = setup
    first = await service.create("alice", "Task", "Task", "same")
    second = await service.create("alice", "Task", "Task", "same")
    assert first["id"] == second["id"]
    assert client.beta.agents.sessions.create.await_count == 1
    with pytest.raises(AgentServiceError, match="idempotency_conflict"):
        await service.create("alice", "Changed task", "Task", "same")


@pytest.mark.asyncio
async def test_unknown_creation_is_not_retried_and_errors_are_redacted(setup):
    service, client = setup
    client.beta.agents.sessions.create.side_effect = RuntimeError("sk-secret private request body")
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown") as error:
        await service.create("alice", "Task", "Task", "same")
    assert "sk-secret" not in str(error.value)
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "unknown"
    client.session["metadata"] = {}
    await service.create("alice", "Task", "Task", "same")
    assert client.beta.agents.sessions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 429])
async def test_definite_4xx_create_rejection_settles_failed_and_frees_the_slot(setup, status_code):
    service, client = setup
    original_side_effect = client.beta.agents.sessions.create.side_effect
    client.beta.agents.sessions.create.side_effect = _api_status_error(status_code)
    with pytest.raises(AgentServiceError, match="provider_rejected_request") as error:
        await service.create("alice", "Task", "Task", "rejected")
    assert error.value.status_code == 422
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "failed"
    # A confirmed, never-dispatched create must not permanently occupy an
    # active-session slot: all MAX_ACTIVE_SESSIONS real sessions still fit.
    client.beta.agents.sessions.create.side_effect = original_side_effect
    for index in range(agent_service.MAX_ACTIVE_SESSIONS):
        client.session.update(id=f"ok_{index}", status="in_progress")
        await service.create("alice", "Task", "Task", f"ok_{index}")
    with pytest.raises(AgentServiceError, match="active_session_limit"):
        await service.create("alice", "Task", "Task", "overflow")
    assert client.beta.agents.sessions.list.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 409])
async def test_ambiguous_4xx_create_rejection_stays_unknown(setup, status_code):
    service, client = setup
    client.beta.agents.sessions.create.side_effect = _api_status_error(status_code)
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create("alice", "Task", "Task", "ambiguous")
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_stale_unbound_creates_settle_failed_and_stop_relisting(setup):
    service, client = setup
    original_side_effect = client.beta.agents.sessions.create.side_effect
    client.beta.agents.sessions.list.side_effect = lambda **kwargs: FakePage([])
    client.beta.agents.sessions.create.side_effect = RuntimeError("provider response lost")
    for index in range(3):
        with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
            await service.create("alice", "Task", "Task", f"lost_{index}")
    stale_created_at = datetime.fromtimestamp(time.time() - agent_service.TURN_TIMEOUT_SECONDS - agent_service.UNBOUND_RESOLUTION_MARGIN_SECONDS - 10, UTC).isoformat()
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE sessions SET created_at=?", (stale_created_at,))
        db.execute("UPDATE deadlines SET expires_at=0")
    await service.enforce_deadlines()
    rows = await service.list_sessions("alice")
    assert len(rows) == 3
    assert all(row["status"] == "failed" for row in rows)
    assert client.beta.agents.sessions.list.await_count == 3
    # Settled rows drop out of the unbound-due scan: no further relisting.
    await service.enforce_deadlines()
    assert client.beta.agents.sessions.list.await_count == 3
    # The three failed creates no longer occupy active-session slots.
    client.beta.agents.sessions.create.side_effect = original_side_effect
    await service.create("alice", "Task", "Task", "finally_ok")
    assert client.beta.agents.sessions.create.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_5xx_create_rejection_stays_unknown(setup, status_code):
    # Guards the `< 500` boundary in _is_definite_create_rejection: a 5xx means
    # the provider may have processed the request, so it must stay ambiguous,
    # never a confirmed "failed" (which would risk masking a billable session).
    service, client = setup
    client.beta.agents.sessions.create.side_effect = _api_status_error(status_code)
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create("alice", "Task", "Task", "servererror")
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_stale_unbound_create_with_truncated_search_stays_unknown(setup):
    # Guards the `not more` condition in snapshot()'s stale-settle branch: a
    # search truncated at MAX_PAGES has not confirmed zero matches, so even a
    # very stale row must stay ambiguous instead of settling "failed" (which
    # would orphan a session that exists past page MAX_PAGES).
    service, client = setup
    client.beta.agents.sessions.create.side_effect = RuntimeError("provider response lost")
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create("alice", "Task", "Task", "lost")
    client.beta.agents.sessions.list.side_effect = lambda **kwargs: EndlessEmptyPage()
    stale_created_at = datetime.fromtimestamp(time.time() - agent_service.TURN_TIMEOUT_SECONDS - agent_service.UNBOUND_RESOLUTION_MARGIN_SECONDS - 10, UTC).isoformat()
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE sessions SET created_at=?", (stale_created_at,))
        db.execute("UPDATE deadlines SET expires_at=0")
    await service.enforce_deadlines()
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_failed_unbound_row_is_not_relisted_or_resurrected_by_a_late_match(setup):
    # A row already dead-lettered "failed" must stay that way even if a
    # matching provider session shows up later (list-endpoint lag): re-listing
    # and binding it would resurrect a row the watchdog has already stopped
    # watching (its deadline is "settled"), leaking an unsupervised session.
    service, client = setup
    client.beta.agents.sessions.create.side_effect = _api_status_error(400)
    with pytest.raises(AgentServiceError, match="provider_rejected_request"):
        await service.create("alice", "Task", "Task", "rejected")
    session_id = (await service.list_sessions("alice"))[0]["id"]
    client.session.update(id="late_arrival", status="in_progress", metadata={"momo_local_session": session_id, "momo_owner_scope": agent_service._hash("alice")})
    result = await service.snapshot("alice", session_id)
    assert result["status"] == "failed"
    assert client.beta.agents.sessions.list.await_count == 0
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_slow_create_landing_after_dead_letter_is_cancelled_not_orphaned(setup):
    # A create() whose sessions.create() call is slow enough that the
    # watchdog dead-letters the row (provider_id still NULL) before it
    # returns must not leave the real, now-billable session untracked once
    # it finally lands: the guarded "bind" silently no-ops, so the caller
    # must reconcile (here: cancel it) instead of just dropping the result.
    service, client = setup
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_create(**kwargs):
        entered.set()
        await release.wait()
        return client.session

    client.beta.agents.sessions.create.side_effect = slow_create
    client.beta.agents.sessions.list.side_effect = lambda **kwargs: FakePage([])
    pending = asyncio.create_task(service.create("alice", "Task", "Task", "slow"))
    await entered.wait()

    session_id = (await service.list_sessions("alice"))[0]["id"]
    stale_created_at = datetime.fromtimestamp(time.time() - agent_service.TURN_TIMEOUT_SECONDS - agent_service.UNBOUND_RESOLUTION_MARGIN_SECONDS - 10, UTC).isoformat()
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE sessions SET created_at=?", (stale_created_at,))
        db.execute("UPDATE deadlines SET expires_at=0")
    await service.enforce_deadlines()
    assert (await service.list_sessions("alice"))[0]["status"] == "failed"

    release.set()
    await pending

    # The late-landing real session must be reconciled (cancelled, here,
    # since the fake client's delete always succeeds), never silently lost.
    client.beta.agents.sessions.delete.assert_awaited_once_with("sess_remote")
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "failed"
    assert rows[0]["id"] == session_id


@pytest.mark.asyncio
async def test_fail_unbound_does_not_settle_deadline_of_a_row_already_bound(setup):
    # If a concurrent bind wins the race first (row is live, provider-bound),
    # a losing fail_unbound call must not settle its deadline -- otherwise a
    # session that is genuinely still running loses watchdog coverage for
    # good (its deadline state never matches the "due" query again).
    service, client = setup
    client.turns = [{"id": "root", "status": "in_progress", "subagent_id": None}]
    client.session["status"] = "in_progress"
    row = await service.create("alice", "Task", "Task", "create")
    assert row["status"] == "in_progress"
    await service._storage("fail_unbound", row["id"], "alice", "provider_create_not_found")
    with sqlite3.connect(service.path) as db:
        deadline_state = db.execute("SELECT state FROM deadlines WHERE session_id=?", (row["id"],)).fetchone()[0]
    assert deadline_state == "waiting"
    rows = await service.list_sessions("alice")
    assert rows[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_terminal_child_turn_cannot_mark_root_done(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "a")
    client.turns = [{"id": "child", "status": "completed", "subagent_id": "worker"}, {"id": "root", "status": "in_progress", "subagent_id": None}]
    client.items = [{"id": "msg", "type": "message", "turn_id": "child", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "Child done"}]}]
    result = await service.snapshot("alice", row["id"])
    assert result["turn"]["id"] == "root"
    assert result["turn"]["output_verified"] is False
    client.turns = [{"id": "root", "status": "completed", "subagent_id": None}]
    assert (await service.snapshot("alice", row["id"]))["turn"]["output_verified"] is False
    client.items.append({"id": "answer", "type": "message", "turn_id": "root", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "Actual answer"}]})
    assert (await service.snapshot("alice", row["id"]))["turn"]["output_verified"] is True


@pytest.mark.asyncio
async def test_message_admission_is_atomic_and_transport_receipt_is_not_completion(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "create")
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(*args, **kwargs):
        entered.set()
        await release.wait()

    client.beta.agents.sessions.events.create.side_effect = send
    pending = asyncio.create_task(service.message("alice", row["id"], "Next", "m1"))
    await entered.wait()
    with pytest.raises(AgentServiceError, match="operation_pending"):
        await service.message("alice", row["id"], "Other", "m2")
    release.set()
    result = await pending
    assert result["operation_pending"] is True
    assert client.beta.agents.sessions.events.create.await_count == 1
    await service.message("alice", row["id"], "Next", "m1")
    assert client.beta.agents.sessions.events.create.await_count == 1
    client.turns = [{"id": "new_root", "status": "completed", "subagent_id": None}]
    assert (await service.snapshot("alice", row["id"]))["operation_pending"] is False


@pytest.mark.asyncio
async def test_failed_turn_and_provider_read_failure_remain_truthful(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    client.turns = [{"id": "root", "status": "failed", "subagent_id": None}]
    result = await service.snapshot("alice", row["id"])
    assert result["turn"]["status"] == "failed" and not result["turn"]["output_verified"]
    client.beta.agents.sessions.retrieve.side_effect = RuntimeError("Authorization: sk-secret")
    with pytest.raises(AgentServiceError, match="provider_read_failed") as error:
        await service.snapshot("alice", row["id"])
    assert "sk-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_local_bind_failure_attempts_remote_cleanup(setup, monkeypatch):
    service, client = setup
    original = service._db

    def broken(action, *args):
        if action == "bind":
            raise OSError("disk full")
        return original(action, *args)

    monkeypatch.setattr(service, "_db", broken)
    with pytest.raises(AgentServiceError, match="local_persistence_failed"):
        await service.create("alice", "Task", "Task", "c")
    client.beta.agents.sessions.delete.assert_awaited_once_with("sess_remote")


@pytest.mark.asyncio
async def test_artifact_download_checks_session_owner_first(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    with pytest.raises(AgentServiceError, match="not_found"):
        await service.artifact("bob", row["id"], "artifact1")
    assert client.beta.agents.sessions.artifacts.retrieve.await_count == 0


@pytest.mark.asyncio
async def test_cancel_is_not_claimed_from_http_acceptance(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    client.turns = [{"id": "root", "status": "in_progress", "subagent_id": None}]
    client.session["status"] = "in_progress"
    result = await service.cancel("alice", row["id"])
    assert result["turn"]["status"] == "in_progress" and result["operation_pending"]
    client.turns[0]["status"] = "cancelled"
    client.session["status"] = "idle"
    result = await service.snapshot("alice", row["id"])
    assert not result["operation_pending"] and not result["turn"]["output_verified"]


@pytest.mark.asyncio
async def test_same_message_retry_while_turn_active_is_a_read(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    await service.message("alice", row["id"], "Next", "m")
    client.turns = [{"id": "root2", "status": "in_progress", "subagent_id": None}]
    client.session["status"] = "in_progress"
    result = await service.message("alice", row["id"], "Next", "m")
    assert result["turn"]["status"] == "in_progress"
    assert client.beta.agents.sessions.events.create.await_count == 1


@pytest.mark.asyncio
async def test_cancelled_create_retains_unknown_admission_without_retry(setup):
    service, client = setup
    client.beta.agents.sessions.create.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.create("alice", "Task", "Task", "c")
    assert (await service.list_sessions("alice"))[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_streaming_artifact_rejects_oversize_before_body_read(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    client.beta.agents.sessions.artifacts.retrieve.return_value = {"size_bytes": 30 * 1024 * 1024}
    content = Mock(side_effect=AssertionError("Oversized metadata must prevent opening the stream"))
    client.beta.agents.sessions.artifacts.with_streaming_response = SimpleNamespace(content=content)
    with pytest.raises(AgentServiceError, match="artifact_size_unavailable_or_exceeded"):
        await service.artifact("alice", row["id"], "artifact1")
    content.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size,chunks,expected",
    [(3, [b"a"], None), (1, [b"a", b"bc"], None), (0, [], b""), (3, [b"a", b"bc"], b"abc")],
    ids=["truncated", "excess-within-limit", "empty", "exact-multiple-chunks"],
)
async def test_artifact_eof_matches_metadata_and_always_closes_stream(setup, size, chunks, expected):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    artifacts = client.beta.agents.sessions.artifacts
    artifacts.retrieve.return_value = {"size_bytes": size}
    state = {"entered": 0, "closed": 0, "read": 0, "eof": False, "exit_error": None}

    class Stream:
        async def iter_bytes(self, chunk_size):
            assert chunk_size == 65536
            for chunk in chunks:
                state["read"] += len(chunk)
                yield chunk
            state["eof"] = True

    class Context:
        async def __aenter__(self):
            state["entered"] += 1
            return Stream()

        async def __aexit__(self, error_type, _error, _traceback):
            state["closed"] += 1
            state["exit_error"] = error_type

    content = Mock(return_value=Context())
    artifacts.with_streaming_response = SimpleNamespace(content=content)
    if expected is None:
        with pytest.raises(AgentServiceError, match="artifact_read_failed") as error:
            await service.artifact("alice", row["id"], "artifact1")
        assert error.value.status_code == 502
    else:
        assert await service.artifact("alice", row["id"], "artifact1") == expected
    artifacts.retrieve.assert_awaited_once_with("artifact1", session_id="sess_remote")
    content.assert_called_once_with("artifact1", session_id="sess_remote")
    assert state == {"entered": 1, "closed": 1, "read": sum(map(len, chunks)), "eof": True, "exit_error": None}


@pytest.mark.asyncio
async def test_artifact_stream_limit_catches_false_size_metadata(setup, monkeypatch):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    client.beta.agents.sessions.artifacts.retrieve.return_value = {"size_bytes": 1}
    state = {"closed": False, "reads": 0}

    class Stream:
        async def iter_bytes(self, chunk_size=65536):
            for _ in range(5):
                state["reads"] += 1
                yield b"abcd"

    class Context:
        async def __aenter__(self):
            return Stream()

        async def __aexit__(self, *args):
            state["closed"] = True

    client.beta.agents.sessions.artifacts.with_streaming_response = SimpleNamespace(content=lambda *args, **kwargs: Context())
    monkeypatch.setattr("app.gateway.openai_agent_service.MAX_ARTIFACT_BYTES", 6)
    with pytest.raises(AgentServiceError, match="artifact_size_unavailable_or_exceeded"):
        await service.artifact("alice", row["id"], "artifact1")
    assert state == {"closed": True, "reads": 2}


@pytest.mark.asyncio
async def test_durable_deadline_survives_service_restart_and_cancel_is_one_attempt(setup):
    service, client = setup
    await service.create("alice", "Task", "Task", "c")
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET expires_at=0")
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    await restarted.enforce_deadlines()
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 1
    assert client.beta.agents.sessions.events.create.call_args.kwargs["events"] == [{"type": "agent.session.input.cancel"}]


@pytest.mark.asyncio
async def test_cancel_does_not_pretend_unobserved_submission_is_stopped(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "c")
    await service.message("alice", row["id"], "Next", "m")
    with pytest.raises(AgentServiceError, match="operation_pending"):
        await service.cancel("alice", row["id"])
    assert client.beta.agents.sessions.events.create.await_count == 1


@pytest.mark.asyncio
async def test_completed_history_does_not_consume_active_session_slots(setup):
    service, client = setup
    for index in range(5):
        client.session["id"] = f"remote_{index}"
        client.turns = [{"id": f"turn_{index}", "status": "completed", "subagent_id": None}]
        await service.create("alice", "Task", "Task", f"create_{index}")
    assert len(await service.list_sessions("alice")) == 5
    assert client.beta.agents.sessions.create.await_count == 5


@pytest.mark.asyncio
async def test_uncertain_and_required_action_sessions_consume_active_slots(setup):
    service, client = setup
    for index, status in enumerate(("in_progress", "requires_action", "unknown")):
        client.session.update(id=f"remote_{index}", status=status)
        await service.create("alice", "Task", "Task", f"create_{index}")
    with pytest.raises(AgentServiceError, match="active_session_limit"):
        await service.create("alice", "Task", "Task", "overflow")
    assert client.beta.agents.sessions.create.await_count == 3


@pytest.mark.asyncio
async def test_owner_daily_admission_cap_counts_paid_work_but_not_retries_or_cancel(setup, monkeypatch):
    service, client = setup
    monkeypatch.setattr(agent_service, "MAX_OWNER_ADMISSIONS_24H", 2, raising=False)
    row = await service.create("alice", "Task", "Task", "create")
    await service.message("alice", row["id"], "Next", "m1")
    client.turns = [{"id": "root", "status": "in_progress", "subagent_id": None}]
    client.session["status"] = "in_progress"
    await service.message("alice", row["id"], "Next", "m1")
    await service.cancel("alice", row["id"])
    client.turns[0]["status"] = "cancelled"
    client.session["status"] = "idle"
    await service.snapshot("alice", row["id"])
    with pytest.raises(AgentServiceError, match="owner_admission_limit"):
        await service.message("alice", row["id"], "Extra", "m2")
    with pytest.raises(AgentServiceError, match="owner_admission_limit"):
        await service.create("alice", "Task", "Task", "second_create")
    assert client.beta.agents.sessions.create.await_count == 1
    assert client.beta.agents.sessions.events.create.await_count == 2
    # Another identity scope and admissions older than 24 hours remain usable.
    client.session["id"] = "remote_bob"
    await service.create("bob", "Task", "Task", "bob_create")
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE events SET created_at='2000-01-01T00:00:00+00:00' WHERE session_id=?", (row["id"],))
    await service.message("alice", row["id"], "New day", "m3")
    assert client.beta.agents.sessions.events.create.await_count == 3


@pytest.mark.asyncio
async def test_watchdog_reclaims_crashed_claim_and_reuses_provider_idempotency(setup):
    service, client = setup
    await service.create("alice", "Task", "Task", "create")
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET expires_at=0")
    assert len(await service._storage("due")) == 1
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 0
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET lease_expires_at=0")
    await restarted.enforce_deadlines()
    first_key = client.beta.agents.sessions.events.create.call_args.kwargs["idempotency_key"]
    # An accepted cancellation without observed terminal turn is still uncertain.
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET lease_expires_at=0")
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 2
    assert client.beta.agents.sessions.events.create.call_args.kwargs["idempotency_key"] == first_key


@pytest.mark.asyncio
async def test_claimed_watchdog_fences_new_turn_until_outbound_cancel_settles(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "create")
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET expires_at=0")
    claimed = (await service._storage("due"))[0]
    client.turns = [{"id": "root", "status": "completed", "subagent_id": None}]
    assert (await service.snapshot("alice", row["id"]))["operation_pending"]
    with pytest.raises(AgentServiceError, match="operation_pending"):
        await service.message("alice", row["id"], "New task", "m")
    assert client.beta.agents.sessions.events.create.await_count == 0
    await service._storage("deadline_sent", row["id"], "alice", claimed["expires_at"], claimed["lease_expires_at"])
    assert not (await service.snapshot("alice", row["id"]))["operation_pending"]
    await service.message("alice", row["id"], "New task", "m")
    assert client.beta.agents.sessions.events.create.await_count == 1


@pytest.mark.asyncio
async def test_delegations_preserve_real_participants_and_commentary_is_not_final(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "create")
    client.turns = [{"id": "root_turn", "status": "completed", "subagent_id": None}]
    client.items = [
        {"id": "comment", "type": "message", "turn_id": "root_turn", "role": "assistant", "phase": "commentary", "content": [{"type": "output_text", "text": "Working on it"}]},
        {"id": "delegate", "type": "create_subagent_call", "turn_id": "root_turn", "agent_id": "root", "content": [{"type": "input_text", "text": "Check the evidence"}]},
        {"id": "prompt", "type": "agent_message", "turn_id": "root_turn", "sender_agent_id": "root", "recipient_agent_id": "subagent_verified", "content": [{"type": "input_text", "text": "Check the evidence"}]},
        {"id": "reply", "type": "agent_message", "turn_id": "root_turn", "sender_agent_id": "subagent_verified", "recipient_agent_id": "root", "content": [{"type": "output_text", "text": "Evidence checked"}]},
    ]
    result = await service.snapshot("alice", row["id"])
    assert not result["turn"]["output_verified"]
    items = {item["id"]: item for item in result["items"]}
    assert items["comment"]["phase"] == "commentary"
    assert items["delegate"]["agent_id"] == "root" and items["delegate"]["text"] == "Check the evidence"
    assert items["prompt"]["subagent_id"] == "subagent_verified"
    assert items["reply"]["subagent_id"] == "subagent_verified"
    assert items["reply"]["sender_agent_id"] == "subagent_verified" and items["reply"]["recipient_agent_id"] == "root"


@pytest.mark.asyncio
async def test_watchdog_uncertain_cancel_retries_only_after_lease_and_observes_terminal(setup):
    service, client = setup
    row = await service.create("alice", "Task", "Task", "create")
    client.turns = [{"id": "root", "status": "in_progress", "subagent_id": None}]
    client.session["status"] = "in_progress"
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET expires_at=0")
    client.beta.agents.sessions.events.create.side_effect = RuntimeError("private provider details")
    await service.enforce_deadlines()
    first_key = client.beta.agents.sessions.events.create.call_args.kwargs["idempotency_key"]
    assert (await service.list_sessions("alice"))[0]["last_error"] == "deadline_cancel_outcome_unknown"
    await service.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 1
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET lease_expires_at=0")
    client.beta.agents.sessions.events.create.side_effect = None
    client.turns[0]["status"] = "cancelled"
    client.session["status"] = "idle"
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    await restarted.enforce_deadlines()
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 2
    assert client.beta.agents.sessions.events.create.call_args.kwargs["idempotency_key"] == first_key
    result = await restarted.snapshot("alice", row["id"])
    assert result["turn"]["status"] == "cancelled" and not result["operation_pending"]
    assert result["last_error"] is None


@pytest.mark.asyncio
async def test_watchdog_migrates_legacy_claim_without_lease(setup):
    service, client = setup
    # Existing installations have the original three-column deadline schema.
    service.path.touch(mode=0o600)
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TABLE deadlines(session_id TEXT PRIMARY KEY,expires_at REAL NOT NULL,state TEXT NOT NULL)")
    await service.create("alice", "Task", "Task", "create")
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET state='claimed',expires_at=0,lease_expires_at=NULL")
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.events.create.await_count == 1


@pytest.mark.asyncio
async def test_unknown_paid_admission_consumes_owner_cap_even_after_new_session_key(setup, monkeypatch):
    service, client = setup
    monkeypatch.setattr(agent_service, "MAX_OWNER_ADMISSIONS_24H", 1)
    client.beta.agents.sessions.create.side_effect = RuntimeError("provider response lost")
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create("alice", "Task", "Task", "first")
    with pytest.raises(AgentServiceError, match="owner_admission_limit"):
        await service.create("alice", "Task", "Task", "replacement_key")
    assert client.beta.agents.sessions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("matching_owner", [True, False])
async def test_watchdog_resolves_unknown_create_only_by_exact_private_metadata(setup, matching_owner):
    service, client = setup
    client.beta.agents.sessions.create.side_effect = RuntimeError("create response lost")
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create("alice", "Task", "Task", "create")
    metadata = client.beta.agents.sessions.create.call_args.kwargs["metadata"].copy()
    if not matching_owner:
        metadata["momo_owner_scope"] = "other_owner"
    client.session.update(status="in_progress", metadata=metadata)
    client.turns = [{"id": "root", "status": "in_progress", "subagent_id": None}]
    with sqlite3.connect(service.path) as db:
        db.execute("UPDATE deadlines SET expires_at=0")
    restarted = OpenAIAgentService(service.path, client_factory=lambda: client)
    await restarted.enforce_deadlines()
    assert client.beta.agents.sessions.create.await_count == 1
    assert client.beta.agents.sessions.events.create.await_count == int(matching_owner)
    if matching_owner:
        client.beta.agents.sessions.events.create.assert_awaited_once_with("sess_remote", events=[{"type": "agent.session.input.cancel"}], idempotency_key=client.beta.agents.sessions.events.create.call_args.kwargs["idempotency_key"])
    else:
        assert (await restarted.list_sessions("alice"))[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_owner_cap_is_atomic_across_two_gateway_instances(setup, monkeypatch):
    service, client = setup
    monkeypatch.setattr(agent_service, "MAX_OWNER_ADMISSIONS_24H", 2)
    remote_sessions = {}

    def create(**kwargs):
        provider_id = f"provider_{len(remote_sessions)}"
        remote = {"id": provider_id, "status": "in_progress", "usage": None, "required_actions": []}
        remote_sessions[provider_id] = remote
        return remote

    client.beta.agents.sessions.create.side_effect = create
    client.beta.agents.sessions.retrieve.side_effect = lambda provider_id: remote_sessions[provider_id]
    peer = OpenAIAgentService(service.path, client_factory=lambda: client)
    results = await asyncio.gather(
        service.create("alice", "Task one", "Task", "one"),
        peer.create("alice", "Task two", "Task", "two"),
        service.create("alice", "Task three", "Task", "three"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 2
    errors = [result for result in results if isinstance(result, AgentServiceError)]
    assert len(errors) == 1 and errors[0].code == "owner_admission_limit"
    assert client.beta.agents.sessions.create.await_count == 2


def test_watchdog_clock_defaults_to_monotonic(setup):
    service, client = setup
    assert service._clock is time.monotonic


@pytest.mark.asyncio
async def test_watchdog_logs_one_throttled_warning_with_error_code_only(setup, monkeypatch, caplog):
    service, client = setup

    async def boom():
        raise AgentServiceError("unsafe_storage", 503)

    monkeypatch.setattr(service, "enforce_deadlines", boom)
    monkeypatch.setattr(service, "_clock", lambda: 0.0)
    with caplog.at_level(logging.WARNING, logger=agent_service.__name__):
        last_warning = await service._watch_deadlines_iteration(float("-inf"))
        # A second failure inside the throttle window logs nothing further.
        last_warning = await service._watch_deadlines_iteration(last_warning)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "unsafe_storage" in warnings[0].getMessage()
    assert last_warning == 0.0


@pytest.mark.asyncio
async def test_watchdog_warning_throttle_window_expires(setup, monkeypatch, caplog):
    service, client = setup
    fake_now = {"t": 0.0}

    async def boom():
        raise AgentServiceError("unsafe_storage", 503)

    monkeypatch.setattr(service, "enforce_deadlines", boom)
    monkeypatch.setattr(service, "_clock", lambda: fake_now["t"])
    with caplog.at_level(logging.WARNING, logger=agent_service.__name__):
        last_warning = await service._watch_deadlines_iteration(float("-inf"))
        fake_now["t"] = agent_service.WATCHDOG_WARNING_THROTTLE_SECONDS - 1
        last_warning = await service._watch_deadlines_iteration(last_warning)
        fake_now["t"] = agent_service.WATCHDOG_WARNING_THROTTLE_SECONDS + 1
        last_warning = await service._watch_deadlines_iteration(last_warning)
        # Elapsed time exactly equal to the throttle window must still log:
        # the comparison is strictly `<`, not `<=`.
        fake_now["t"] = last_warning + agent_service.WATCHDOG_WARNING_THROTTLE_SECONDS
        last_warning = await service._watch_deadlines_iteration(last_warning)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    # t=0, t=THROTTLE+1, and the exact-boundary call should log; the one
    # still inside the window (t=THROTTLE-1) must not.
    assert len(warnings) == 3
    assert last_warning == 2 * agent_service.WATCHDOG_WARNING_THROTTLE_SECONDS + 1


@pytest.mark.asyncio
async def test_watchdog_loop_persists_throttle_state_across_iterations(setup, monkeypatch, caplog):
    """A regression against discarding _watch_deadlines_iteration's return value,
    which would reset the throttle every 5s and log on every scan forever."""
    service, client = setup

    async def boom():
        raise AgentServiceError("unsafe_storage", 503)

    monkeypatch.setattr(service, "enforce_deadlines", boom)
    # Pin the clock: real time.monotonic() counts from boot, so on a runner up
    # for less than the throttle window this test would pass even if the loop's
    # initial last_warning started at 0.0 instead of -inf (both would then look
    # "recent" against a small elapsed monotonic value).
    monkeypatch.setattr(service, "_clock", lambda: 0.0)
    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(agent_service.asyncio, "sleep", fast_sleep)

    with caplog.at_level(logging.WARNING, logger=agent_service.__name__):
        task = asyncio.create_task(service._watch_deadlines())
        await real_sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_watchdog_warning_never_carries_provider_exception_text(setup, monkeypatch, caplog):
    service, client = setup

    async def boom():
        raise RuntimeError("sk-secret upstream provider response body")

    monkeypatch.setattr(service, "enforce_deadlines", boom)
    with caplog.at_level(logging.WARNING, logger=agent_service.__name__):
        await service._watch_deadlines_iteration(float("-inf"))

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].exc_info is None
    assert "sk-secret" not in warnings[0].getMessage()
    assert "sk-secret" not in caplog.text
    assert "watchdog_scan_failed" in warnings[0].getMessage()
