"""Offline lifecycle/security tests: no credentials or provider networking."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway import openai_agent_service as agent_service
from app.gateway.openai_agent_service import AgentServiceError, OpenAIAgentService


class FakePage:
    def __init__(self, data):
        self.data = data

    def has_next_page(self):
        return False


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
    with pytest.raises(AgentServiceError, match="artifact_size_unavailable_or_exceeded"):
        await service.artifact("alice", row["id"], "artifact1")
    client.beta.agents.sessions.artifacts.content.assert_not_awaited()


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
