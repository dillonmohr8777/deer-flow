"""Synthetic admission, durable-clock and real worker regressions; no providers."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.run_config import RunConfig
from deerflow.persistence.run import RunRepository
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import ConflictError, RunManager, RunStartOutcome, RunStartupError
from deerflow.runtime.runs.schemas import RunStatus, ThreadOperationKind
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


@pytest.fixture(params=["memory", "sql"])
async def limit_store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'limits.db'}", sqlite_dir=str(tmp_path))
    try:
        yield RunRepository(get_session_factory())
    finally:
        await close_engine()


def test_operator_defaults_disable_and_validation():
    assert AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}).run == RunConfig(execution_timeout_seconds=2700, prestart_wait_seconds=300)
    for value in (None, 0, -10):
        assert RunConfig(execution_timeout_seconds=value, prestart_wait_seconds=value).execution_timeout_seconds is None
    for value in (True, "0", float("inf"), float("nan"), 1e300, 10**1000):
        with pytest.raises(ValidationError):
            RunConfig(prestart_wait_seconds=value)
    with pytest.raises(ValidationError):
        RunConfig(deadline_at="2099-01-01")


@pytest.mark.anyio
async def test_captured_policy_start_once_reload_and_metadata(limit_store):
    manager = RunManager(store=limit_store, run_config=RunConfig(execution_timeout_seconds=20, prestart_wait_seconds=10))
    metadata = {"run_limits": {"execution_timeout_seconds": None}, "prestart_deadline_at": "2099-01-01", "regenerate_from_run_id": "source"}
    kwargs = {"__deerflow_run_storage_v1__": {"kwargs": {}, "timing": {"execution_timeout_seconds": None}}, "config": {"context": {"run": {"execution_timeout_seconds": 0}}}}
    record = await manager.create_or_reject("captured", metadata=metadata, kwargs=kwargs)
    try:
        pending = deepcopy(await limit_store.get(record.run_id))
        assert pending["metadata"] == metadata
        assert pending["kwargs"] == kwargs
        assert pending["run_limits"]["execution_timeout_seconds"] == 20
        assert pending["run_limits"]["started_at"] is None
        assert await manager.try_start(record.run_id) == RunStartOutcome.started
        running = deepcopy(await limit_store.get(record.run_id))
        timing = running["run_limits"]
        assert datetime.fromisoformat(timing["execution_deadline_at"]) - datetime.fromisoformat(timing["started_at"]) == timedelta(seconds=20)
        assert await manager.try_start(record.run_id) == RunStartOutcome.cancelled
        assert await limit_store.start_run(record.run_id) is False
        await limit_store.put(record.run_id, **manager._store_put_payload(manager._record_from_store(pending)))
        assert (await limit_store.get(record.run_id))["run_limits"] == timing
        reloaded = RunManager(store=limit_store, run_config=RunConfig(execution_timeout_seconds=999, prestart_wait_seconds=999))
        hydrated = await reloaded.get(record.run_id)
        assert hydrated.run_limits == timing
        assert hydrated.metadata == metadata and hydrated.kwargs == kwargs
    finally:
        await manager.stop_run_limit(record.run_id)


@pytest.mark.anyio
async def test_snapshot_cannot_retrofit_policy_onto_legacy_row(limit_store):
    await limit_store.put("legacy", thread_id="legacy", kwargs={"original": True})
    await limit_store.put("legacy", thread_id="legacy", run_limits={"execution_timeout_seconds": 999})
    assert (await limit_store.get("legacy"))["run_limits"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("shape", ["TEXT", "JSON NOT NULL", "JSON DEFAULT '{}' "])
async def test_run_limit_schema_helper_rejects_drift(tmp_path, shape):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.persistence.run.schema import ensure_run_limits_column

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'drift.db'}")
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE TABLE runs (run_limits_json {shape})"))
            with pytest.raises(RuntimeError, match="nullable JSON without a server default"):
                await connection.run_sync(ensure_run_limits_column)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_cancelled_run_limit_ddl_keeps_bootstrap_lock_until_commit(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.util import await_only

    from deerflow.persistence.bootstrap import bootstrap_schema
    from deerflow.persistence.run import schema

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ddl-drain.db'}")
    entered, release = asyncio.Event(), asyncio.Event()
    first = second = None
    original = schema.ensure_run_limits_column
    calls = 0

    def held_after_actual_ddl(connection):
        nonlocal calls
        original(connection)
        calls += 1
        if calls == 1:
            entered.set()
            await_only(release.wait())

    try:
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE runs DROP COLUMN run_limits_json"))
        monkeypatch.setattr(schema, "ensure_run_limits_column", held_after_actual_ddl)
        first = asyncio.create_task(bootstrap_schema(engine, backend="sqlite"))
        await asyncio.wait_for(entered.wait(), 5)
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        second = asyncio.create_task(bootstrap_schema(engine, backend="sqlite"))
        for _ in range(10):
            await asyncio.sleep(0)
        assert not first.done() and not second.done() and calls == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(second, 5)
        assert calls == 2
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "0053_board_work_plan"
            await connection.execute(text("SELECT run_limits_json FROM runs"))
    finally:
        release.set()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
        await engine.dispose()


def bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


def start_worker(manager, record, output, *, event_store=None, factory=None):
    record.task = asyncio.create_task(
        run_agent(output, manager, record, ctx=RunContext(checkpointer=None, event_store=event_store), agent_factory=factory or Mock(side_effect=AssertionError("agent must not start")), graph_input={}, config={})
    )
    return record.task


@pytest.mark.anyio
async def test_prestart_expiry_leaves_prior_finalizer_held(limit_store):
    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, run_config=RunConfig(prestart_wait_seconds=0.04, execution_timeout_seconds=1))
    prior = await manager.create_or_reject("barrier")
    await manager.cancel(prior.run_id)
    await manager.set_finalizing(prior.run_id, True)
    replacement = await manager.create_or_reject("barrier", multitask_strategy="interrupt")
    output = bridge()
    await asyncio.wait_for(start_worker(manager, replacement, output, event_store=events), 2)
    stored = await limit_store.get(replacement.run_id)
    assert stored["status"] == "error" and stored["stop_reason"] == "prestart_wait_timeout"
    assert stored["run_limits"]["started_at"] is None
    assert prior.finalizing and prior.abort_action == "interrupt"
    output.publish_end.assert_awaited_once_with(replacement.run_id)
    rows = await events.list_events(replacement.thread_id, replacement.run_id)
    assert any(row["event_type"] == "run.error" and row["metadata"].get("stop_reason") == "prestart_wait_timeout" for row in rows)
    assert not manager._limit_tasks


@pytest.mark.anyio
async def test_execution_timeout_drains_worker_before_terminal_and_end(limit_store, monkeypatch):
    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.04))
    record = await manager.create_or_reject("execution")
    entered, cancelling, drain = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleanup = AsyncMock()
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", cleanup)

    class BlockingAgent:
        async def astream(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                await drain.wait()
            yield

    output = bridge()
    task = start_worker(manager, record, output, event_store=events, factory=lambda **kwargs: BlockingAgent())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(cancelling.wait(), 2)
        assert record.status == RunStatus.running and record.finalizing
        held = await limit_store.get(record.run_id)
        assert held["status"] == "running" and held["cancel_action"] == "execution_timeout"
        assert await limit_store.claim_for_takeover(record.run_id, grace_seconds=0, error="wrong") is False
        assert not await limit_store.list_inflight_with_expired_lease(grace_seconds=0)
        with pytest.raises(ConflictError):
            await manager.create_or_reject("execution", multitask_strategy="interrupt")
        output.publish_end.assert_not_awaited()
    finally:
        drain.set()
        await asyncio.wait_for(task, 2)
    assert cleanup.await_count >= 1
    assert record.status == RunStatus.timeout and record.stop_reason == "execution_timeout"
    assert (await limit_store.get(record.run_id))["status"] == "timeout"
    output.publish_end.assert_awaited_once_with(record.run_id)
    assert not manager._limit_tasks


@pytest.mark.anyio
async def test_never_attached_pending_expires_and_late_worker_cannot_double_end(limit_store):
    output = bridge()
    manager = RunManager(store=limit_store, on_unstarted_limit=output.publish_end, run_config=RunConfig(prestart_wait_seconds=0.02))
    record = await manager.create_or_reject("unattached")
    await asyncio.wait_for(record.abort_event.wait(), 2)
    # Finish the supervisor's durable write; no wall-clock delay assumption.
    task = manager._limit_tasks.get(record.run_id)
    if task is not None:
        await task
    assert (await limit_store.get(record.run_id))["status"] == "error"
    await start_worker(manager, record, output)
    output.publish_end.assert_awaited_once()


@pytest.mark.anyio
async def test_non_run_holds_get_no_policy_or_supervisor(limit_store):
    manager = RunManager(store=limit_store, run_config=RunConfig(prestart_wait_seconds=0.001, execution_timeout_seconds=0.001))
    for kind in (ThreadOperationKind.upload_write, ThreadOperationKind.artifact_write):
        async with manager.reserve_thread_operation(f"hold-{kind}", kind=kind) as record:
            assert record.run_limits is None
            assert (await limit_store.get(record.run_id))["run_limits"] is None
            assert record.run_id not in manager._limit_tasks
            assert not record.abort_event.is_set()


@pytest.mark.anyio
async def test_disabled_policy_and_unsupported_store_compatibility():
    class LegacyStore(MemoryRunStore):
        supports_run_limits = False

    legacy = LegacyStore()
    with pytest.raises(RunStartupError, match="cannot persist"):
        await RunManager(store=legacy).create_or_reject("unsupported")
    manager = RunManager(store=legacy, run_config=RunConfig(prestart_wait_seconds=None, execution_timeout_seconds=0))
    record = await manager.create_or_reject("disabled")
    assert record.run_limits is None and not manager._limit_tasks
    assert await manager.try_start(record.run_id) == RunStartOutcome.started


@pytest.mark.anyio
async def test_store_claiming_timing_support_must_confirm_deadline_before_agent_start():
    class IncompleteTimingStore(MemoryRunStore):
        async def start_run(self, run_id):
            started = await super().start_run(run_id)
            if started:
                self._runs[run_id]["run_limits"]["execution_deadline_at"] = None
            return started

    manager = RunManager(store=IncompleteTimingStore())
    record = await manager.create_or_reject("invalid-capability")
    factory = Mock(side_effect=AssertionError("unconfirmed timing must not execute"))
    output = bridge()
    await start_worker(manager, record, output, factory=factory)
    factory.assert_not_called()
    assert record.status == RunStatus.error and "immutable persisted execution timing" in record.error
    output.publish_end.assert_awaited_once()


@pytest.mark.anyio
async def test_preflight_guard_cancels_and_drains_before_terminal(limit_store):
    output = bridge()
    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, on_unstarted_limit=output.publish_end, run_config=RunConfig(prestart_wait_seconds=0.03))
    record = await manager.create_or_reject("preflight")
    entered, unwinding, drain = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def preflight():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwinding.set()
            await drain.wait()

    task = manager.create_worker_task(record, preflight())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(unwinding.wait(), 2)
        assert (await limit_store.get(record.run_id))["status"] == "pending"
        output.publish_end.assert_not_awaited()
    finally:
        drain.set()
        await asyncio.wait_for(task, 2)
    assert (await limit_store.get(record.run_id))["status"] == "error"
    output.publish_end.assert_awaited_once()
    assert not record.worker_entered and not record.finalizing


@pytest.mark.anyio
async def test_cleanup_failure_retains_timeout_claim_and_no_end(limit_store, monkeypatch):
    manager = RunManager(store=limit_store, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.04))
    record = await manager.create_or_reject("cleanup-unknown")
    entered = asyncio.Event()

    class BlockingAgent:
        async def astream(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            yield

    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", AsyncMock(side_effect=RuntimeError("synthetic unknown cleanup")))
    output = bridge()
    task = start_worker(manager, record, output, factory=lambda **kwargs: BlockingAgent())
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(RuntimeError, match="unknown cleanup"):
        await asyncio.wait_for(task, 2)
    held = await limit_store.get(record.run_id)
    assert held["status"] == "running" and held["cancel_action"] == "execution_timeout"
    output.publish_end.assert_not_awaited()
    assert record.finalizing and record.status == RunStatus.running
    await manager.cleanup(record.run_id, delay=0)
    assert record.run_id in manager._runs
    await manager.shutdown(timeout=0.1)
    assert (await limit_store.get(record.run_id))["status"] == "running"


@pytest.mark.anyio
async def test_explicit_interrupt_wins_before_internal_deadline(limit_store):
    manager = RunManager(store=limit_store, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.1))
    record = await manager.create_or_reject("first-cause")
    output = bridge()
    await manager.cancel(record.run_id, action="rollback")
    await start_worker(manager, record, output)
    assert record.abort_action == "rollback" and record.status == RunStatus.error
    assert record.stop_reason is None
    assert (await limit_store.get(record.run_id))["status"] == "error"
    output.publish_end.assert_awaited_once()
    assert not manager._limit_tasks


@pytest.mark.anyio
async def test_real_gateway_deps_capture_operator_policy_and_publish_end():
    from fastapi import FastAPI

    from app.gateway.deps import langgraph_runtime
    from app.gateway.routers.thread_runs import _record_to_response
    from deerflow.runtime import END_SENTINEL

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "memory"}, "run": {"prestart_wait_seconds": 0.02, "execution_timeout_seconds": 7}})
    app = FastAPI()
    async with langgraph_runtime(app, config):
        manager = app.state.run_manager
        record = await manager.create_or_reject("deps-normal", metadata={"run": {"prestart_wait_seconds": 999}}, kwargs={"input": {}})
        task = manager._limit_tasks[record.run_id]
        await asyncio.wait_for(task, 2)
        assert record.run_limits["execution_timeout_seconds"] == 7
        assert record.status == RunStatus.error
        response = _record_to_response(record).model_dump()
        assert response["metadata"] == {"run": {"prestart_wait_seconds": 999}}
        assert response["kwargs"] == {"input": {}}
        assert "run_limits" not in response
        frames = [event async for event in app.state.stream_bridge.subscribe(record.run_id)]
        assert frames == [END_SENTINEL]


@pytest.mark.anyio
async def test_real_start_run_ignores_caller_policy_in_all_carriers(monkeypatch):
    from fastapi import FastAPI

    from app.gateway import services
    from app.gateway.deps import langgraph_runtime
    from app.gateway.routers.thread_runs import RunCreateRequest, _record_to_response
    from deerflow.config.app_config import reset_app_config, set_app_config

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "memory"}, "run": {"prestart_wait_seconds": 1, "execution_timeout_seconds": 0.06}})
    entered = asyncio.Event()

    class BlockingAgent:
        async def astream(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            yield

    monkeypatch.setattr(services, "resolve_agent_factory", lambda *args, **kwargs: lambda **kwargs: BlockingAgent())
    set_app_config(config)
    try:
        app = FastAPI()
        async with langgraph_runtime(app, config):
            request = SimpleNamespace(headers={}, state=SimpleNamespace(), app=app)
            spoof = {"run": {"execution_timeout_seconds": None, "prestart_wait_seconds": 999}, "run_limits": {"execution_deadline_at": "2099-01-01"}}
            body = RunCreateRequest(input={"messages": [{"role": "user", "content": "synthetic limit check"}]}, metadata=spoof, context=spoof, config={"configurable": spoof, "context": spoof})
            record = await services.start_run(body, "normal-services-limit", request)
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(record.task, 2)
            assert record.status == RunStatus.timeout
            assert record.run_limits["execution_timeout_seconds"] == 0.06
            assert record.run_limits["prestart_wait_seconds"] == 1
            response = _record_to_response(record).model_dump()
            assert response["metadata"]["run"] == spoof["run"]
            assert "run_limits" not in response["kwargs"]
    finally:
        reset_app_config()


@pytest.mark.anyio
async def test_total_execution_cap_survives_root_success_and_continuation(limit_store, monkeypatch):
    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.08))
    record = await manager.create_or_reject("continuations")
    evaluations = 0
    evaluating_second = asyncio.Event()
    observed_timing = []

    class CompletedRoot:
        async def astream(self, _input, *, config, **kwargs):
            observed_timing.append(deepcopy(record.run_limits))
            for handler in config.get("callbacks", []):
                if hasattr(handler, "on_chain_end"):
                    handler.on_chain_end({"messages": []}, run_id=uuid4())
            yield ("values", {"messages": []})

    async def evaluate(**kwargs):
        nonlocal evaluations
        evaluations += 1
        if evaluations == 1:
            return {"messages": []}
        evaluating_second.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("deerflow.runtime.runs.worker._prepare_goal_continuation_input", evaluate)
    output = bridge()
    task = start_worker(manager, record, output, event_store=events, factory=lambda **kwargs: CompletedRoot())
    await asyncio.wait_for(evaluating_second.wait(), 2)
    assert record.status == RunStatus.running
    assert not any(row["event_type"] == "run.end" for row in await events.list_events(record.thread_id, record.run_id))
    await asyncio.wait_for(task, 2)
    assert len(observed_timing) == 2 and observed_timing[0] == observed_timing[1]
    assert record.status == RunStatus.timeout
    rows = await events.list_events(record.thread_id, record.run_id)
    assert not any(row["event_type"] == "run.end" for row in rows)
    assert any(row["event_type"] == "run.error" and row["metadata"].get("stop_reason") == "execution_timeout" for row in rows)
    output.publish_end.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("expire_during_cleanup", [False, True])
async def test_managed_success_waits_for_cleanup_and_deadline_stays_armed(limit_store, monkeypatch, expire_during_cleanup):
    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.05 if expire_during_cleanup else 2))
    record = await manager.create_or_reject("terminal-staging")
    cleanup_entered, release = asyncio.Event(), asyncio.Event()
    callback_states = []

    class CompletedRoot:
        async def astream(self, _input, *, config, **kwargs):
            for handler in config.get("callbacks", []):
                if hasattr(handler, "on_chain_end"):
                    handler.on_chain_end({"messages": []}, run_id=uuid4())
            yield ("values", {"messages": []})

    async def cleanup(_context):
        cleanup_entered.set()
        await release.wait()

    async def completed(snapshot):
        callback_states.append(snapshot.status)
        assert snapshot is record
        assert record.status in (RunStatus.success, RunStatus.timeout)

    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", cleanup)
    output = bridge()
    record.task = asyncio.create_task(run_agent(output, manager, record, ctx=RunContext(checkpointer=None, event_store=events, on_run_completed=completed), agent_factory=lambda **kwargs: CompletedRoot(), graph_input={}, config={}))
    try:
        await asyncio.wait_for(cleanup_entered.wait(), 2)
        if expire_during_cleanup:
            await asyncio.wait_for(record.abort_event.wait(), 2)
        assert record.status == RunStatus.running and (await limit_store.get(record.run_id))["status"] == "running"
        assert not any(row["event_type"] == "run.end" for row in await events.list_events(record.thread_id, record.run_id))
        output.publish_end.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(record.task, 2)
    expected = RunStatus.timeout if expire_during_cleanup else RunStatus.success
    assert record.status == expected and callback_states == [expected]
    rows = await events.list_events(record.thread_id, record.run_id)
    assert sum(row["event_type"] == "run.end" for row in rows) == (0 if expire_during_cleanup else 1)
    output.publish_end.assert_awaited_once()


def test_owned_children_tracker_cannot_be_supplied_by_caller_or_checkpointed():
    from deerflow.runtime.runs.owned_children import OWNED_CHILDREN_CONTEXT_KEY, OwnedRunChildren
    from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context, _release_run_scoped_references

    caller = {OWNED_CHILDREN_CONTEXT_KEY: {"completed": True}}
    runtime = _build_runtime_context("synthetic-thread", "synthetic-run", caller)
    assert OWNED_CHILDREN_CONTEXT_KEY not in runtime
    trusted = OwnedRunChildren()
    runtime[OWNED_CHILDREN_CONTEXT_KEY] = trusted
    config = {"context": dict(caller), "configurable": dict(caller)}
    _install_runtime_context(config, runtime)
    assert OWNED_CHILDREN_CONTEXT_KEY not in config["configurable"]
    assert config["context"][OWNED_CHILDREN_CONTEXT_KEY] is trusted
    _release_run_scoped_references([config], runtime, None)
    assert OWNED_CHILDREN_CONTEXT_KEY not in runtime
    assert OWNED_CHILDREN_CONTEXT_KEY not in config["context"]


@pytest.mark.anyio
async def test_start_cas_race_and_heartbeat_never_extend_timing(limit_store):
    manager = RunManager(store=limit_store)
    record = await manager.create_or_reject("start-race")
    try:
        results = await asyncio.gather(limit_store.start_run(record.run_id), limit_store.start_run(record.run_id))
        assert sorted(results) == [False, True]
        timing = deepcopy((await limit_store.get(record.run_id))["run_limits"])
        assert await limit_store.update_lease(record.run_id, owner_worker_id=record.owner_worker_id, lease_expires_at=(datetime.now(UTC) + timedelta(hours=8)).isoformat())
        assert (await limit_store.get(record.run_id))["run_limits"] == timing
    finally:
        await manager.stop_run_limit(record.run_id)


@pytest.mark.anyio
async def test_wall_clock_rollback_does_not_extend_local_prestart_clock(monkeypatch):
    import deerflow.runtime.runs.manager as module

    manager = RunManager(run_config=RunConfig(prestart_wait_seconds=0.02))
    record = await manager.create_or_reject("clock-rollback")

    class BackwardsClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(days=1)

    monkeypatch.setattr(module, "datetime", BackwardsClock)
    await asyncio.wait_for(record.abort_event.wait(), 1)
    task = manager._limit_tasks.get(record.run_id)
    if task is not None:
        await task
    assert record.status == RunStatus.error and record.stop_reason == "prestart_wait_timeout"


@pytest.mark.anyio
async def test_persisted_expired_execution_fences_recovery_when_timeout_claim_fails(limit_store, monkeypatch):
    manager = RunManager(store=limit_store, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.1))
    record = await manager.create_or_reject("partition-deadline")
    entered, unwinding, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class BlockingAgent:
        async def astream(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                unwinding.set()
                await release.wait()
            yield

    original_request_cancel = limit_store.request_cancel
    monkeypatch.setattr(limit_store, "request_cancel", AsyncMock(side_effect=RuntimeError("synthetic timeout-claim write outage")))
    output = bridge()
    task = start_worker(manager, record, output, factory=lambda **kwargs: BlockingAgent())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await limit_store.update_lease(record.run_id, owner_worker_id=record.owner_worker_id, lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
        await asyncio.wait_for(unwinding.wait(), 2)
        stored = await limit_store.get(record.run_id)
        captured = deepcopy(stored["run_limits"])
        assert stored["status"] == "running" and stored["cancel_action"] is None
        assert datetime.fromisoformat(captured["execution_deadline_at"]) <= datetime.now(UTC)
        peer = RunManager(store=limit_store, run_config=RunConfig(prestart_wait_seconds=None, execution_timeout_seconds=None))
        assert await peer.reconcile_orphaned_inflight_runs(error="must not reclaim old file work") == []
        assert await limit_store.claim_for_takeover(record.run_id, grace_seconds=0, error="must not retire") is False
        with pytest.raises(ConflictError):
            await peer.create_or_reject(record.thread_id, multitask_strategy="interrupt")
        assert (await limit_store.get(record.run_id))["run_limits"] == captured
        output.publish_end.assert_not_awaited()
    finally:
        monkeypatch.setattr(limit_store, "request_cancel", original_request_cancel)
        release.set()
        await asyncio.wait_for(task, 2)
    assert (await limit_store.get(record.run_id))["status"] == "timeout"
    output.publish_end.assert_awaited_once()
    replacement = await peer.create_or_reject(record.thread_id)
    assert replacement.run_limits["execution_timeout_seconds"] is None
    assert (await limit_store.get(record.run_id))["run_limits"] == captured


@pytest.mark.anyio
async def test_deadline_during_task_stop_precedes_final_scheduler_callback(limit_store):
    from deerflow.extensions.registry import ExtensionRegistry

    events = MemoryRunEventStore()
    manager = RunManager(store=limit_store, event_store=events, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=0.08))
    record = await manager.create_or_reject("stop-observer")
    stop_entered, release = asyncio.Event(), asyncio.Event()
    order = []

    class Observer:
        async def on_task_start(self, app_store, task_store, info):
            return None

        async def on_task_stop(self, app_store, task_store, info, outcome):
            stop_entered.set()
            await release.wait()
            order.append("stop-drained")

    class CompletedRoot:
        async def astream(self, _input, *, config, **kwargs):
            for handler in config.get("callbacks", []):
                if hasattr(handler, "on_chain_end"):
                    handler.on_chain_end({"messages": []}, run_id=uuid4())
            yield ("values", {"messages": []})

    async def completed(actual):
        assert actual is record and actual.status == RunStatus.timeout
        assert (await limit_store.get(actual.run_id))["status"] == "timeout"
        order.append("completion-timeout")

    registry = ExtensionRegistry()
    with registry.attributed_to("synthetic:install"):
        registry.task_lifecycle(Observer())
    output = bridge()
    record.task = asyncio.create_task(
        run_agent(output, manager, record, ctx=RunContext(checkpointer=None, event_store=events, extensions=registry.build(), on_run_completed=completed), agent_factory=lambda **kwargs: CompletedRoot(), graph_input={}, config={})
    )
    try:
        await asyncio.wait_for(stop_entered.wait(), 2)
        await asyncio.wait_for(record.abort_event.wait(), 2)
        assert record.status == RunStatus.running and not order
        output.publish_end.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(record.task, 2)
    assert order == ["stop-drained", "completion-timeout"]
    assert not any(row["event_type"] == "run.end" for row in await events.list_events(record.thread_id, record.run_id))
    output.publish_end.assert_awaited_once()
