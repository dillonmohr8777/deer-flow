"""Synthetic native HAI route acceptance; no keys, network or real allowances."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_workflow_adapters import SCHEMA, request
from test_workflow_engine import schema_value
from test_workflow_native_runtime import NATIVE_OWNER, create, drain, runtime

from app.gateway.routers.workflows import WorkflowRequest
from app.gateway.workflow_adapters import HAI_MODEL, HAI_ROUTE, MODEL, ROUTE_ENV, AdapterError, WorkflowModelAdapter, worker_environment
from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
from deerflow.workflows.catalog import get_workflow
from deerflow.workflows.engine import WorkflowEngine
from deerflow.workflows.errors import WorkflowResumeError

CONTEXT = {"owner_scope": "synthetic-owner", "actor": "synthetic-actor", "organization": None, "storage_user": "synthetic-actor", "run_id": "synthetic-run", "workflow_id": "synthetic-workflow"}


class SyntheticResponses:
    def __init__(self, *, served_model=HAI_MODEL, error=None):
        self.calls = []
        self.responses = self
        self.served_model = served_model
        self.error = error
        self.close = AsyncMock()

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        schema = kwargs["text"]["format"]["schema"]
        output = schema_value(schema)
        properties = schema["properties"]
        if "approach" in properties:
            output["effort"] = "low"
            output["browser_needed"] = False
        elif "checks" in properties:
            criteria = properties["checks"]["items"]["properties"]["criterion"]["enum"]
            output["approved"] = True
            output["checks"] = [{"criterion": item, "passed": True, "rationale": "Checked only synthetic admitted inputs."} for item in criteria]
        elif "evidence_references" in properties:
            output["evidence_references"] = ["input:source_excerpts"]
        return SimpleNamespace(id="synthetic-response", model=self.served_model, status="completed", output_text=json.dumps(output), output=[], usage=SimpleNamespace(input_tokens=12, output_tokens=8))


def attempts(path):
    with sqlite3.connect(path) as database:
        database.row_factory = sqlite3.Row
        return [dict(row) for row in database.execute("SELECT * FROM workflow_attempts ORDER BY created")]


def selected(monkeypatch, *, client=None, guard=None):
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    return WorkflowModelAdapter(client=client, provider_admission=guard)


@pytest.mark.asyncio
async def test_real_native_maker_checker_uses_fixed_hai_route_shared_meter_and_exact_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    client = SyntheticResponses()
    admissions = []

    async def synthetic_existing_owner_guard(value):
        assert value["owner_scope"] == "synthetic-owner-scope"
        assert value["actor"] == value["storage_user"] == "synthetic-actor"
        assert value["organization"] == "synthetic-org"
        assert value["model"] == HAI_MODEL and value["provider"] == "hai"
        assert value["effort"] == "low" and value["max_output_tokens"] <= 2048
        assert value["input_token_limit"] <= 60000
        assert value["call_id"] in {row["call_id"] for row in attempts(service.path) if row["state"] == "reserved"}
        assert not {"api_key", "base_url", "prompt", "cost", "currency"}.intersection(value)
        admissions.append(value)
        return True  # Synthetic test double, never a live currency allowance.

    adapter = selected(monkeypatch, client=client, guard=synthetic_existing_owner_guard)
    service = WorkflowService(tmp_path / "native.sqlite", checkpointer=InMemorySaver(), adapter=adapter, run_manager=manager, thread_store=threads, event_store=events)
    await service.start()
    try:
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "completed" and result["accepted"] is True
        assert len(client.calls) == len(admissions) == 3
        assert result["usage"]["model_calls"] == 3 and result["usage"]["unknown_model_calls"] == 0
        assert result["usage"]["input_tokens"] == 36 and result["usage"]["output_tokens"] == 24
        assert result["usage"]["cost"] is None
        assert all(row["state"] == "complete" for row in attempts(service.path))
        assert all(row["model"] == HAI_MODEL and row["reasoning"] == {"effort": "low"} and row["store"] is False for row in client.calls)
        assert client.calls[0]["text"]["format"]["schema"]["properties"]["effort"]["enum"] == ["low"]
        native = await manager.get(result["native_run_id"], user_id=NATIVE_OWNER)
        persisted = await store.get(native.run_id, user_id=NATIVE_OWNER)
        assert persisted["model_name"] == HAI_MODEL
        assert persisted["token_usage_by_model"] == {HAI_MODEL: {"input_tokens": 36, "output_tokens": 24}}
        assert await store.get(native.run_id, user_id="foreign-actor") is None
        journal = await events.list_events(result["thread_id"], native.run_id)
        assert all(entry.get("metadata", {}).get("model_name", HAI_MODEL) != MODEL for entry in journal)
        assert (await create(service))["id"] == admitted["id"]
        await drain(service)
        assert len(client.calls) == len(admissions) == 3
    finally:
        await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["denied", "guard_exception", "guard_timeout", "transport_exception"])
async def test_native_guard_denial_or_ambiguity_keeps_reservation_without_replay(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")

    async def guard(_value):
        if mode == "guard_exception":
            raise RuntimeError("hai_SYNTHETIC_SECRET never exposed")
        if mode == "guard_timeout":
            await asyncio.Event().wait()
        return mode != "denied"

    client = SyntheticResponses(error=RuntimeError("hai_SYNTHETIC_SECRET") if mode == "transport_exception" else None)
    adapter = selected(monkeypatch, client=client, guard=guard)
    if mode == "guard_timeout":
        adapter.timeout = 1
    service = WorkflowService(tmp_path / "held.sqlite", checkpointer=InMemorySaver(), adapter=adapter)
    await service.start()
    try:
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "failed" and result["accepted"] is False
        assert result["usage"]["unknown_model_calls"] == result["usage"]["model_calls"] == 1
        assert attempts(service.path)[0]["state"] == "reserved"
        assert attempts(service.path)[0]["reserved_input"] > 0 and attempts(service.path)[0]["reserved_output"] > 0
        assert len(client.calls) == (1 if mode == "transport_exception" else 0)
        assert "SYNTHETIC_SECRET" not in json.dumps(result)
        with pytest.raises(WorkflowServiceError, match="run_not_interrupted"):
            await service.resume("synthetic-owner-scope", admitted["id"])
        hold = attempts(service.path)[0]
        with pytest.raises(WorkflowServiceError, match="uncertain_provider_attempt"):
            await service._storage("reserve_call", admitted["id"], "synthetic-owner-scope", hold["call_id"], hold["fingerprint"], hold["reserved_output"], service.limits, hold["reserved_input"])
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_guard_retains_native_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    entered = asyncio.Event()

    async def guard(_value):
        entered.set()
        await asyncio.Event().wait()

    client = SyntheticResponses()
    service = WorkflowService(tmp_path / "cancel.sqlite", checkpointer=InMemorySaver(), adapter=selected(monkeypatch, client=client, guard=guard))
    await service.start()
    await create(service)
    await asyncio.wait_for(entered.wait(), 5)
    await service.aclose()
    assert not client.calls
    assert len(attempts(service.path)) == 1 and attempts(service.path)[0]["state"] == "reserved"


@pytest.mark.asyncio
@pytest.mark.parametrize("served,expected", [(MODEL, MODEL), ("hai_SYNTHETIC_SECRET", "unverified-provider-model")])
async def test_mismatch_cost_is_unknown_and_usage_is_not_attributed_to_requested_hai(tmp_path, monkeypatch, served, expected):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    store, events, manager, threads = runtime()
    client = SyntheticResponses(served_model=served)
    service = WorkflowService(tmp_path / "mismatch.sqlite", checkpointer=InMemorySaver(), adapter=selected(monkeypatch, client=client, guard=AsyncMock(return_value=True)), run_manager=manager, thread_store=threads, event_store=events)
    await service.start()
    try:
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot("synthetic-owner-scope", admitted["id"])
        assert result["status"] == "failed" and len(client.calls) == 1
        charged = json.loads(attempts(service.path)[0]["result"])
        assert charged["requested_model"] == HAI_MODEL and charged["model"] == expected
        assert charged["served_model"] == (MODEL if served == MODEL else None)
        assert charged["model_identity_verified"] is False and charged["usage"]["cost"] is None
        persisted = await store.get(result["native_run_id"], user_id=NATIVE_OWNER)
        assert persisted["token_usage_by_model"] == {expected: {"input_tokens": 12, "output_tokens": 8}}
        assert "SYNTHETIC_SECRET" not in json.dumps(charged) + json.dumps(persisted)
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_missing_hai_guard_is_unavailable_and_never_uses_default_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_OPENAI_KEY")
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    adapter = selected(monkeypatch)
    assert adapter.capabilities()["langgraph"] == {"available": False, "detail": "provider_allowance_unverified"}
    with pytest.raises(AdapterError, match="provider_allowance_unverified"):
        await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
    assert adapter.client is None
    adapter = selected(monkeypatch, guard=AsyncMock(return_value=True))
    with pytest.raises(AdapterError, match="model_key_missing"):
        await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
    assert adapter.client is None


@pytest.mark.asyncio
async def test_fixed_hai_sdk_configuration_does_not_follow_redirects_or_inherit_proxy(monkeypatch):
    import openai

    monkeypatch.setenv("HAI_API_KEY", "SYNTHETIC_HAI_KEY")
    monkeypatch.setenv("HTTPS_PROXY", "https://untrusted.invalid")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid")
    captured = []
    client = SyntheticResponses()

    def factory(**kwargs):
        captured.append(kwargs)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    adapter = selected(monkeypatch, guard=AsyncMock(return_value=True))
    try:
        assert (await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT))["model"] == HAI_MODEL
        value = captured[0]
        assert value["base_url"] == "https://hai-api.hcloud.ltd/v1" and value["api_key"] == "SYNTHETIC_HAI_KEY"
        assert value["max_retries"] == 0
        assert value["http_client"].follow_redirects is False and value["http_client"]._trust_env is False
    finally:
        await captured[0]["http_client"].aclose()
        await adapter.aclose()


@pytest.mark.asyncio
async def test_real_pinned_sdk_serializes_responses_fields_over_mock_transport(monkeypatch):
    import httpx
    from openai import AsyncOpenAI

    sent = []

    async def synthetic_transport(value):
        sent.append(value)
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 1,
                "model": HAI_MODEL,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "output": [{"type": "message", "id": "msg_synthetic", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": '{"answer":"Synthetic SDK output"}', "annotations": []}]}],
                "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(synthetic_transport), follow_redirects=False, trust_env=False)
    client = AsyncOpenAI(api_key="SYNTHETIC_HAI_KEY", base_url="https://hai-api.hcloud.ltd/v1", max_retries=0, http_client=http_client)
    adapter = selected(monkeypatch, client=client, guard=AsyncMock(return_value=True))
    try:
        result = await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
        assert result["output"] == {"answer": "Synthetic SDK output"}
        assert result["model"] == HAI_MODEL and result["usage"]["cost"] is None
        assert len(sent) == 1 and str(sent[0].url) == "https://hai-api.hcloud.ltd/v1/responses"
        payload = json.loads(sent[0].content)
        assert payload["model"] == HAI_MODEL and payload["store"] is False
        assert payload["reasoning"] == {"effort": "low"}
        assert payload["text"]["format"] == {"type": "json_schema", "name": "workflow_result", "strict": True, "schema": SCHEMA}
        assert not {"provider_admission_context", "api_key", "base_url", "model_extra"}.intersection(payload)
        assert sent[0].headers["Idempotency-Key"] == "scope_run_draft_1"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [{"model": MODEL}, {"effort": "medium"}, {"framework": "crewai"}, {"base_url": "https://untrusted.invalid"}, {"api_key": "hai_SYNTHETIC_SECRET"}])
async def test_hai_model_effort_framework_and_secret_overrides_never_dispatch(monkeypatch, updates):
    client = SyntheticResponses()
    guard = AsyncMock(return_value=True)
    adapter = selected(monkeypatch, client=client, guard=guard)
    with pytest.raises(AdapterError):
        await adapter.call(**request(**{"model": HAI_MODEL, **updates}), provider_admission_context=CONTEXT)
    assert not client.calls and not guard.await_count


def test_unknown_server_route_and_caller_route_fields_fail_closed(monkeypatch):
    monkeypatch.setenv(ROUTE_ENV, "hai_SYNTHETIC_SECRET")
    with pytest.raises(ValueError, match="^workflow_model_route_invalid$"):
        WorkflowModelAdapter()
    with pytest.raises(ValueError):
        WorkflowRequest.model_validate({"workflow_id": "personal-research-note", "inputs": {}, "framework": "langgraph", "provider": "hai", "model": HAI_MODEL, "api_key": "hai_SYNTHETIC_SECRET"})


def test_default_openai_and_framework_environment_preserve_secret_boundaries(monkeypatch):
    monkeypatch.delenv(ROUTE_ENV, raising=False)
    assert WorkflowModelAdapter().model == MODEL
    for key in ("HAI_API_KEY", "HAI_KEY", "OPENAI_API_KEY", ROUTE_ENV):
        monkeypatch.setenv(key, "SYNTHETIC_SECRET")
    assert not any("SYNTHETIC_SECRET" in value for value in worker_environment().values())


@pytest.mark.asyncio
async def test_checkpoint_cannot_switch_provider_without_additional_dispatch():
    definition = get_workflow("personal-research-note")
    engine = WorkflowEngine(InMemorySaver())
    calls = []

    async def model_call(**kwargs):
        calls.append(kwargs)
        schema = kwargs["output_schema"]
        output = schema_value(schema)
        if kwargs["role"] == "verifier":
            criteria = schema["properties"]["checks"]["items"]["properties"]["criterion"]["enum"]
            output["checks"] = [{"criterion": item, "passed": True, "rationale": "Synthetic check."} for item in criteria]
        elif kwargs["role"] != "planner":
            output["evidence_references"] = ["input:source_excerpts"]
        return {"output": output, "model": kwargs["model"], "effort": kwargs["effort"], "usage": {"input_tokens": 12, "output_tokens": 8, "cost": None}}

    async def event(*_args, **_kwargs):
        return None

    kwargs = {"run_id": "synthetic-model-pin", "scope": "synthetic-scope", "framework": "langgraph", "model_call": model_call, "browser_call": None, "event": event}
    assert (await engine.execute(definition, definition.example_inputs, **kwargs))["accepted"]
    count = len(calls)
    with pytest.raises(WorkflowResumeError, match="checkpoint_identity_mismatch"):
        await engine.execute(definition, definition.example_inputs, **kwargs, model=HAI_MODEL, resume=True)
    assert len(calls) == count
