"""Real native run/thread/event stores cooperate with the checkpointed workflow graph."""

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
from deerflow.persistence.base import Base
from deerflow.persistence.models import RunChangeClockRow, RunRow, ThreadMetaRow
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import WorkspaceStorageContext, get_current_user, get_effective_user_id, reset_current_user, reset_storage_context, resolve_organization_id, set_current_user, set_storage_context
from deerflow.workflows.catalog import get_workflow

pytestmark = pytest.mark.anyio
NATIVE_OWNER = "wf_" + hashlib.sha256(b"momo-workflow-native\0synthetic-owner-scope").hexdigest()[:60]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class SyntheticAdapter:
    """Explicit offline outputs; exercises real app/native bookkeeping only."""

    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {"langgraph": {"available": True, "detail": "Offline synthetic response double"}}

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        properties = kwargs["output_schema"]["properties"]
        if kwargs["role"] == "planner":
            output = {"approach": ["Separate supplied facts from unanswered questions."], "producer_role": properties["producer_role"]["enum"][0], "effort": "low", "browser_needed": False}
        elif kwargs["role"] == "verifier":
            criteria = properties["checks"]["items"]["properties"]["criterion"]["enum"]
            output = {
                "approved": True,
                "output_sha256": properties["output_sha256"]["const"],
                "checks": [{"criterion": criterion, "passed": True, "rationale": "Checked against supplied synthetic notes."} for criterion in criteria],
                "findings": [],
            }
        else:
            output = {
                "workflow_id": properties["workflow_id"]["const"],
                "status": "draft",
                "assumptions": [],
                "evidence_references": ["input:source_excerpts"],
                "research_note": ["Supplied notes distinguish surviving metadata from a separately verified saved transcript."],
                "open_questions": ["Which persisted checkpoint proves conversation recovery after restart?"],
            }
        return {"output": output, "model": kwargs["model"], "effort": kwargs["effort"], "usage": {"input_tokens": 40, "output_tokens": 20, "cost": None}}


def runtime():
    run_store = MemoryRunStore()
    events = MemoryRunEventStore()
    manager = RunManager(store=run_store, event_store=events)
    threads = MemoryThreadMetaStore(InMemoryStore())
    return run_store, events, manager, threads


def service_at(path, *, saver, adapter, manager, threads, events, cls=WorkflowService):
    return cls(path, checkpointer=saver, adapter=adapter, run_manager=manager, thread_store=threads, event_store=events)


async def drain(service):
    for _ in range(12):
        if service.pump_task is not None:
            await asyncio.wait_for(asyncio.shield(service.pump_task), 5)
        tasks = list(service.tasks.values())
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        else:
            return
    raise AssertionError("Workflow admission did not drain")


async def create(service, key="synthetic-native"):
    definition = get_workflow("personal-research-note")
    return await service.create("synthetic-owner-scope", definition.id, definition.example_inputs, "langgraph", key, actor="synthetic-actor", organization="synthetic-org", storage_user="synthetic-actor")


