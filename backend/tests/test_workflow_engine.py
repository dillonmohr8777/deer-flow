"""Offline graph execution uses real checkpoints; no provider/client data is needed."""

import asyncio
import hashlib
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deerflow.workflows.catalog import list_workflows
from deerflow.workflows.engine import WorkflowEngine
from deerflow.workflows.errors import WorkflowCallbackError, WorkflowInputError, WorkflowOutputError, WorkflowResumeError, WorkflowReviewError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def schema_value(schema):
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {name: schema_value(child) for name, child in schema["properties"].items() if name in schema.get("required", [])}
    if kind == "array":
        return [schema_value(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if kind == "boolean":
        return True
    return "Factual synthetic draft"


class ModelDouble:
    def __init__(self, *, reject=False, bad_schema=False):
        self.calls = []
        self.reject = reject
        self.bad_schema = bad_schema

    async def __call__(self, **request):
        self.calls.append(request)
        output = schema_value(request["output_schema"])
        if request["role"] == "verifier":
            criteria = request["output_schema"]["properties"]["checks"]["items"]["properties"]["criterion"]["enum"]
            output["checks"] = [{"criterion": criterion, "passed": not self.reject, "rationale": "Checked against the admitted synthetic inputs."} for criterion in criteria]
            output["approved"] = not self.reject
        elif request["role"] != "planner":
            output["evidence_references"] = ["input:brief"]
            if self.bad_schema:
                output["unexpected_private_field"] = "must be rejected"
        return {"output": output, "model": request["model"], "effort": request["effort"], "usage": {"input_tokens": 40, "output_tokens": 20, "cost": None}}


async def browser_double(urls):
    text = "SYNTHETIC source text; no remote browser was called."
    return {"pages": [{"url": urls[0], "title": "Synthetic page", "text": text}], "evidence": [{"kind": "browser_page", "reference": urls[0], "sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text.encode())}]}


async def event_double(*_args, **_kwargs):
    return None


@pytest.mark.parametrize("definition", list_workflows(), ids=lambda item: item.id)
async def test_all_120_workflows_execute_and_require_independent_verified_artifacts(definition):
    model = ModelDouble()
    engine = WorkflowEngine(InMemorySaver())
    result = await engine.execute(definition, definition.example_inputs, run_id="run", scope="owner-a:org-a", framework="langgraph", model_call=model, browser_call=browser_double, event=event_double)
    assert result["accepted"] is True
    assert result["output"]["workflow_id"] == definition.id
    assert result["output"]["status"] == "draft"
    assert len(model.calls) == 3
    assert [call["role"] for call in model.calls][::2] == ["planner", "verifier"]
    assert len({call["worker_id"] for call in model.calls}) == 3
    artifact = next(item for item in result["evidence"] if item["kind"] == "workflow_output")
    content = json.dumps(result["output"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["bytes"] == len(content)


async def test_invalid_input_and_schema_never_become_accepted():
    definition = list_workflows()[0]
    model = ModelDouble(bad_schema=True)
    engine = WorkflowEngine(InMemorySaver())
    with pytest.raises(WorkflowInputError):
        await engine.execute(definition, {}, run_id="bad-input", scope="a", framework="langgraph", model_call=model, browser_call=None, event=event_double)
    assert not model.calls
    with pytest.raises(WorkflowOutputError):
        await engine.execute(definition, definition.example_inputs, run_id="bad-output", scope="a", framework="langgraph", model_call=model, browser_call=None, event=event_double)
    assert len(model.calls) == 2


async def test_review_rejection_is_bounded_and_reuses_the_existing_producer():
    definition = list_workflows()[0]
    model = ModelDouble(reject=True)
    engine = WorkflowEngine(InMemorySaver())
    with pytest.raises(WorkflowReviewError):
        await engine.execute(definition, definition.example_inputs, run_id="rejected", scope="a", framework="langgraph", model_call=model, browser_call=None, event=event_double)
    assert len(model.calls) == 5
    assert model.calls[1]["worker_id"] == model.calls[3]["worker_id"]
    assert model.calls[3]["continuation"][0] == {"role": "user", "content": model.calls[1]["prompt"]}
    assert json.loads(model.calls[3]["continuation"][1]["content"])["evidence_references"] == ["input:brief"]
    assert model.calls[2]["worker_id"] != model.calls[1]["worker_id"]


async def test_restart_resume_reuses_saved_work_and_rejects_changed_inputs(tmp_path):
    definition = list_workflows()[0]
    model = ModelDouble()
    db = str(tmp_path / "workflow.db")
    arrived = asyncio.Event()
    blocked = asyncio.Event()

    async def interrupt_before_review(**request):
        if request["role"] == "verifier":
            arrived.set()
            await blocked.wait()
        return await model(**request)

    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        task = asyncio.create_task(WorkflowEngine(saver).execute(definition, definition.example_inputs, run_id="restart", scope="a", framework="langgraph", model_call=interrupt_before_review, browser_call=None, event=event_double))
        await asyncio.wait_for(arrived.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(model.calls) == 2
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        engine = WorkflowEngine(saver)
        with pytest.raises(WorkflowResumeError):
            await engine.execute(definition, {**definition.example_inputs, "brief": "Changed after admission"}, run_id="restart", scope="a", framework="langgraph", model_call=model, browser_call=None, event=event_double, resume=True)
        result = await engine.execute(definition, definition.example_inputs, run_id="restart", scope="a", framework="langgraph", model_call=model, browser_call=None, event=event_double, resume=True)
        assert result["accepted"] is True
    assert len(model.calls) == 3


async def test_scopes_and_run_ids_cannot_read_or_resume_foreign_checkpoints(tmp_path):
    definition = list_workflows()[0]
    model = ModelDouble()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "scope.db")) as saver:
        engine = WorkflowEngine(saver)
        args = dict(run_id="same-id", framework="langgraph", model_call=model, browser_call=None, event=event_double)
        await engine.execute(definition, definition.example_inputs, scope="owner-a", **args)
        with pytest.raises(WorkflowResumeError):
            await engine.execute(definition, definition.example_inputs, scope="owner-b", resume=True, **args)
        await engine.execute(definition, definition.example_inputs, scope="owner-b", **args)
    assert model.calls[0]["worker_id"] != model.calls[3]["worker_id"]


async def test_concurrent_same_run_is_serialized_without_second_dispatch():
    definition = list_workflows()[0]
    entered = asyncio.Event()
    release = asyncio.Event()
    model = ModelDouble()

    async def paused_model(**request):
        entered.set()
        await release.wait()
        return await model(**request)

    engine = WorkflowEngine(InMemorySaver())
    kwargs = dict(run_id="same", scope="owner", framework="langgraph", model_call=paused_model, browser_call=None, event=event_double)
    first = asyncio.create_task(engine.execute(definition, definition.example_inputs, **kwargs))
    await entered.wait()
    second = asyncio.create_task(WorkflowEngine(engine.checkpointer).execute(definition, definition.example_inputs, **kwargs))
    release.set()
    assert (await first)["accepted"] is True
    assert (await second)["accepted"] is True
    assert len(model.calls) == 3


@pytest.mark.parametrize(
    "invalid",
    [
        {"model": "unapproved-expensive-model"},
        {"effort": "max"},
        {"usage": None},
        {"usage": {"input_tokens": None, "output_tokens": 20, "cost": None}},
        {"usage": {"input_tokens": True, "output_tokens": 20, "cost": None}},
        {"usage": {"input_tokens": 40, "output_tokens": -1, "cost": None}},
        {"usage": {"input_tokens": 40, "output_tokens": 20, "cost": float("nan")}},
    ],
)
async def test_invalid_provider_receipts_fail_closed(invalid):
    definition = list_workflows()[0]
    model = ModelDouble()

    async def bad_receipt(**request):
        return {**await model(**request), **invalid}

    with pytest.raises(WorkflowCallbackError):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="receipt", scope="a", framework="langgraph", model_call=bad_receipt, browser_call=None, event=event_double)
    assert len(model.calls) == 1


async def test_missing_review_criterion_and_forged_provenance_fail_closed():
    definition = list_workflows()[0]

    async def duplicate_review(**request):
        response = await ModelDouble()(**request)
        if request["role"] == "verifier":
            response["output"]["checks"][1] = response["output"]["checks"][0]
        return response

    with pytest.raises(WorkflowReviewError):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="review", scope="a", framework="langgraph", model_call=duplicate_review, browser_call=None, event=event_double)

    async def forged_reference(**request):
        response = await ModelDouble()(**request)
        if request["role"] not in ("planner", "verifier"):
            response["output"]["evidence_references"] = ["https://unrelated.example/secret"]
        return response

    with pytest.raises(WorkflowOutputError):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="provenance", scope="a", framework="langgraph", model_call=forged_reference, browser_call=None, event=event_double)


async def test_budget_callback_stops_before_next_provider_dispatch_and_errors_are_bounded():
    definition = list_workflows()[0]
    model = ModelDouble()

    async def budgeted(**request):
        if len(model.calls) == 2:
            raise RuntimeError("provider-private-secret-data-must-not-appear-in-error")
        return await model(**request)

    with pytest.raises(WorkflowCallbackError) as error:
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="budget", scope="a", framework="langgraph", model_call=budgeted, browser_call=None, event=event_double)
    assert "secret" not in str(error.value)
    assert error.value.code == "workflow_model_call_failed"
    # The raw provider exception is preserved as the cause so workflow_service.py
    # can recover an inner WorkflowServiceError's own code, but the wrapper's own
    # message/code never leaks it.
    assert isinstance(error.value.__cause__, RuntimeError)
    assert len(model.calls) == 2


@pytest.mark.parametrize("browser", [None, lambda urls: {"pages": [], "evidence": []}])
async def test_browser_required_work_cannot_succeed_without_real_page_evidence(browser):
    definition = next(item for item in list_workflows() if item.requires_browser)
    model = ModelDouble()

    async def broken(urls):
        return browser(urls)

    with pytest.raises(WorkflowCallbackError):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="browser", scope="a", framework="langgraph", model_call=model, browser_call=None if browser is None else broken, event=event_double)
    assert not model.calls


async def test_stagehand_extraction_is_untrusted_draft_context_with_exact_evidence_hashes():
    definition = next(item for item in list_workflows() if item.requires_browser)
    quote = "The supplied page lists a fictional service area."
    text = "SYNTHETIC " + "x" * 4500 + quote
    data = {"title": "Synthetic extracted page", "summary": "A bounded extracted summary visible to the draft worker.", "claims": [{"claim": "The service area appears in supplied source text.", "quote": quote}]}
    model = ModelDouble()

    async def extracted_browser(urls):
        result = await browser_double(urls)
        result["pages"][0].update(text=text, stagehand_extract={"data": data, "metadata": {"private_transport": "must-not-enter-context"}, "mode": "stagehand_extract_public_snapshot"})
        return result

    result = await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="extracted", scope="a", framework="langgraph", model_call=model, browser_call=extracted_browser, event=event_double)
    draft = model.calls[1]["prompt"]
    assert "stagehand_extract" in draft and '"untrusted":true' in draft
    assert data["summary"] in draft and quote in draft
    assert "must-not-enter-context" not in draft
    evidence = next(item for item in result["evidence"] if item["kind"] == "stagehand_extract")
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert evidence["sha256"] == hashlib.sha256(encoded).hexdigest() and evidence["bytes"] == len(encoded)
    snapshot = next(item for item in result["evidence"] if item["kind"] == "browser_snapshot")
    assert snapshot["sha256"] == hashlib.sha256(text[:24000].encode()).hexdigest()
    assert snapshot["bytes"] == len(text[:24000].encode())


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {"data": None},
        {"data": {"title": "Title", "summary": "Summary", "claims": [], "extra": "forged"}},
        {"data": {"title": "t" * 201, "summary": "Summary", "claims": []}},
        {"data": {"title": "Title", "summary": "s" * 2001, "claims": []}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "c" * 501, "quote": "SYNTHETIC"}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": ""}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": " "}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "unsupported private fact"}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "q" * 1001}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "SYNTHETIC", "extra": "forged"}]}},
        {"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "SYNTHETIC"}] * 9}},
    ],
)
async def test_invalid_stagehand_shape_or_unsupported_quote_fails_before_model(invalid):
    definition = next(item for item in list_workflows() if item.requires_browser)
    model = ModelDouble()

    async def extracted_browser(urls):
        result = await browser_double(urls)
        result["pages"][0]["stagehand_extract"] = invalid
        return result

    with pytest.raises(WorkflowCallbackError, match="workflow_browser_extract"):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="invalid-extract", scope="a", framework="langgraph", model_call=model, browser_call=extracted_browser, event=event_double)
    assert not model.calls


