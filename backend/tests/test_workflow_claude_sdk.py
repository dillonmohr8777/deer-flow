"""Offline checks of the existing SDK worker's narrow workflow bridge."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.workflow_adapters import AdapterError, WorkflowModelAdapter
from app.gateway.workflow_claude_sdk import MODEL, SOURCE_WORKFLOW, ClaudeSDKBridge
from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
from deerflow.workflows.catalog import get_workflow


def request():
    return dict(
        worker_id="maker",
        call_id="wc_" + "a" * 64,
        framework="claude_sdk",
        model=MODEL,
        effort="low",
        max_output_tokens=256,
        input_token_limit=60000,
        role="maker",
        prompt="Use the synthetic source.",
        continuation=[],
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False},
    )


def context():
    return dict(owner_scope="owner", run_id="run", workflow_id=SOURCE_WORKFLOW, source_sha256="b" * 64)


def response(job, output=None, tools_used=None, usage=None):
    value = dict(
        job_id=job["job_id"],
        ok=True,
        outcome="completed",
        attempts=1,
        models=[MODEL],
        observed_models=[MODEL],
        requested_model=MODEL,
        usage={"input_tokens": 10, "output_tokens": 6, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3},
        cost_usd=0.002,
        cost_known=True,
        cost_is_estimate=True,
        verification="synthetic_output_checked",
        session_hash="d" * 64,
        tools_used=[],
        tools_succeeded=[],
        failed_sources=[],
        denied_count=0,
        result={"text": '{"answer":"Synthetic result"}', "source_refs": [], "failed_sources": []},
    )
    if output is not None:
        value["result"]["text"] = json.dumps(output)
    if tools_used is not None:
        value["tools_used"] = tools_used
    if usage is not None:
        value["usage"] = usage
    row = {key: val for key, val in value.items() if key != "result"}
    row.update(at="synthetic-time", event="finished", policy_hash="e" * 64, output_sha256=hashlib.sha256(json.dumps(value["result"], sort_keys=True).encode()).hexdigest())
    raw = (json.dumps(row) + "\n").encode()
    path = Path(os.environ["MOMOBOT_CLAUDE_SDK_RECEIPTS"])
    with path.open("ab") as stream:
        stream.write(raw)
    value.update(receipt_sha256=hashlib.sha256(raw).hexdigest(), persistence="receipt_readback_confirmed")
    return value


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_CLAUDE_SDK_RECEIPTS", str(tmp_path / "worker-receipts.jsonl"))


def configured(monkeypatch, handler):
    monkeypatch.setenv("MOMOBOT_CLAUDE_SDK_ENABLED", "true")
    monkeypatch.setenv("MOMOBOT_CLAUDE_SDK_URL", "http://127.0.0.1:18878/run")
    monkeypatch.setenv("MOMOBOT_CLAUDE_SDK_TOKEN", "synthetic-local-token")
    return ClaudeSDKBridge(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_default_off_and_no_transport(monkeypatch):
    monkeypatch.delenv("MOMOBOT_CLAUDE_SDK_ENABLED", raising=False)
    bridge = ClaudeSDKBridge(transport=httpx.MockTransport(lambda _: pytest.fail("disabled bridge sent HTTP")))
    assert bridge.capability()["available"] is False
    with pytest.raises(AdapterError, match="claude_sdk_unavailable"):
        await bridge.call(request(), context())


@pytest.mark.asyncio
async def test_stable_scoped_job_no_tools_and_rich_receipt(monkeypatch):
    jobs = []

    def handler(req):
        assert req.headers["authorization"] == "Bearer synthetic-local-token"
        job = json.loads(req.content)
        jobs.append(job)
        return httpx.Response(200, json=response(job))

    bridge = configured(monkeypatch, handler)
    adapter = WorkflowModelAdapter(claude_sdk=bridge)
    result = await adapter.call(**request(), provider_admission_context=context())
    assert jobs[0]["allowed_tools"] == [] and jobs[0]["data_class"] == "synthetic"
    assert jobs[0]["max_budget_usd"] == 0.03
    assert jobs[0]["max_attempts"] == 1
    assert result["output"] == {"answer": "Synthetic result"}
    assert result["usage"]["input_tokens"] == 15
    assert result["sdk_receipt"]["source_sha256"] == context()["source_sha256"]
    assert "synthetic-local-token" not in json.dumps(result)
    other = await bridge.call(request(), dict(context(), owner_scope="other"))
    assert other["sdk_receipt"]["job_id"] != result["sdk_receipt"]["job_id"]


@pytest.mark.parametrize("url", ["https://example.com/run", "http://localhost:18878/run", "http://user:pass@127.0.0.1:18878/run", "http://127.0.0.1:18878/run?key=x"])
def test_unsafe_endpoint_is_unavailable(monkeypatch, url):
    bridge = configured(monkeypatch, lambda _: pytest.fail("unsafe endpoint sent HTTP"))
    monkeypatch.setenv("MOMOBOT_CLAUDE_SDK_URL", url)
    assert ClaudeSDKBridge().capability()["available"] is False
    assert bridge.capability()["available"] is True


@pytest.mark.parametrize(
    "change",
    [
        dict(job_id="wrong"),
        dict(observed_models=["claude-sonnet-5-5"]),
        dict(attempts=2),
        dict(cost_known=False),
        dict(tools_used=["Bash"]),
        dict(receipt_sha256="bad"),
        dict(usage={"input_tokens": True, "output_tokens": 3}),
        dict(result={"text": '{"answer":"x","extra":1}', "source_refs": [], "failed_sources": []}),
    ],
)
@pytest.mark.asyncio
async def test_invalid_receipts_are_uncertain_no_retry(monkeypatch, change):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={**response(json.loads(req.content)), **change})

    bridge = configured(monkeypatch, handler)
    with pytest.raises(AdapterError):
        await bridge.call(request(), context())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_redirect_retry_or_exception_text(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(302, headers={"Location": "https://external.example/"})

    bridge = configured(monkeypatch, handler)
    with pytest.raises(AdapterError, match="claude_sdk_outcome_uncertain"):
        await bridge.call(request(), context())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fixture_admission_and_source_change_gate(tmp_path, monkeypatch):
    bridge = configured(monkeypatch, lambda _: pytest.fail("source gate must precede HTTP"))
    service = WorkflowService(tmp_path / "jobs.sqlite", checkpointer=InMemorySaver(), adapter=WorkflowModelAdapter(claude_sdk=bridge))
    service.started = True
    definition = get_workflow(SOURCE_WORKFLOW)
    inputs = definition.example_inputs
    with pytest.raises(WorkflowServiceError, match="claude_sdk_source_denied"):
        await service.create("owner", SOURCE_WORKFLOW, dict(inputs, brief="private text"), "claude_sdk", "one", actor="a", organization=None, storage_user="a")
    with pytest.raises(WorkflowServiceError, match="claude_sdk_source_denied"):
        await service.create("owner", SOURCE_WORKFLOW, inputs, "claude_sdk", "one", actor="a", organization=None, storage_user="a", supervisor=True)
    source_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert service._claude_source({"workflow_id": SOURCE_WORKFLOW, "_inputs": inputs, "_claude_source_sha256": source_hash, "_sdk_configuration_sha256": bridge.configuration_sha256}) == source_hash
    with pytest.raises(WorkflowServiceError, match="claude_sdk_source_denied"):
        service._claude_source({"workflow_id": SOURCE_WORKFLOW, "_inputs": dict(inputs, brief="private"), "_claude_source_sha256": source_hash, "_sdk_configuration_sha256": bridge.configuration_sha256})


@pytest.mark.asyncio
async def test_graph_native_receipts_artifact_replay_and_owner(tmp_path, monkeypatch):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    calls = []

    def handler(req):
        job = json.loads(req.content)
        calls.append(job)
        admitted = json.loads(job["brief"].split("\n", 1)[1])
        schema = admitted["output_schema"]["properties"]
        if admitted["role"] == "planner":
            output = dict(approach=["Preserve source meaning and author voice."], producer_role="general_specialist", effort="low", browser_needed=False)
        elif admitted["role"] == "verifier":
            criteria = schema["checks"]["items"]["properties"]["criterion"]["enum"]
            output = dict(approved=True, output_sha256=schema["output_sha256"]["const"], checks=[dict(criterion=criterion, passed=True, rationale="Matches the supplied synthetic passage.") for criterion in criteria], findings=[])
        else:
            output = dict(workflow_id=SOURCE_WORKFLOW, status="draft", assumptions=[], evidence_references=["input:manuscript_excerpt"], edited_passages=["Synthetic edited passage."], editorial_notes=["Preserved meaning and voice."])
        return httpx.Response(200, json=response(job, output))

    bridge = configured(monkeypatch, handler)
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    events, store = MemoryRunEventStore(), MemoryRunStore()
    manager = RunManager(store=store, event_store=events)
    threads = MemoryThreadMetaStore(InMemoryStore())
    service = WorkflowService(tmp_path / "jobs.sqlite", checkpointer=InMemorySaver(), adapter=WorkflowModelAdapter(claude_sdk=bridge), run_manager=manager, thread_store=threads, event_store=events)
    await service.start()
    definition = get_workflow(SOURCE_WORKFLOW)
    try:
        args = dict(actor="synthetic-actor", organization=None, storage_user="synthetic-actor")
        created = await service.create("owner", definition.id, definition.example_inputs, "claude_sdk", "proof", **args)
        if service.pump_task:
            await service.pump_task
        await asyncio.gather(*service.tasks.values())
        final = await service.snapshot("owner", created["id"])
        assert final["status"] == "completed", final["error"]
        assert final["usage"]["model_calls"] == len(calls) == 3
        assert final["usage"]["input_tokens"] == 45
        assert final["usage"]["cost"] == 0.006 and final["cost_is_estimate"]
        assert len(final["sdk_receipts"]) == 3
        artifact = json.loads(await service.artifact("owner", created["id"]))
        assert artifact["sdk_receipts"] == final["sdk_receipts"]
        assert artifact["source"]["data_class"] == "synthetic"
        full = await service._storage("get", final["id"], "owner")
        await service._storage("patch", final["id"], "owner", {"sdk_receipts": []})
        with pytest.raises(WorkflowServiceError, match="claude_sdk_artifact_receipts_missing"):
            await service._write_artifact(full, {"accepted": True, "output": final["output"]})
        for receipt in final["sdk_receipts"]:
            await service._persist_sdk_receipt(
                {"id": final["id"], "_scope": "owner", "workflow_id": SOURCE_WORKFLOW, "_inputs": definition.example_inputs, "_claude_source_sha256": final["source"]["sha256"], "_sdk_configuration_sha256": bridge.configuration_sha256},
                receipt,
            )
        assert len((await service.snapshot("owner", created["id"]))["sdk_receipts"]) == 3
        native_owner = "wf_" + hashlib.sha256(b"momo-workflow-native\0owner").hexdigest()[:60]
        native = await store.get(final["native_run_id"], user_id=native_owner)
        assert native["llm_call_count"] == 3 and native["total_input_tokens"] == 45
        assert await store.get(final["native_run_id"], user_id="synthetic-actor") is None
        replay = await service.create("owner", definition.id, definition.example_inputs, "claude_sdk", "proof", **args)
        assert replay["id"] == created["id"] and len(calls) == 3
        with pytest.raises(WorkflowServiceError, match="not_found"):
            await service.artifact("foreign", created["id"])
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_missing_or_altered_real_receipt_never_accepts(monkeypatch):
    def handler(req):
        value = response(json.loads(req.content))
        Path(os.environ["MOMOBOT_CLAUDE_SDK_RECEIPTS"]).write_text("{}\n")
        return httpx.Response(200, json=value)

    with pytest.raises(AdapterError, match="claude_sdk_ledger_readback_failed"):
        await configured(monkeypatch, handler).call(request(), context())


@pytest.mark.asyncio
async def test_internal_formatter_is_allowed_without_external_tool_authority(monkeypatch):
    bridge = configured(monkeypatch, lambda req: httpx.Response(200, json=response(json.loads(req.content), tools_used=["StructuredOutput"])))
    result = await bridge.call(request(), context())
    assert result["sdk_receipt"]["internal_format_tools"] == ["StructuredOutput"]
    assert result["sdk_receipt"]["external_tools"] == []


@pytest.mark.asyncio
async def test_total_deadline_stops_without_retry(monkeypatch):
    calls = []

    async def handler(req):
        calls.append(req)
        await asyncio.Event().wait()

    monkeypatch.setattr("app.gateway.workflow_claude_sdk.HTTP_DEADLINE", 0.01)
    with pytest.raises(AdapterError, match="claude_sdk_outcome_uncertain"):
        await configured(monkeypatch, handler).call(request(), context())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_receipt_symlink_and_oversized_response_refuse(tmp_path, monkeypatch):
    def handler(req):
        value = response(json.loads(req.content))
        real = Path(os.environ["MOMOBOT_CLAUDE_SDK_RECEIPTS"])
        link = tmp_path / "symlink.jsonl"
        link.symlink_to(real)
        bridge.receipts = link
        return httpx.Response(200, json=value)

    bridge = configured(monkeypatch, handler)
    with pytest.raises(AdapterError, match="claude_sdk_ledger_readback_failed"):
        await bridge.call(request(), context())
    too_large = configured(monkeypatch, lambda _: httpx.Response(200, content=b"x" * (256 * 1024 + 1)))
    with pytest.raises(AdapterError, match="claude_sdk_outcome_uncertain"):
        await too_large.call(request(), context())


@pytest.mark.parametrize("code, expected", [("claude_sdk_outcome_uncertain", "claude_sdk_outcome_uncertain"), ("private_error_text", "workflow_model_call_failed")])
@pytest.mark.asyncio
async def test_sdk_reports_only_explicit_safe_failure_codes(code, expected):
    from deerflow.workflows.engine import WorkflowEngine
    from deerflow.workflows.errors import WorkflowCallbackError

    async def fail(**_kwargs):
        raise AdapterError(code)

    async def event(*_args, **_kwargs):
        pass

    definition = get_workflow(SOURCE_WORKFLOW)
    with pytest.raises(WorkflowCallbackError) as failure:
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="safe-error-proof", scope="owner", framework="claude_sdk", model=MODEL, model_call=fail, browser_call=None, event=event)
    assert failure.value.code == expected


@pytest.mark.asyncio
async def test_schema_failure_and_token_overage_keep_verified_actual_cost(monkeypatch):
    invalid = configured(monkeypatch, lambda req: httpx.Response(200, json=response(json.loads(req.content), output={"answer": "x", "extra": 1})))
    with pytest.raises(AdapterError, match="claude_sdk_output_schema_invalid") as failed:
        await invalid.call(request(), context())
    assert failed.value.usage == {"input_tokens": 15, "output_tokens": 6, "cost": 0.002}
    Path(os.environ["MOMOBOT_CLAUDE_SDK_RECEIPTS"]).write_bytes(b"")
    overage = configured(monkeypatch, lambda req: httpx.Response(200, json=response(json.loads(req.content))))
    with pytest.raises(AdapterError, match="provider_token_limit_exceeded") as failed:
        await overage.call({**request(), "max_output_tokens": 5}, context())
    assert failed.value.usage["cost"] == 0.002 and failed.value.usage["output_tokens"] == 6


@pytest.mark.asyncio
async def test_driver_captures_only_bounded_synthetic_response_without_headers(tmp_path, monkeypatch):
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_claude_sdk_workflow.py"
    spec = importlib.util.spec_from_file_location("sdk_pilot_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = b'{"synthetic_result":"for audit"}'
    monkeypatch.setattr(module.httpx, "AsyncHTTPTransport", lambda **_kwargs: httpx.MockTransport(lambda _req: httpx.Response(200, content=output)))
    directory = tmp_path / "capture"
    directory.mkdir()
    transport = module.SyntheticCaptureTransport(directory)
    job_id = "sdk_" + "a" * 64
    req = httpx.Request("POST", "http://127.0.0.1:18878/run", json={"job_id": job_id, "allowed_tools": [], "data_class": "synthetic"}, headers={"Authorization": "Bearer synthetic-local-token"})
    captured = await transport.handle_async_request(req)
    assert captured.content == output
    saved = directory / (job_id + ".json")
    assert saved.read_bytes() == output and saved.stat().st_mode & 0o777 == 0o600
    assert b"synthetic-local-token" not in saved.read_bytes()
    sidecar = json.loads(saved.with_suffix(".receipt.json").read_text())
    assert sidecar["sha256"] == hashlib.sha256(output).hexdigest()
    with pytest.raises(RuntimeError, match="requires_synthetic"):
        await transport.handle_async_request(httpx.Request("POST", req.url, json={"job_id": job_id, "allowed_tools": [], "data_class": "private"}))


@pytest.mark.parametrize("failure_kind, expected", [("schema", "claude_sdk_output_schema_invalid"), ("tokens", "provider_token_limit_exceeded")])
@pytest.mark.asyncio
async def test_first_known_failure_labels_snapshot_and_native_end_cost_estimate(tmp_path, monkeypatch, failure_kind, expected):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    calls = []

    def handler(req):
        job = json.loads(req.content)
        assert job["max_attempts"] == 1
        calls.append(job)
        usage = dict(input_tokens=10, output_tokens=5000 if failure_kind == "tokens" else 6, cache_creation_input_tokens=2, cache_read_input_tokens=3)
        return httpx.Response(200, json=response(job, output={"answer": "Not the requested planner schema"}, usage=usage))

    bridge = configured(monkeypatch, handler)
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    events, store = MemoryRunEventStore(), MemoryRunStore()
    service = WorkflowService(
        tmp_path / "jobs.sqlite",
        checkpointer=InMemorySaver(),
        adapter=WorkflowModelAdapter(claude_sdk=bridge),
        run_manager=RunManager(store=store, event_store=events),
        thread_store=MemoryThreadMetaStore(InMemoryStore()),
        event_store=events,
    )
    await service.start()
    definition = get_workflow(SOURCE_WORKFLOW)
    try:
        created = await service.create("owner", definition.id, definition.example_inputs, "claude_sdk", "failure", actor="actor", organization=None, storage_user="actor")
        if service.pump_task:
            await service.pump_task
        await asyncio.gather(*service.tasks.values())
        final = await service.snapshot("owner", created["id"])
        assert final["status"] == "failed" and final["error"] == expected
        assert len(calls) == final["usage"]["model_calls"] == 1
        assert final["cost_is_estimate"] is True
        assert final["usage"]["cost_is_estimate"] is True
        assert final["usage"]["cost"] == 0.002 and final["usage"]["complete"] is True
        assert not final.get("sdk_receipts") and not final.get("artifact")
        journal = await events.list_events(final["thread_id"], final["native_run_id"])
        end = next(row for row in journal if row["event_type"] == "run.end")
        assert end["content"]["usage"]["cost"] == 0.002
        assert end["content"]["usage"]["cost_is_estimate"] is True
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_legacy_worker_rejects_new_one_attempt_contract_without_fallback(monkeypatch):
    requests = []

    def handler(req):
        job = json.loads(req.content)
        requests.append(job)
        assert job["max_attempts"] == 1
        return httpx.Response(200, json={"ok": False, "error": "invalid_job_fields", "cost_usd": 0.0, "cost_known": True})

    with pytest.raises(AdapterError, match="claude_sdk_receipt_shape_invalid"):
        await configured(monkeypatch, handler).call(request(), context())
    assert len(requests) == 1