async def test_real_graph_acceptance_populates_native_usage_owned_thread_and_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    service = service_at(tmp_path / "native.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    try:
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "completed" and result["accepted"] is True
        assert {key: result["usage"][key] for key in ("model_calls", "input_tokens", "output_tokens", "cost")} == {"model_calls": 3, "input_tokens": 120, "output_tokens": 60, "cost": None}
        assert result["usage"]["complete"] is True and result["usage"]["unknown_model_calls"] == 0
        native = await manager.get(result["native_run_id"], user_id=NATIVE_OWNER)
        persisted = await store.get(native.run_id, user_id=NATIVE_OWNER)
        assert native.user_id != "synthetic-actor" and len(native.user_id) <= 64
        assert await store.get(native.run_id, user_id="synthetic-actor") is None
        assert native.status == RunStatus.success
        assert persisted["status"] == "success" and persisted["llm_call_count"] == 3
        assert persisted["total_input_tokens"] == 120 and persisted["total_output_tokens"] == 60
        assert await threads.get(result["thread_id"], user_id=NATIVE_OWNER) is not None
        assert await threads.get(result["thread_id"], user_id="synthetic-actor") is None
        assert await threads.get(result["thread_id"], user_id="foreign-actor") is None
        journal = await events.list_events(result["thread_id"], native.run_id)
        kinds = [entry["event_type"] for entry in journal]
        assert kinds.count("run.start") == 1 and kinds.count("run.end") == 1
        messages = [entry for entry in journal if entry["category"] == "message"]
        assert any("research_note" in json.dumps(entry["content"]) for entry in messages)
        assert b"research_note" in await service.artifact("synthetic-owner-scope", admitted["id"])
        assert (await service.cancel("synthetic-owner-scope", admitted["id"]))["status"] == "completed"
        replay = await create(service)
        assert replay["id"] == admitted["id"]
        await drain(service)
        assert len(adapter.calls) == 3
    finally:
        await service.aclose()


async def test_workflow_service_error_from_a_model_call_keeps_its_own_code(tmp_path, monkeypatch):
    # engine.py wraps every model_call failure in WorkflowCallbackError("workflow_model_call_failed");
    # _run() must still recover the real WorkflowServiceError code from the chain, not the wrapper's.
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    service = service_at(tmp_path / "native.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    try:

        async def budget_exhausted(data, **kwargs):
            raise WorkflowServiceError("run_token_budget_exhausted", 429)

        service._model = budget_exhausted
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "failed" and result["error"] == "run_token_budget_exhausted"
        assert not adapter.calls
    finally:
        await service.aclose()


async def test_plain_model_call_exception_still_stores_workflow_model_call_failed(tmp_path, monkeypatch):
    # With no WorkflowServiceError anywhere in the chain, fall back to the outermost
    # (WorkflowCallbackError) code, not the innermost provider exception's.
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    service = service_at(tmp_path / "native.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    try:

        async def broken(data, **kwargs):
            raise RuntimeError("provider-private-secret-data-must-not-appear-in-error")

        service._model = broken
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "failed" and result["error"] == "workflow_model_call_failed"
        assert not adapter.calls
    finally:
        await service.aclose()


async def test_queue_cancel_before_execution_has_no_native_or_paid_admission(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    service = service_at(tmp_path / "queue.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    try:
        await drain(service)
        service.limits["max_running"] = 0
        admitted = await create(service)
        await drain(service)
        result = await service.cancel("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "cancelled" and result["accepted"] is False
        assert "native_run_id" not in result
        assert not adapter.calls
        assert not manager._runs
    finally:
        await service.aclose()


async def test_resume_cannot_bypass_global_queue_admission(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    service = service_at(tmp_path / "resume-queue.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    try:
        await drain(service)
        service.limits.update(max_running=0, max_queued=1)
        interrupted = await create(service, "interrupted")
        await drain(service)
        await service._storage("patch", interrupted["id"], "synthetic-owner-scope", {"status": "interrupted"})
        await create(service, "queued")
        await drain(service)
        with pytest.raises(WorkflowServiceError, match="queue_full"):
            await service.resume("synthetic-owner-scope", interrupted["id"])
        assert (await service.status("synthetic-owner-scope"))["queued"] == 1
        assert (await service.snapshot("synthetic-owner-scope", interrupted["id"]))["status"] == "interrupted"
        assert not adapter.calls and not manager._runs
    finally:
        await service.aclose()


async def test_sqlite_restart_resume_keeps_prior_usage_and_only_runs_saved_next_step(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    arrived, release = asyncio.Event(), asyncio.Event()

    class PauseBeforeVerification(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "verify" and status == "running":
                arrived.set()
                await release.wait()

    checkpoint_path = str(tmp_path / "checkpoints.sqlite")
    ledger_path = tmp_path / "ledger.sqlite"
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
        service = service_at(ledger_path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseBeforeVerification)
        await service.start()
        admitted = await create(service)
        await asyncio.wait_for(arrived.wait(), 5)
        await service.aclose()
        result = await service.snapshot("synthetic-owner-scope", admitted["id"]) if service.started else service._db("get", admitted["id"], "synthetic-owner-scope")
        assert result["status"] == "interrupted"
        assert result["usage"]["model_calls"] == 2
        initial_native_id = result["native_run_id"]
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
        manager = RunManager(store=store, event_store=events)
        service = service_at(ledger_path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events)
        await service.start()
        try:
            await service.resume("synthetic-owner-scope", admitted["id"])
            await drain(service)
            result = await service.snapshot("synthetic-owner-scope", admitted["id"])
            assert result["status"] == "completed" and result["accepted"] is True
            assert {key: result["usage"][key] for key in ("model_calls", "input_tokens", "output_tokens", "cost")} == {"model_calls": 3, "input_tokens": 120, "output_tokens": 60, "cost": None}
            assert result["usage"]["complete"] is True and result["usage"]["unknown_model_calls"] == 0
            assert len(adapter.calls) == 3 and adapter.calls[-1]["role"] == "verifier"
            attempts = [await store.get(run_id, user_id=NATIVE_OWNER) for run_id in (initial_native_id, result["native_run_id"])]
            assert len(attempts) == 2
            assert sum(attempt["total_input_tokens"] for attempt in attempts) == 120
            assert sum(attempt["total_output_tokens"] for attempt in attempts) == 60
            assert sum(attempt["llm_call_count"] for attempt in attempts) == 3
        finally:
            await service.aclose()


async def test_native_abort_fence_cannot_promote_cancelled_job_to_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    arrived, release = asyncio.Event(), asyncio.Event()

    class PauseBeforePlan(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "plan" and status == "running":
                arrived.set()
                await release.wait()

    service = service_at(tmp_path / "abort.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseBeforePlan)
    await service.start()
    try:
        admitted = await create(service)
        await asyncio.wait_for(arrived.wait(), 5)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        await manager.cancel(result["native_run_id"])
        await drain(service)
        final = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert final["status"] in {"cancelled", "interrupted"}
        assert final["accepted"] is False and final["artifact"] is None
        assert not adapter.calls
        native = await manager.get(result["native_run_id"], user_id=NATIVE_OWNER)
        assert native.status == RunStatus.interrupted
    finally:
        release.set()
        await service.aclose()


async def test_cancel_after_artifact_write_before_acceptance_hides_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    arrived, release = asyncio.Event(), asyncio.Event()

    class PauseAfterArtifactWrite(WorkflowService):
        async def _write_artifact(self, data, result):
            await super()._write_artifact(data, result)
            arrived.set()
            await release.wait()

    service = service_at(tmp_path / "artifact-race.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseAfterArtifactWrite)
    await service.start()
    try:
        admitted = await create(service)
        await asyncio.wait_for(arrived.wait(), 5)
        final = await service.cancel("synthetic-owner-scope", admitted["id"])
        await drain(service)
        assert final["status"] == "cancelled" and final["accepted"] is False
        assert final["output"] is None
        with pytest.raises(WorkflowServiceError, match="artifact_unavailable"):
            await service.artifact("synthetic-owner-scope", admitted["id"])
        native = await manager.get(final["native_run_id"], user_id=NATIVE_OWNER)
        assert native.status == RunStatus.interrupted
        assert len(adapter.calls) == 3
    finally:
        release.set()
        await service.aclose()


async def test_repeated_cancel_does_not_interrupt_native_terminal_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    running, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    closed = []

    class PauseDuringCancellation(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "plan" and status == "running":
                running.set()
                await release.wait()

        async def _native_finish(self, record, data, status, error=None):
            if status == "cancelled":
                cleanup.set()
                await release.wait()
                closed.append(record.run_id)
            await super()._native_finish(record, data, status, error)

    service = service_at(tmp_path / "cancel-race.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseDuringCancellation)
    await service.start()
    first = None
    try:
        admitted = await create(service)
        await asyncio.wait_for(running.wait(), 5)
        first = asyncio.create_task(service.cancel("synthetic-owner-scope", admitted["id"]))
        await asyncio.wait_for(cleanup.wait(), 5)
        second = await service.cancel("synthetic-owner-scope", admitted["id"])
        assert second["status"] == "cancelled"
        release.set()
        final = await asyncio.wait_for(first, 5)
        await drain(service)
        assert final["accepted"] is False
        assert closed == [final["native_run_id"]]
        native = await manager.get(final["native_run_id"], user_id=NATIVE_OWNER)
        assert native.status == RunStatus.interrupted
        journal = await events.list_events(final["thread_id"], native.run_id)
        assert [entry["event_type"] for entry in journal].count("run.end") == 1
        assert not adapter.calls
    finally:
        release.set()
        if first is not None:
            await asyncio.gather(first, return_exceptions=True)
        await service.aclose()


async def test_known_paid_receipt_replays_missing_ai_journal_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    arrived, release = asyncio.Event(), asyncio.Event()

    class PauseAfterReceiptBeforeJournal(WorkflowService):
        async def _journal_model(self, data, result, kwargs):
            if kwargs["role"] == "planner":
                arrived.set()
                await release.wait()
            await super()._journal_model(data, result, kwargs)

    checkpoint_path = str(tmp_path / "journal-checkpoints.sqlite")
    ledger_path = tmp_path / "journal-ledger.sqlite"
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
        service = service_at(ledger_path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseAfterReceiptBeforeJournal)
        await service.start()
        admitted = await create(service)
        await asyncio.wait_for(arrived.wait(), 5)
        await service.aclose()
        interrupted = service._db("get", admitted["id"], "synthetic-owner-scope")
        assert interrupted["status"] == "interrupted"
        assert interrupted["usage"]["model_calls"] == 1
        assert interrupted["usage"]["unknown_model_calls"] == 0
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
        manager = RunManager(store=store, event_store=events)
        service = service_at(ledger_path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events)
        await service.start()
        try:
            await service.resume("synthetic-owner-scope", admitted["id"])
            await drain(service)
            final = await service.snapshot("synthetic-owner-scope", admitted["id"])
            assert final["status"] == "completed" and final["accepted"] is True
            assert len(adapter.calls) == 3
            assert final["usage"]["model_calls"] == 3
            journal = await events.list_messages(final["thread_id"], user_id=NATIVE_OWNER)
            ai = [entry for entry in journal if entry["event_type"] == "llm.ai.response"]
            assert len(ai) == 3
            assert len({entry["metadata"]["call_id"] for entry in ai}) == 3
        finally:
            await service.aclose()


async def test_cancelling_cancel_request_does_not_abort_native_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    running, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class PauseDuringCleanup(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "plan" and status == "running":
                running.set()
                await release.wait()

        async def _native_finish(self, record, data, status, error=None):
            if status == "cancelled":
                cleanup.set()
                await release.wait()
            await super()._native_finish(record, data, status, error)

    service = service_at(tmp_path / "cancel-request.sqlite", saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseDuringCleanup)
    await service.start()
    request = None
    try:
        admitted = await create(service)
        await asyncio.wait_for(running.wait(), 5)
        request = asyncio.create_task(service.cancel("synthetic-owner-scope", admitted["id"]))
        await asyncio.wait_for(cleanup.wait(), 5)
        request.cancel()
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        await drain(service)
        final = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert final["status"] == "cancelled" and final["accepted"] is False
        native = await manager.get(final["native_run_id"], user_id=NATIVE_OWNER)
        assert native.status == RunStatus.interrupted
        journal = await events.list_events(final["thread_id"], native.run_id)
        assert [entry["event_type"] for entry in journal].count("run.end") == 1
        assert not adapter.calls
    finally:
        release.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await service.aclose()


async def test_sql_journal_uses_private_native_owner_and_authority_uses_actual_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'journal.sqlite'}")
    factory = async_sessionmaker(db, expire_on_commit=False)
    async with db.begin() as connection:
        await connection.run_sync(
            lambda connection: Base.metadata.create_all(connection, tables=[OrganizationRow.__table__, ProjectRow.__table__, ThreadMetaRow.__table__, RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__])
        )
    store, threads = RunRepository(factory), ThreadMetaRepository(factory)
    events = DbRunEventStore(factory)
    manager = RunManager(store=store, event_store=events)
    authorizations = []
    original_org = private_organization_id("shared-storage")

    async def actual_authority(actor, organization, workspace):
        authorizations.append((actor, organization, workspace))
        return (actor, organization, workspace) == ("synthetic-actor", original_org, "shared-storage")

    class OriginalActorAdapter(SyntheticAdapter):
        async def call(self, **kwargs):
            assert get_current_user().id == "synthetic-actor"
            assert get_effective_user_id() == "shared-storage"
            assert resolve_organization_id() == original_org
            return await super().call(**kwargs)

    adapter = OriginalActorAdapter()
    service = WorkflowService(tmp_path / "sql-ledger.sqlite", checkpointer=InMemorySaver(), adapter=adapter, run_manager=manager, thread_store=threads, event_store=events, authority=actual_authority)
    user_token = set_current_user(SimpleNamespace(id="synthetic-actor"))
    storage_token = set_storage_context(WorkspaceStorageContext("synthetic-actor", original_org, "shared-storage"))
    await service.start()
    try:
        definition = get_workflow("personal-research-note")
        admitted = await service.create("synthetic-owner-scope", definition.id, definition.example_inputs, "langgraph", "synthetic-private-journal", actor="synthetic-actor", organization=original_org, storage_user="shared-storage")
        await drain(service)
        final = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert final["status"] == "completed" and final["accepted"] is True
        assert len(adapter.calls) == 3 and authorizations
        assert set(authorizations) == {("synthetic-actor", original_org, "shared-storage")}
        quarantine = set_storage_context(WorkspaceStorageContext("synthetic-actor", None, NATIVE_OWNER))
        try:
            native = await store.get(final["native_run_id"], user_id=NATIVE_OWNER)
            thread = await threads.get(final["thread_id"], user_id=NATIVE_OWNER)
        finally:
            reset_storage_context(quarantine)
        assert native["organization_id"] is None and thread["organization_id"] is None
        journal = await events.list_events(final["thread_id"], final["native_run_id"], user_id=NATIVE_OWNER)
        assert len(journal) == 5
        assert {row["user_id"] for row in journal} == {NATIVE_OWNER}
        assert await events.list_events(final["thread_id"], final["native_run_id"], user_id="shared-storage") == []
        assert await events.list_messages(final["thread_id"], user_id="synthetic-actor") == []
        assert native["llm_call_count"] == 3 and native["total_input_tokens"] == 120
        assert await store.get(final["native_run_id"], user_id=NATIVE_OWNER) is None
        assert await threads.check_access(final["thread_id"], "shared-storage", require_existing=True) is False
        assert b"research_note" in await service.artifact("synthetic-owner-scope", admitted["id"])
    finally:
        await service.aclose()
        await db.dispose()
        reset_storage_context(storage_token)
        reset_current_user(user_token)


async def test_actual_sql_native_restart_resume_preserves_private_journal_and_per_attempt_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native-restart.sqlite'}")
    factory = async_sessionmaker(db, expire_on_commit=False)
    async with db.begin() as connection:
        await connection.run_sync(
            lambda connection: Base.metadata.create_all(connection, tables=[OrganizationRow.__table__, ProjectRow.__table__, ThreadMetaRow.__table__, RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__])
        )
    store, threads, events = RunRepository(factory), ThreadMetaRepository(factory), DbRunEventStore(factory)
    adapter = SyntheticAdapter()
    arrived, release = asyncio.Event(), asyncio.Event()
    original_org = private_organization_id("shared-storage")
    user_token = set_current_user(SimpleNamespace(id="synthetic-actor"))
    storage_token = set_storage_context(WorkspaceStorageContext("synthetic-actor", original_org, "shared-storage"))

    class PauseBeforeVerification(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "verify" and status == "running":
                arrived.set()
                await release.wait()

    path, checkpoints = tmp_path / "ledger-restart.sqlite", str(tmp_path / "graph-restart.sqlite")
    try:
        async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
            manager = RunManager(store=store, event_store=events)
            first = service_at(path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events, cls=PauseBeforeVerification)
            await first.start()
            definition = get_workflow("personal-research-note")
            admitted = await first.create("synthetic-owner-scope", definition.id, definition.example_inputs, "langgraph", "synthetic-restart", actor="synthetic-actor", organization=original_org, storage_user="shared-storage")
            await asyncio.wait_for(arrived.wait(), 5)
            await first.aclose()
            prior = first._db("get", admitted["id"], "synthetic-owner-scope")
            assert prior["status"] == "interrupted" and prior["usage"]["model_calls"] == 2
        async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
            manager = RunManager(store=store, event_store=events)
            resumed = service_at(path, saver=saver, adapter=adapter, manager=manager, threads=threads, events=events)
            await resumed.start()
            try:
                await resumed.resume("synthetic-owner-scope", admitted["id"])
                await drain(resumed)
                final = await resumed.snapshot("synthetic-owner-scope", admitted["id"])
                assert final["status"] == "completed" and final["accepted"] is True
                assert len(adapter.calls) == 3 and adapter.calls[-1]["role"] == "verifier"
                assert final["usage"]["model_calls"] == 3 and final["usage"]["input_tokens"] == 120 and final["usage"]["output_tokens"] == 60
                quarantine = set_storage_context(WorkspaceStorageContext("synthetic-actor", None, NATIVE_OWNER))
                try:
                    attempts = [await store.get(run_id, user_id=NATIVE_OWNER) for run_id in (prior["native_run_id"], final["native_run_id"])]
                    messages = await events.list_messages(final["thread_id"], user_id=NATIVE_OWNER)
                finally:
                    reset_storage_context(quarantine)
                assert {row["organization_id"] for row in attempts} == {None}
                assert {row["user_id"] for row in attempts} == {NATIVE_OWNER}
                assert sum(row["llm_call_count"] for row in attempts) == 3
                assert sum(row["total_input_tokens"] for row in attempts) == 120
                assert sum(row["total_output_tokens"] for row in attempts) == 60
                assert len(messages) == 3 and len({row["metadata"]["call_id"] for row in messages}) == 3
                assert await store.get(final["native_run_id"], user_id="shared-storage") is None
                assert await threads.check_access(final["thread_id"], "shared-storage", require_existing=True) is False
                assert b"research_note" in await resumed.artifact("synthetic-owner-scope", admitted["id"])
            finally:
                await resumed.aclose()
    finally:
        release.set()
        await db.dispose()
        reset_storage_context(storage_token)
        reset_current_user(user_token)


async def test_existing_legacy_native_journal_aborts_startup_without_rewriting_originals(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    adapter = SyntheticAdapter()
    path = tmp_path / "legacy-native.sqlite"
    service = service_at(path, saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    await service.start()
    admitted = await create(service)
    await drain(service)
    final = await service.snapshot("synthetic-owner-scope", admitted["id"])
    journal = await events.list_events(final["thread_id"], final["native_run_id"])
    await service.aclose()
    with sqlite3.connect(path) as connection:
        data = json.loads(connection.execute("SELECT data FROM workflow_jobs WHERE id=?", (admitted["id"],)).fetchone()[0])
        data.pop("_native_storage_user")
        original = json.dumps(data)
        connection.execute("UPDATE workflow_jobs SET data=? WHERE id=?", (original, admitted["id"]))
    resumed = service_at(path, saver=InMemorySaver(), adapter=adapter, manager=manager, threads=threads, events=events)
    with pytest.raises(RuntimeError, match="workflow_native_namespace_migration_required"):
        await resumed.start()
    assert not resumed.started and resumed.lease is None and not resumed.tasks
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT data FROM workflow_jobs WHERE id=?", (admitted["id"],)).fetchone()[0] == original
    assert await events.list_events(final["thread_id"], final["native_run_id"]) == journal
    assert len(adapter.calls) == 3


async def test_existing_standalone_admission_without_native_journal_still_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    path = tmp_path / "legacy-standalone.sqlite"
    adapter = SyntheticAdapter()
    service = WorkflowService(path, checkpointer=InMemorySaver(), adapter=adapter)
    await service.start()
    admitted = await create(service)
    await drain(service)
    await service.aclose()
    with sqlite3.connect(path) as connection:
        data = json.loads(connection.execute("SELECT data FROM workflow_jobs WHERE id=?", (admitted["id"],)).fetchone()[0])
        data.pop("_native_storage_user")
        connection.execute("UPDATE workflow_jobs SET data=? WHERE id=?", (json.dumps(data), admitted["id"]))
    resumed = WorkflowService(path, checkpointer=InMemorySaver(), adapter=adapter)
    await resumed.start()
    try:
        final = await resumed.snapshot("synthetic-owner-scope", admitted["id"])
        assert final["status"] == "completed" and final["accepted"] is True
        assert "native_run_id" not in final and len(adapter.calls) == 3
        assert b"research_note" in await resumed.artifact("synthetic-owner-scope", admitted["id"])
    finally:
        await resumed.aclose()