async def test_stagehand_quote_beyond_rendered_snapshot_fails_before_model():
    definition = next(item for item in list_workflows() if item.requires_browser)
    model = ModelDouble()

    async def extracted_browser(urls):
        result = await browser_double(urls)
        result["pages"][0].update(text="x" * 24000 + "Not rendered.", stagehand_extract={"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "Not rendered."}]}})
        return result

    with pytest.raises(WorkflowCallbackError, match="workflow_browser_extract"):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="outside-snapshot", scope="a", framework="langgraph", model_call=model, browser_call=extracted_browser, event=event_double)
    assert not model.calls


async def test_stagehand_quote_beyond_javascript_utf16_snapshot_fails_before_model():
    definition = next(item for item in list_workflows() if item.requires_browser)
    model = ModelDouble()

    async def extracted_browser(urls):
        result = await browser_double(urls)
        result["pages"][0].update(text="🎵" * 12000 + "Not rendered.", stagehand_extract={"data": {"title": "Title", "summary": "Summary", "claims": [{"claim": "Claim", "quote": "Not rendered."}]}})
        return result

    with pytest.raises(WorkflowCallbackError, match="workflow_browser_extract"):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, run_id="outside-utf16-snapshot", scope="a", framework="langgraph", model_call=model, browser_call=extracted_browser, event=event_double)
    assert not model.calls


