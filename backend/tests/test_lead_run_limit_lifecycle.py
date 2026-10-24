"""Promoted desired-contract regressions from independent lifecycle review v4.

Source probe SHA256 a72f978a4682d8b29304aaf7c8abd3ee28ac33b25dbd49ec468917009532d491.
Only its two accepted findings are promoted. A draining worker must stay alive,
so observations wait for cleanup entry rather than awaiting terminal completion.
"""

import asyncio
import importlib
import sys
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.run_config import RunConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


def output_bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("store_kind", ["memory", "sql"])
@pytest.mark.parametrize("failed_claim", [False, True])
async def test_actual_services_timeout_keeps_metadata_cleanup_owned(monkeypatch, tmp_path, store_kind, failed_claim):
    from app.gateway import services
    from app.gateway.deps import langgraph_runtime
    from app.gateway.run_models import RunCreateRequest

    metadata_entered, metadata_cancelling, release, metadata_drained = [asyncio.Event() for _ in range(4)]
    metadata_tasks = []

    async def metadata(*args, **kwargs):
        metadata_tasks.append(asyncio.current_task())
        metadata_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            metadata_cancelling.set()
            await release.wait()
            metadata_drained.set()

    factory = Mock(side_effect=AssertionError("prestart timeout must not build agent"))
    monkeypatch.setattr(services, "_ensure_thread_metadata", metadata)
    monkeypatch.setattr(services, "resolve_agent_factory", lambda *args, **kwargs: factory)
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "memory"}, "run": {"prestart_wait_seconds": 0.2, "execution_timeout_seconds": 1}})
    set_app_config(config)
    engine = None
    try:
        app = FastAPI()
        async with langgraph_runtime(app, config):
            if store_kind == "sql":
                from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

                import deerflow.persistence.models  # noqa: F401
                from deerflow.persistence.base import Base
                from deerflow.persistence.run.sql import RunRepository

                # Keep actual services/deps/RunManager orchestration. Supply a
                # real SQL run adapter without changing memory runtime globals.
                engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'preflight.db'}")
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                app.state.run_store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
                app.state.run_manager._store = app.state.run_store
            run_store = app.state.run_store
            if failed_claim:
                monkeypatch.setattr(run_store, "request_cancel", AsyncMock(side_effect=RuntimeError("synthetic prestart claim outage")))
            original_end = app.state.stream_bridge.publish_end
            end = AsyncMock(wraps=original_end)
            app.state.stream_bridge.publish_end = end
            app.state.run_manager._on_unstarted_limit = end
            request = SimpleNamespace(headers={}, state=SimpleNamespace(), app=app)
            body = RunCreateRequest(input={"messages": [{"role": "user", "content": "synthetic service preflight check"}]})
            record = await services.start_run(body, "independent-metadata-drain", request)
            try:
                await asyncio.wait_for(metadata_entered.wait(), 2)
                await asyncio.wait_for(metadata_cancelling.wait(), 5)
                await app.state.run_manager.cancel(record.run_id, action="rollback")
                # Repeated host cancellation must not detach the actual child.
                record.task.cancel()
                await asyncio.sleep(0)
                record.task.cancel()
                for _ in range(10):
                    await asyncio.sleep(0)
                stored = await app.state.run_store.get(record.run_id)
                observed = {
                    "worker_entered": record.worker_entered,
                    "worker_done": record.task.done(),
                    "metadata_drained": metadata_drained.is_set(),
                    "metadata_task_done": metadata_tasks[0].done(),
                    "local_status": record.status.value,
                    "stored_status": stored["status"],
                    "stop_reason": record.stop_reason,
                    "end_published": record.end_published,
                    "finalizing": record.finalizing,
                }
                # A cancelled awaiter is not proof that its owned metadata coroutine drained.
                assert not record.end_published and stored["status"] == "pending" and not record.task.done(), observed
                assert record.finalizing and not metadata_drained.is_set()
                assert record.abort_action == "prestart_timeout"
                assert stored["cancel_action"] == (None if failed_claim else "prestart_timeout")
                assert await run_store.update_lease(record.run_id, owner_worker_id=record.owner_worker_id, lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
                peer = RunManager(store=run_store)
                assert await peer.reconcile_orphaned_inflight_runs(error="must not reclaim metadata") == []
                assert not await run_store.claim_for_takeover(record.run_id, grace_seconds=0, error="must not retire metadata")
                with pytest.raises(ConflictError):
                    await peer.create_or_reject(record.thread_id, multitask_strategy="interrupt")
            finally:
                release.set()
                await asyncio.gather(*metadata_tasks, return_exceptions=True)
                await asyncio.wait_for(asyncio.gather(record.task, return_exceptions=True), 5)
            assert metadata_drained.is_set() and not record.finalizing and record.end_published
            assert (await run_store.get(record.run_id))["status"] == "error"
            assert record.stop_reason == "prestart_wait_timeout"
            end.assert_awaited_once_with(record.run_id)
            replacement = await peer.create_or_reject(record.thread_id)
            await peer.cancel(replacement.run_id)
            await peer.stop_run_limit(replacement.run_id)
            factory.assert_not_called()
    finally:
        reset_app_config()
        if engine is not None:
            await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["interrupt", "rollback", "shutdown"])
