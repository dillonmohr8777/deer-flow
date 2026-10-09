"""The private workflow lifecycle keeps database and artifact IO off-loop."""

import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.workflow_service import WorkflowService
from deerflow.workflows.catalog import get_workflow


class Adapter:
    def capabilities(self):
        return {"langgraph": {"available": True, "detail": "Offline synthetic fixture"}}

    async def call(self, **kwargs):
        fields = kwargs["output_schema"]["properties"]
        if kwargs["role"] == "planner":
            output = {"approach": ["Read supplied notes."], "producer_role": fields["producer_role"]["enum"][0], "effort": "low", "browser_needed": False}
        elif kwargs["role"] == "verifier":
            output = {
                "approved": True,
                "output_sha256": fields["output_sha256"]["const"],
                "checks": [{"criterion": criterion, "passed": True, "rationale": "Checked supplied fixture."} for criterion in fields["checks"]["items"]["properties"]["criterion"]["enum"]],
                "findings": [],
            }
        else:
            output = {
                "workflow_id": fields["workflow_id"]["const"],
                "status": "draft",
                "assumptions": [],
                "evidence_references": ["input:source_excerpts"],
                "research_note": ["Supplied synthetic note preserves uncertainty."],
                "open_questions": ["Which saved checkpoint confirms recovery?"],
            }
        return {"output": output, "model": kwargs["model"], "effort": kwargs["effort"], "usage": {"input_tokens": 12, "output_tokens": 12, "cost": None}}


@pytest.mark.asyncio
async def test_start_admit_execute_readback_close_do_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    service = WorkflowService(tmp_path / "workflows.sqlite", checkpointer=InMemorySaver(), adapter=Adapter())
    await service.start()
    try:
        definition = get_workflow("personal-research-note")
        run = await service.create("owner", definition.id, definition.example_inputs, "langgraph", "strict-io", actor="owner", organization="org", storage_user="owner")
        for _ in range(12):
            if service.pump_task:
                await service.pump_task
            if not service.tasks:
                break
            await asyncio.gather(*list(service.tasks.values()))
        result = await service.snapshot("owner", run["id"])
        assert result["accepted"] is True
        assert (await service.artifact("owner", run["id"])).startswith(b"{")
        assert (await service.status("owner"))["running"] == 0
    finally:
        await service.aclose()
