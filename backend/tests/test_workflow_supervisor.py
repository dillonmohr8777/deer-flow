"""Supervisor gates use offline transports and the existing durable graph."""

import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_workflow_engine import ModelDouble, event_double, schema_value

from deerflow.workflows.catalog import list_workflows
from deerflow.workflows.engine import WorkflowEngine
from deerflow.workflows.errors import WorkflowOutputError, WorkflowResumeError, WorkflowReviewError

pytestmark = pytest.mark.asyncio


class SupervisorDouble(ModelDouble):
    def __init__(self, *, plan_failure=None, **kwargs):
        super().__init__(**kwargs)
        self.plan_failure = plan_failure

    async def __call__(self, **request):
        if request["role"] != "plan_reviewer":
            return await super().__call__(**request)
        self.calls.append(request)
        output = schema_value(request["output_schema"])
        criteria = request["output_schema"]["properties"]["checks"]["items"]["properties"]["criterion"]["enum"]
        output["checks"] = [{"criterion": criterion, "passed": True, "rationale": "Plan covers this required criterion."} for criterion in criteria]
        if self.plan_failure == "rejected":
            output["approved"] = False
        elif self.plan_failure == "failed_check":
            output["checks"][0]["passed"] = False
        elif self.plan_failure == "blocker":
            output["findings"] = ["Required source evidence is absent."]
        elif self.plan_failure == "duplicate":
            output["checks"][-1] = output["checks"][0]
        elif self.plan_failure == "wrong_hash":
            output["output_sha256"] = "0" * 64
        return {"output": output, "model": request["model"], "effort": request["effort"], "usage": {"input_tokens": 40, "output_tokens": 20, "cost": None}}


def execution(model, **changes):
    return {"run_id": "supervised", "scope": "owner", "framework": "langgraph", "model_call": model, "browser_call": None, "event": event_double, "supervisor": True, **changes}


async def test_supervisor_reviews_plan_before_any_producer_and_keeps_workers_independent():
    definition = list_workflows()[0]
    model = SupervisorDouble()
    result = await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, **execution(model))
    assert result["accepted"] is True and result["output"]["status"] == "draft"
    assert [call["role"] for call in model.calls] == ["planner", "plan_reviewer", f"{definition.category}_specialist", "verifier"]
    assert len({call["worker_id"] for call in model.calls}) == 4
    assert any(item["kind"] == "workflow_plan_review" for item in result["evidence"])


@pytest.mark.parametrize("failure", ["rejected", "failed_check", "blocker", "duplicate", "wrong_hash"])
async def test_rejected_or_invalid_plan_stops_before_drafting(failure):
    definition = list_workflows()[0]
    model = SupervisorDouble(plan_failure=failure)
    with pytest.raises((WorkflowReviewError, WorkflowOutputError)):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, **execution(model))
    assert [call["role"] for call in model.calls] == ["planner", "plan_reviewer"]


async def test_supervisor_revision_stays_at_six_calls_with_original_producer():
    definition = list_workflows()[0]
    model = SupervisorDouble(reject=True)
    with pytest.raises(WorkflowReviewError):
        await WorkflowEngine(InMemorySaver()).execute(definition, definition.example_inputs, **execution(model))
    assert len(model.calls) == 6
    assert model.calls[2]["worker_id"] == model.calls[4]["worker_id"]
    assert model.calls[4]["continuation"]


async def test_checkpoint_resume_keeps_plan_gate_and_mode_without_repeating_approved_work():
    definition = list_workflows()[0]
    model = SupervisorDouble()
    saver = InMemorySaver()
    arrived = asyncio.Event()
    blocked = asyncio.Event()

    async def pause_before_draft(**request):
        if request["role"].endswith("specialist"):
            arrived.set()
            await blocked.wait()
        return await model(**request)

    task = asyncio.create_task(WorkflowEngine(saver).execute(definition, definition.example_inputs, **execution(pause_before_draft)))
    await asyncio.wait_for(arrived.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(model.calls) == 2
    with pytest.raises(WorkflowResumeError):
        await WorkflowEngine(saver).execute(definition, definition.example_inputs, **execution(model, supervisor=False, resume=True))
    result = await WorkflowEngine(saver).execute(definition, definition.example_inputs, **execution(model, resume=True))
    assert result["accepted"] is True and len(model.calls) == 4