async def test_interrupt_during_actual_child_cleanup_still_finishes_worker(monkeypatch, stop):
    action = "interrupt" if stop == "shutdown" else stop
    from deerflow.runtime.runs.owned_children import OWNED_CHILDREN_CONTEXT_KEY
    from deerflow.subagents.config import SubagentConfig

    # The repository conftest pre-mocks executor for an inherited circular import.
    # All package dependencies are now loaded; remove only that mock for this probe.
    previous = sys.modules.pop("deerflow.subagents.executor", None)
    module = importlib.import_module("deerflow.subagents.executor")
    child_cleanup_entered, release, child_cleanup_drained = [threading.Event() for _ in range(3)]

    async def child_cleanup(_owner):
        child_cleanup_entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        child_cleanup_drained.set()

    async def lead_cleanup(_runtime):
        return None

    class ChildAgent:
        async def astream(self, _state, *, context, **kwargs):
            context["sandbox_id"] = "synthetic-child-cleanup"
            yield {"messages": []}

    monkeypatch.setattr(module, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    executor = module.SubagentExecutor(
        config=SubagentConfig(name="synthetic-owned", description="offline", max_turns=2, timeout_seconds=30), tools=[], parent_model="synthetic", thread_id="independent-child-drain", run_id="synthetic-parent"
    )
    monkeypatch.setattr(executor, "_build_initial_state", AsyncMock(return_value=({"messages": []}, [], None)))
    monkeypatch.setattr(executor, "_create_agent", lambda *args, **kwargs: ChildAgent())
    monkeypatch.setattr("deerflow.sandbox.get_sandbox_provider", lambda: object())
    monkeypatch.setattr("deerflow.sandbox.lease.get_sandbox_lease_manager", lambda _provider: SimpleNamespace(release_async=child_cleanup))
    monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", lead_cleanup)
    tracker_holder, child_ids = [], []

    class LeadAgent:
        async def astream(self, _input, *, config, **kwargs):
            tracker = config["context"][OWNED_CHILDREN_CONTEXT_KEY]
            tracker_holder.append(tracker)
            child_ids.append(executor.execute_async("synthetic child", owned_children=tracker))
            while not child_cleanup_entered.is_set():
                await asyncio.sleep(0.005)
            yield ("values", {"messages": []})

    store, events, bridge = MemoryRunStore(), MemoryRunEventStore(), output_bridge()
    manager = RunManager(store=store, event_store=events, run_config=RunConfig(prestart_wait_seconds=1, execution_timeout_seconds=30))
    record = await manager.create_or_reject("independent-child-drain")

    async def completion(actual):
        assert actual is record and child_cleanup_drained.is_set()
        assert tracker_holder[0]._children[0].confirmed
        assert actual.status == (RunStatus.interrupted if action == "interrupt" else RunStatus.error)
        assert (await store.get(actual.run_id))["status"] == actual.status.value

    completed = AsyncMock(side_effect=completion)
    record.task = manager.create_worker_task(
        record,
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=events, app_config=AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}), on_run_completed=completed),
            agent_factory=lambda **kwargs: LeadAgent(),
            graph_input={},
            config={},
        ),
    )
    try:
        async with asyncio.timeout(10):
            while not (child_cleanup_entered.is_set() and record.finalizing):
                await asyncio.sleep(0.005)
        if stop == "shutdown":
            await manager.shutdown(timeout=0.1)
        else:
            await manager.cancel(record.run_id, action=action)
        await manager.cancel(record.run_id, action="rollback" if action == "interrupt" else "interrupt")
        record.task.cancel()
        await asyncio.sleep(0)
        record.task.cancel()
        for _ in range(10):
            await asyncio.sleep(0)
        observed = {
            "worker_done": record.task.done(),
            "worker_cancelled": record.task.cancelled(),
            "child_cleanup_drained": child_cleanup_drained.is_set(),
            "child_completion_set": tracker_holder[0]._children[0].completed.is_set(),
            "status": record.status.value,
            "stored_status": (await store.get(record.run_id))["status"],
            "finalizing": record.finalizing,
            "abort_action": record.abort_action,
            "end_count": bridge.publish_end.await_count,
            "completion_count": completed.await_count,
        }
        assert not record.task.done() and record.finalizing and observed["stored_status"] == "running", observed
        assert record.abort_action == action and (await store.get(record.run_id))["cancel_action"] == action
        assert await store.update_lease(record.run_id, owner_worker_id=record.owner_worker_id, lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
        peer = RunManager(store=store)
        assert await peer.reconcile_orphaned_inflight_runs(error="must not reclaim child cleanup") == []
        assert not await store.claim_for_takeover(record.run_id, grace_seconds=0, error="must not retire child cleanup")
        with pytest.raises(ConflictError):
            await peer.create_or_reject(record.thread_id, multitask_strategy="interrupt")
        # Interrupt must preserve owned drain and eventually release the barrier/END.
        release.set()
        async with asyncio.timeout(10):
            while not (child_cleanup_drained.is_set() and tracker_holder[0]._children[0].completed.is_set()):
                await asyncio.sleep(0.005)
        await asyncio.wait_for(asyncio.gather(record.task, return_exceptions=True), 5)
        after = {
            "actual_child_drained": child_cleanup_drained.is_set(),
            "owned_handle_completed": tracker_holder[0]._children[0].completed.is_set(),
            "owned_handle_confirmed": tracker_holder[0]._children[0].confirmed,
            "worker_done": record.task.done(),
            "worker_cancelled": record.task.cancelled(),
            "finalizing": record.finalizing,
            "end_count": bridge.publish_end.await_count,
            "completion_count": completed.await_count,
        }
        assert bridge.publish_end.await_count == 1 and not record.finalizing, after
        assert completed.await_count == 1 and completed.await_args.args[0] is record
        assert record.abort_action == action and record.status == (RunStatus.interrupted if action == "interrupt" else RunStatus.error)
        assert (await store.get(record.run_id))["status"] == record.status.value
        replacement = await peer.create_or_reject(record.thread_id)
        await peer.cancel(replacement.run_id)
        await peer.stop_run_limit(replacement.run_id)
    finally:
        release.set()
        for execution_id in child_ids:
            module.cleanup_background_task(execution_id)
        if not record.task.done():
            record.task.cancel()
            await asyncio.gather(record.task, return_exceptions=True)
        await manager.stop_run_limit(record.run_id)
        if previous is None:
            sys.modules.pop("deerflow.subagents.executor", None)
        else:
            sys.modules["deerflow.subagents.executor"] = previous
