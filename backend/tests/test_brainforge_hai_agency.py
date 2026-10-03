"""Exact94 native supervisor remains active under the synthetic HAI bridge."""

import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_brainforge_hai_budget import CONTEXT, KEY, rows, synthetic_config
from test_brainforge_hai_native import SyntheticResponses
from test_workflow_native_runtime import drain

from app.gateway.routers.workflows import WorkflowRequest
from app.gateway.workflow_adapters import HAI_MODEL, HAI_ROUTE, ROUTE_ENV
from app.gateway.workflow_hai_budget import SECTION, create_workflow_model_adapter
from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
from deerflow.workflows.catalog import get_workflow
from deerflow.workflows.engine import MAX_SUPERVISOR_MODEL_CALLS


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_plan", [False, True])
async def test_exact94_supervisor_review_is_distinct_low_only_and_stops_unapproved_plan(tmp_path, monkeypatch, reject_plan):
    cfg = synthetic_config(tmp_path)
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    definition = get_workflow("personal-research-note")

    class SupervisorResponses(SyntheticResponses):
        async def create(self, **kwargs):
            value = await super().create(**kwargs)
            prompt = kwargs["input"][-1]["content"]
            if reject_plan and "Independently review this plan" in prompt:
                data = json.loads(value.output_text)
                data["approved"] = False
                value.output_text = json.dumps(data)
            return value

    client = SupervisorResponses()
    adapter = create_workflow_model_adapter(SimpleNamespace(model_extra={SECTION: cfg}))
    adapter.client = client
    service = WorkflowService(tmp_path / "native.sqlite", checkpointer=InMemorySaver(), adapter=adapter)
    await service.start()
    try:
        arguments = {"actor": CONTEXT["actor"], "organization": CONTEXT["organization"], "storage_user": CONTEXT["storage_user"], "supervisor": True}
        admitted = await service.create(CONTEXT["owner_scope"], definition.id, definition.example_inputs, "langgraph", "same-admission", **arguments)
        await drain(service)
        result = await service.snapshot(CONTEXT["owner_scope"], admitted["id"])
        assert MAX_SUPERVISOR_MODEL_CALLS == 6
        assert all(call["model"] == HAI_MODEL and call["reasoning"] == {"effort": "low"} for call in client.calls)
        assert len(client.calls) == (2 if reject_plan else 4)
        assert result["accepted"] is (not reject_plan)
        assert result["status"] == ("failed" if reject_plan else "completed")
        if not reject_plan:
            assert any(item["kind"] == "workflow_plan_review" for item in result["evidence"])
        with pytest.raises(WorkflowServiceError, match="idempotency_conflict"):
            await service.create(CONTEXT["owner_scope"], definition.id, definition.example_inputs, "langgraph", "same-admission", **{**arguments, "supervisor": False})
        assert len(rows(cfg)) == 2 + 2 * len(client.calls)
    finally:
        await service.aclose()


def test_native_exact94_request_retains_closed_supervisor_field():
    assert set(WorkflowRequest.model_fields) == {"workflow_id", "inputs", "framework", "supervisor"}
    definition = get_workflow("personal-research-note")
    accepted = WorkflowRequest.model_validate({"workflow_id": definition.id, "inputs": definition.example_inputs, "framework": "langgraph", "supervisor": True})
    assert accepted.supervisor is True
    with pytest.raises(ValueError):
        WorkflowRequest.model_validate({**accepted.model_dump(), "model": HAI_MODEL, "base_url": "https://unapproved.invalid"})
