"""Actual CrewAI agency handoffs recover through the shared durable controller.

All provider responses are synthetic. No live model, browser, client or credential
is used; the installed isolated CrewAI Flow/Crew executes its real lifecycle.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.workflow_adapters import WORKERS, WorkflowModelAdapter
from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
from deerflow.persistence.base import Base
from deerflow.persistence.models import RunChangeClockRow, RunRow, ThreadMetaRow
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context
from deerflow.workflows.catalog import get_workflow


def _value(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if schema["type"] == "object":
        return {key: _value(value) for key, value in schema["properties"].items()}
    if schema["type"] == "array":
        return [_value(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if schema["type"] == "boolean":
        return True
    return "Synthetic operator step grounded in the supplied process notes."


class SyntheticProvider:
    def __init__(self):
        self.responses = self
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["text"]["format"]["schema"]
        output = _value(schema)
        assert isinstance(output, dict)
        if "checks" in schema["properties"]:
            criteria = schema["properties"]["checks"]["items"]["properties"]["criterion"]["enum"]
            output["checks"] = [{"criterion": criterion, "passed": True, "rationale": "Synthetic review of admitted fixture."} for criterion in criteria]
        elif "evidence_references" in output:
            output["evidence_references"] = ["input:process_notes"]
        return SimpleNamespace(id="offline-response", model=kwargs["model"], status="completed", output=[], output_text=json.dumps(output), usage=SimpleNamespace(input_tokens=40, output_tokens=20))


class RecordingAdapter(WorkflowModelAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.admissions = []

    async def call(self, **kwargs):
        self.admissions.append(kwargs)
        return await super().call(**kwargs)


@pytest.mark.asyncio
async def test_actual_crewai_agency_restart_preserves_receipts_budget_and_private_sql_journal(tmp_path, monkeypatch):
    worker_root = Path(os.environ.get("MOMOBOT_TEST_WORKER_ROOT", str(WORKERS))).resolve()
    if not (worker_root / "python/.venv/bin/python").is_file():
        pytest.skip("isolated CrewAI worker environment is not installed")
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native.sqlite'}")
    factory = async_sessionmaker(db, expire_on_commit=False)
    async with db.begin() as connection:
        tables = [Base.metadata.tables[row.__tablename__] for row in (OrganizationRow, ProjectRow, ThreadMetaRow, RunRow, RunChangeClockRow, RunEventRow)]
        await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))
    store, threads, events = RunRepository(factory), ThreadMetaRepository(factory), DbRunEventStore(factory)
    provider = SyntheticProvider()
    arrived = asyncio.Event()

    class PauseBeforeVerification(WorkflowService):
        async def _event(self, data, name, status, **details):
            await super()._event(data, name, status, **details)
            if name == "verify" and status == "running":
                arrived.set()
                await asyncio.Event().wait()

    path, checkpoints = tmp_path / "ledger.sqlite", str(tmp_path / "checkpoints.sqlite")
    definition = get_workflow("standard-operating-procedure")
    owner = "synthetic-agency-owner"
    native_owner = "wf_" + hashlib.sha256(b"momo-workflow-native\0" + owner.encode()).hexdigest()[:60]

    def service(saver, adapter, cls=WorkflowService):
        result = cls(path, checkpointer=saver, adapter=adapter, run_manager=RunManager(store=store, event_store=events), thread_store=threads, event_store=events)
        result.limits.update(max_output_tokens_per_run=256, max_input_tokens_per_run=60000)
        return result

    try:
        async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
            first_adapter = RecordingAdapter(client=provider, worker_root=worker_root)
            first = service(saver, first_adapter, PauseBeforeVerification)
            await first.start()
            try:
                admitted = await first.create(owner, definition.id, definition.example_inputs, "crewai", "synthetic-sop", actor="synthetic-actor", organization=None, storage_user="synthetic-actor")
                await asyncio.wait_for(arrived.wait(), 60)
            finally:
                await first.aclose()
            prior = first._db("get", admitted["id"], owner)
            assert isinstance(prior, dict)
            assert prior["status"] == "interrupted"
            assert prior["usage"]["model_calls"] == 2 and prior["usage"]["unknown_model_calls"] == 0
            assert not first_adapter.active_workers
        async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
            resumed_adapter = RecordingAdapter(client=provider, worker_root=worker_root)
            resumed = service(saver, resumed_adapter)
            await resumed.start()
            try:
                with pytest.raises(WorkflowServiceError, match="not_found"):
                    await resumed.resume("foreign-owner", admitted["id"])
                await resumed.resume(owner, admitted["id"])
                for _ in range(12):
                    if resumed.pump_task is not None:
                        await asyncio.wait_for(asyncio.shield(resumed.pump_task), 60)
                    pending = list(resumed.tasks.values())
                    if not pending:
                        break
                    await asyncio.wait_for(asyncio.gather(*pending), 60)
                else:
                    raise AssertionError("Workflow admission did not drain")
                final = await resumed.snapshot(owner, admitted["id"])
                assert final["status"] == "completed" and final["accepted"] is True
                assert final["usage"] == {"model_calls": 3, "input_tokens": 120, "output_tokens": 60, "cost": None, "unknown_model_calls": 0, "complete": True}
                assert len(provider.calls) == 3
                assert [call["max_output_tokens"] for call in provider.calls] == [256, 236, 216]
                assert resumed_adapter.admissions[0]["input_token_limit"] == 59920
                assert len(resumed_adapter.admissions) == 1 and resumed_adapter.admissions[0]["role"] == "verifier"
                ids = [call["extra_headers"]["Idempotency-Key"] for call in provider.calls]
                assert len(set(ids)) == 3
                with sqlite3.connect(path) as ledger:
                    attempts = ledger.execute("SELECT state,call_id FROM workflow_attempts WHERE run_id=?", (admitted["id"],)).fetchall()
                assert set(attempts) == {("complete", call_id) for call_id in ids}
                native_rows = [await store.get(run_id, user_id=native_owner) for run_id in (prior["native_run_id"], final["native_run_id"])]
                native = [row for row in native_rows if row is not None]
                assert len(native) == 2
                assert sum(row["llm_call_count"] for row in native) == 3
                assert sum(row["total_input_tokens"] for row in native) == 120
                assert sum(row["total_output_tokens"] for row in native) == 60
                assert await store.get(final["native_run_id"], user_id="synthetic-actor") is None
                context = set_storage_context(WorkspaceStorageContext("synthetic-actor", None, native_owner))
                try:
                    messages = await events.list_messages(final["thread_id"], user_id=native_owner)
                finally:
                    reset_storage_context(context)
                assert len(messages) == 3
                assert {message["metadata"]["call_id"] for message in messages} == set(ids)
                artifact = await resumed.artifact(owner, admitted["id"])
                assert hashlib.sha256(artifact).hexdigest() == final["artifact"]["sha256"]
                assert json.loads(artifact)["output"]["workflow_id"] == definition.id
                assert not resumed_adapter.active_workers
            finally:
                await resumed.aclose()
    finally:
        await db.dispose()
