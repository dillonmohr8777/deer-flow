"""Durable workflow admission, scope, payment and artifact boundaries."""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.workflow_service import WorkflowService, WorkflowServiceError

pytestmark = pytest.mark.asyncio


class Adapter:
    def capabilities(self):
        return {"langgraph": {"available": True, "detail": "test transport"}}

    async def call(self, **kwargs):
        return {"output": {"ok": True}, "model": "gpt-6.1-sol", "effort": kwargs["effort"], "usage": {"input_tokens": 10, "output_tokens": 10, "cost": None}}


@pytest_asyncio.fixture
async def service(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    value = WorkflowService(tmp_path / "workflows.sqlite", checkpointer=InMemorySaver(), adapter=Adapter(), engine=object())
    await value.start()
    try:
        yield value
    finally:
        await value.aclose()


async def _admit(service, owner, key):
    import uuid

    data = {
        "id": str(uuid.uuid4()),
        "workflow_id": "synthetic-local-test",
        "framework": "langgraph",
        "status": "running",
        "title": "Synthetic transport test",
        "_scope": owner,
        "created_at": "test",
        "updated_at": "test",
        "usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": None},
        "steps": [],
        "artifact": None,
    }
    return (await service._storage("admit", data, key, key, service.limits))[0]


async def test_call_receipt_is_reused_and_other_scope_cannot_read(service):
    data = await _admit(service, "owner", "one")
    args = {"call_id": "step-1", "worker_id": "planner", "role": "planner", "prompt": "Bounded synthetic test", "output_schema": {"type": "object"}, "model": "gpt-6.1-sol", "effort": "low", "continuation": []}
    first = await service._model(data, **args)
    second = await service._model(data, **args)
    assert first == second
    assert (await service.snapshot("owner", data["id"]))["usage"]["model_calls"] == 1
    with pytest.raises(WorkflowServiceError, match="not_found"):
        await service.snapshot("other", data["id"])


async def test_uncertain_provider_attempt_cannot_retry_or_refund(service):
    data = await _admit(service, "owner", "one")
    await service._storage("reserve_call", data["id"], "owner", "uncertain", "fp", 128, service.limits)
    with pytest.raises(WorkflowServiceError, match="uncertain_provider_attempt"):
        await service._storage("reserve_call", data["id"], "owner", "uncertain", "fp", 128, service.limits)
    assert (await service.snapshot("owner", data["id"]))["usage"]["model_calls"] == 1


async def test_atomic_global_call_budget(service):
    service.limits["max_model_calls_per_day"] = 1
    values = await asyncio.gather(*(_admit(service, "owner", str(i)) for i in range(2)))
    results = await asyncio.gather(*(service._storage("reserve_call", value["id"], "owner", "call", "fp", 128, service.limits) for value in values), return_exceptions=True)
    assert sum(isinstance(value, WorkflowServiceError) for value in results) == 1


