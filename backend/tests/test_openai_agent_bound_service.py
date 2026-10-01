"""Offline integration of work provenance with the existing session ledger."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.openai_agent_service import AgentServiceError, OpenAIAgentService
from app.gateway.openai_agent_work_binding import CanonicalWorkBinding, prepare_bound_input

OWNER = "a" * 64


class Page:
    def __init__(self, data):
        self.data = data

    def has_next_page(self):
        return False


@pytest.fixture
def bound_setup(tmp_path):
    source = b"Synthetic public source for a local draft."
    checked_at = datetime.now(UTC)
    binding = CanonicalWorkBinding(
        execution_id="direct-fixture-1",
        owner_scope=OWNER,
        canonical_source_commit="b" * 40,
        manifest_sha256="c" * 64,
        graph_locator="state/graphs/fixture.json",
        graph_sha256="d" * 64,
        graph_run_id="graph-fixture",
        graph_revision=1,
        validation_sha256="e" * 64,
        validation_checked_at=checked_at.isoformat(),
        validation_expires_at=(checked_at + timedelta(minutes=5)).isoformat(),
        queue_revision=1,
        queue_sha256="f" * 64,
        work_item_id="wi-fixture",
        work_item_version=1,
        work_item_content_sha256="1" * 64,
        client_id="fixture-client",
        source_locator="clients/fixture-client/source.md",
        source_sha256=hashlib.sha256(source).hexdigest(),
        source=source,
        title="Synthetic draft",
        task="Prepare a sourced draft",
        acceptance_criteria=("State unavailable metrics",),
        artifact_locator="clients/fixture-client/deliverables/draft.bin",
    )
    remote = {"id": "sess_remote", "status": "idle", "required_actions": [], "usage": None}
    sessions = SimpleNamespace(
        create=AsyncMock(return_value=remote),
        retrieve=AsyncMock(return_value=remote),
        list=AsyncMock(return_value=Page([])),
        delete=AsyncMock(),
        turns=SimpleNamespace(list=AsyncMock(return_value=Page([]))),
        items=SimpleNamespace(list=AsyncMock(return_value=Page([]))),
        artifacts=SimpleNamespace(list=AsyncMock(return_value=Page([]))),
        events=SimpleNamespace(create=AsyncMock()),
    )
    service = OpenAIAgentService(tmp_path / "agents.sqlite", client_factory=lambda: SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions))))
    return service, sessions, binding


@pytest.mark.asyncio
async def test_bound_provenance_is_persisted_before_dispatch_and_survives_restart(bound_setup):
    service, sessions, binding = bound_setup
    prepared = prepare_bound_input(binding)

    async def inspect_admission(**kwargs):
        with sqlite3.connect(service.path) as db:
            saved = json.loads(db.execute("SELECT work_binding_json FROM sessions").fetchone()[0])
        assert saved == {"binding_digest": prepared.binding_digest, "metadata": prepared.metadata}
        assert binding.source.decode() not in json.dumps(saved)
        assert kwargs["metadata"]["momo_work_binding"] == prepared.binding_digest
        return {"id": "sess_remote", "status": "idle", "required_actions": [], "usage": None}

    sessions.create.side_effect = inspect_admission
    result = await service.create_bound(OWNER, binding)
    restarted = OpenAIAgentService(service.path, client_factory=service._factory)
    again = await restarted.create_bound(OWNER, binding)
    assert result["id"] == again["id"]
    assert sessions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("task", "Changed task"), ("work_item_version", 2), ("client_id", "other-client")])
async def test_bound_execution_cannot_redispatch_changed_work(bound_setup, field, value):
    service, sessions, binding = bound_setup
    await service.create_bound(OWNER, binding)
    with pytest.raises(AgentServiceError, match="idempotency_conflict"):
        await service.create_bound(OWNER, replace(binding, **{field: value}))
    assert sessions.create.await_count == 1


@pytest.mark.asyncio
async def test_wrong_owner_and_expired_validation_stop_before_storage_or_client(bound_setup):
    service, sessions, binding = bound_setup
    with pytest.raises(AgentServiceError, match="owner_binding_mismatch"):
        await service.create_bound("0" * 64, binding)
    old = replace(binding, validation_checked_at=(datetime.now(UTC) - timedelta(minutes=10)).isoformat())
    with pytest.raises(AgentServiceError, match="canonical_validation_stale"):
        await service.create_bound(OWNER, old)
    assert not service.path.exists()
    sessions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_bound_admission_never_redispatches(bound_setup):
    service, sessions, binding = bound_setup
    sessions.create.side_effect = TimeoutError("synthetic")
    with pytest.raises(AgentServiceError, match="provider_outcome_unknown"):
        await service.create_bound(OWNER, binding)
    result = await service.create_bound(OWNER, binding)
    assert result["operation_pending"] is True
    assert sessions.create.await_count == 1


@pytest.mark.asyncio
async def test_bound_session_rejects_free_text_followup_before_provider_read(bound_setup):
    service, sessions, binding = bound_setup
    result = await service.create_bound(OWNER, binding)
    reads = sessions.retrieve.await_count
    with pytest.raises(AgentServiceError, match="bound_session_followup_requires_validation"):
        await service.message(OWNER, result["id"], "Rebind to another client", "followup")
    assert sessions.retrieve.await_count == reads
    sessions.events.create.assert_not_awaited()


def completed_root(sessions):
    sessions.retrieve.return_value = {"id": "sess_remote", "status": "completed", "required_actions": [], "usage": None}
    sessions.turns.list.return_value = Page([{"id": "turn_root", "status": "completed", "subagent_id": None}])
    sessions.items.list.return_value = Page([{"id": "msg_final", "type": "message", "role": "assistant", "phase": "final_answer", "turn_id": "turn_root", "content": [{"type": "output_text", "text": "Draft prepared."}]}])
    sessions.artifacts.list.return_value = Page([{"id": "artifact_1", "path": "/workspace/outputs/draft.bin", "turn_id": "turn_root"}])


@pytest.mark.asyncio
async def test_binary_artifact_receipt_is_durable_immutable_and_not_acceptance(bound_setup):
    service, sessions, binding = bound_setup
    result = await service.create_bound(OWNER, binding)
    completed_root(sessions)
    payload = b"\x00\xff\x80synthetic binary"
    service.artifact = AsyncMock(return_value=payload)
    receipt = await service.record_bound_artifact(OWNER, result["id"], binding, "artifact_1")
    assert receipt["artifact_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["bytes"] == len(payload)
    assert receipt["semantic_acceptance"] == "not_evaluated"
    assert receipt["canonical_adoption"] == "not_performed"
    assert await service.record_bound_artifact(OWNER, result["id"], binding, "artifact_1") == receipt
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT count(*) FROM bound_artifact_receipts").fetchone()[0] == 1
    service.artifact.return_value = payload + b"changed"
    with pytest.raises(AgentServiceError, match="artifact_receipt_conflict"):
        await service.record_bound_artifact(OWNER, result["id"], binding, "artifact_1")
    with sqlite3.connect(service.path) as db:
        assert json.loads(db.execute("SELECT receipt_json FROM bound_artifact_receipts").fetchone()[0]) == receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["child_artifact", "child_final", "commentary", "running", "missing_final", "truncated"])
async def test_unproved_root_artifacts_never_receive_receipt(bound_setup, failure):
    service, sessions, binding = bound_setup
    result = await service.create_bound(OWNER, binding)
    completed_root(sessions)
    if failure == "child_artifact":
        sessions.artifacts.list.return_value.data[0]["turn_id"] = "turn_child"
    elif failure == "child_final":
        sessions.items.list.return_value.data[0]["agent_id"] = "child_1"
    elif failure == "commentary":
        sessions.items.list.return_value.data[0]["phase"] = "commentary"
    elif failure == "running":
        sessions.turns.list.return_value.data[0]["status"] = "running"
    elif failure == "missing_final":
        sessions.items.list.return_value = Page([])
    else:

        async def truncated_snapshot(*args):
            return {"history_truncated": True}

        service.snapshot = truncated_snapshot
    service.artifact = AsyncMock(return_value=b"draft")
    with pytest.raises(AgentServiceError, match="bound_artifact_completion_unproven"):
        await service.record_bound_artifact(OWNER, result["id"], binding, "artifact_1")
    service.artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_binding_cannot_read_provider_artifact(bound_setup):
    service, sessions, binding = bound_setup
    result = await service.create_bound(OWNER, binding)
    reads = sessions.retrieve.await_count
    with pytest.raises(AgentServiceError, match="work_binding_conflict"):
        await service.record_bound_artifact(OWNER, result["id"], replace(binding, work_item_version=2), "artifact_1")
    assert sessions.retrieve.await_count == reads


@pytest.mark.asyncio
async def test_ordinary_unbound_sessions_keep_existing_behavior(bound_setup):
    service, sessions, binding = bound_setup
    result = await service.create(OWNER, "A synthetic ordinary task", "Ordinary", "ordinary")
    await service.message(OWNER, result["id"], "A followup", "followup")
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT work_binding_json FROM sessions").fetchone()[0] is None
    sessions.events.create.assert_awaited_once()