async def test_resumed_paid_attempt_uses_identical_call_id_and_retained_producer_context(tmp_path):
    definition = list_workflows()[0]
    model = ModelDouble(reject=True)
    attempts = []
    waiting = asyncio.Event()
    blocker = asyncio.Event()

    async def pause_revision(**request):
        if request["role"] not in ("planner", "verifier") and request["continuation"]:
            attempts.append(request)
            waiting.set()
            await blocker.wait()
        return await model(**request)

    db = str(tmp_path / "revision.db")
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        task = asyncio.create_task(WorkflowEngine(saver).execute(definition, definition.example_inputs, run_id="revision", scope="a", framework="langgraph", model_call=pause_revision, browser_call=None, event=event_double))
        await asyncio.wait_for(waiting.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    model.reject = False

    async def resume_revision(**request):
        if request["role"] not in ("planner", "verifier"):
            attempts.append(request)
        return await model(**request)

    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        result = await WorkflowEngine(saver).execute(definition, definition.example_inputs, run_id="revision", scope="a", framework="langgraph", model_call=resume_revision, browser_call=None, event=event_double, resume=True)
    assert result["accepted"] is True
    assert attempts[0]["worker_id"] == attempts[1]["worker_id"]
    assert attempts[0]["call_id"] == attempts[1]["call_id"]
    assert attempts[0]["continuation"] == attempts[1]["continuation"]
    assert len(model.calls) == 5