async def test_symlink_database_fails_before_io(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    real = tmp_path / "target"
    real.write_text("untouched")
    path = tmp_path / "workflows.sqlite"
    path.symlink_to(real)
    value = WorkflowService(path, checkpointer=InMemorySaver(), adapter=Adapter())
    with pytest.raises(WorkflowServiceError, match="unsafe_state_path"):
        await value.start()
    assert real.read_text() == "untouched"


async def test_queue_cancel_and_artifact_hash_readback(service):
    data = await _admit(service, "owner", "one")
    cancelled = await service.cancel("owner", data["id"])
    assert cancelled["status"] == "cancelled"
    with pytest.raises(WorkflowServiceError, match="artifact_unavailable"):
        await service.artifact("owner", data["id"])
    data = await _admit(service, "owner", "artifact")
    payload = {"output": {"useful": "actual local result"}, "evidence": [], "accepted": True}
    await service._write_artifact(data, payload)
    await service._storage("terminal", data["id"], "owner", {"status": "completed", "accepted": True})
    loaded = await service.artifact("owner", data["id"])
    assert b"actual local result" in loaded
    assert Path(service.path).stat().st_mode & 0o077 == 0


async def test_input_headroom_is_reserved_before_adapter_dispatch(service):
    data = await _admit(service, "owner", "input-budget")
    service.limits["max_input_tokens_per_run"] = 1
    called = 0

    async def call(**kwargs):
        nonlocal called
        called += 1
        return await Adapter().call(**kwargs)

    service.adapter.call = call
    with pytest.raises(WorkflowServiceError, match="run_token_budget_exhausted"):
        await service._model(data, call_id="input-step", worker_id="planner", role="planner", prompt="Bounded request", output_schema={"type": "object"}, model="gpt-6.1-sol", effort="low", continuation=[])
    assert called == 0


async def test_high_effort_ceiling_remains_inside_original_run_budget(service):
    data = await _admit(service, "owner", "high-effort-budget")
    received = []
    original = service.adapter.call

    async def call(**kwargs):
        received.append(kwargs["max_output_tokens"])
        return await original(**kwargs)

    service.adapter.call = call
    args = {"worker_id": "producer", "role": "producer", "prompt": "Bounded request", "output_schema": {"type": "object"}, "model": "gpt-6.1-sol", "effort": "high", "continuation": []}
    await service._model(data, call_id="high-first", **args)
    assert received == [4096]
    # Completed usage, rather than the original reservation, determines the
    # remaining shared ceiling. Never forward more than that remaining budget.
    service.limits["max_output_tokens_per_run"] = 5010
    await service._model(data, call_id="high-second", **args)
    assert received == [4096, 4096]
    service.limits["max_output_tokens_per_run"] = 1020
    await service._model(data, call_id="high-third", **args)
    assert received == [4096, 4096, 1000]


async def test_stagehand_availability_requires_installed_configured_broker_and_extension(service, monkeypatch):
    from types import SimpleNamespace

    service.adapter.capabilities = lambda: {"langgraph": {"available": True, "detail": "synthetic broker"}, "stagehand": {"available": True, "detail": "installed worker"}}
    service.browser_service = SimpleNamespace(started=True)
    monkeypatch.setenv("BROWSERBASE_API_KEY", "synthetic-model-free-test")
    monkeypatch.delenv("MOMOBOT_STAGEHAND_EXTENSION_ID", raising=False)
    assert (await service.capabilities())["stagehand"]["available"] is False
    monkeypatch.setenv("MOMOBOT_STAGEHAND_EXTENSION_ID", "invalid-extension")
    assert (await service.capabilities())["stagehand"]["available"] is False
    monkeypatch.setenv("MOMOBOT_STAGEHAND_EXTENSION_ID", "00000000-0000-4000-8000-000000000000")
    assert (await service.capabilities())["stagehand"]["available"] is True
    service.browser_service.started = False
    assert (await service.capabilities())["stagehand"]["available"] is False


async def test_uncertain_usage_is_reported_as_incomplete(service):
    data = await _admit(service, "owner", "uncertain-usage")
    await service._storage("reserve_call", data["id"], "owner", "uncertain", "fp", 128, service.limits)
    usage = (await service.snapshot("owner", data["id"]))["usage"]
    assert usage["complete"] is False
    assert usage["unknown_model_calls"] == 1


async def test_cached_receipt_replays_even_when_output_budget_is_spent(service):
    data = await _admit(service, "owner", "replay-budget")
    args = {"call_id": "step-1", "worker_id": "planner", "role": "planner", "prompt": "Bounded synthetic test", "output_schema": {"type": "object"}, "model": "gpt-6.1-sol", "effort": "low", "continuation": []}
    first = await service._model(data, **args)
    service.limits["max_output_tokens_per_run"] = 10
    assert await service._model(data, **args) == first


async def test_native_admission_is_closed_when_ledger_patch_fails(service):
    from types import SimpleNamespace

    from deerflow.runtime.runs.manager import RunStartOutcome

    data = await _admit(service, "owner", "native-failure")
    data.update(_storage_user="owner", _actor="owner", _organization="org")
    record = SimpleNamespace(run_id="native-test", idempotency_reused=False, task=None)
    closed = []

    class Manager:
        async def create_or_reject(self, *_args, **_kwargs):
            return record

        async def try_start(self, *_args):
            return RunStartOutcome.started

        async def update_run_completion(self, *_args, **_kwargs):
            return None

        async def set_status_if_not_cancelled(self, run_id, state, **_kwargs):
            closed.append((run_id, state))

    service.run_manager = Manager()
    storage = service._storage

    async def fail(action, *args):
        if action == "patch":
            raise WorkflowServiceError("simulated_storage_failure", 503)
        return await storage(action, *args)

    service._storage = fail
    with pytest.raises(WorkflowServiceError, match="simulated_storage_failure"):
        await service._native_start(data)
    assert len(closed) == 1
