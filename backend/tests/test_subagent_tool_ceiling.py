"""A delegated child is held to the parent agent's explicit tool_names ceiling.

Chains the real functions: lead assembly stamps the ceiling into run metadata,
then task / batch_task / the durable batch service build the child toolset.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_batch_task_tool as batch_tool_base
import test_momobot_max_assembly as assembly_base
import test_subagent_batch_service as batch_service_base
import test_task_tool_core_logic as task_base

from deerflow.config.builtin_agents import MOMOBOT_MAX_TOOL_NAMES
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents.batch_service import SubagentBatchService
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.config import SubagentConfig
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem

CHILD_TOOLS = ("web_search", "write_file", "bash", "propose_action")  # last two are outside MOMOBOT_MAX_TOOL_NAMES


def _assembled_max_metadata(monkeypatch, tmp_path, *, role="client") -> dict:
    """Real _assemble_lead_agent for momobot-max, with a forged caller ceiling."""
    from deerflow.agents.lead_agent import agent

    seen = {}
    real = agent._assemble_lead_agent

    def wrapped(config, **kwargs):
        config.setdefault("metadata", {})["tool_names"] = None  # caller tries to lift the ceiling
        seen["config"] = config
        return real(config, **kwargs)

    monkeypatch.setattr(agent, "_assemble_lead_agent", wrapped)
    app = assembly_base._app_config(authorization=assembly_base.example_authorization())
    app.momobot_max.staff_model = "claude-haiku-5-5"
    asyncio.run(assembly_base._assemble(monkeypatch, tmp_path, role=role, app=app, keys=("c-max",)))
    return dict(seen["config"]["metadata"])


def _task_child_tools(monkeypatch, metadata: dict) -> set[str]:
    runtime = task_base._make_runtime(app_config=assembly_base._app_config())
    runtime.config["metadata"] = metadata
    captured = {}

    class Executor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute_async(self, prompt, task_id=None):
            return task_id or "t"

    m = task_base.task_tool_module
    monkeypatch.setattr(m, "SubagentStatus", task_base.FakeSubagentStatus)
    monkeypatch.setattr(m, "SubagentExecutor", Executor)
    monkeypatch.setattr(m, "get_subagent_config", lambda *_a, **_k: task_base._make_subagent_config())
    monkeypatch.setattr(m, "get_background_task_result", lambda _: task_base._make_result(task_base.FakeSubagentStatus.COMPLETED, result="done"))
    monkeypatch.setattr(m, "get_stream_writer", lambda: lambda _e: None)
    monkeypatch.setattr(m.asyncio, "sleep", task_base._no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kw: [SimpleNamespace(name=n) for n in CHILD_TOOLS])
    task_base._run_task_tool(runtime=runtime, description="d", prompt="p", subagent_type="general-purpose", tool_call_id="tc")
    return {t.name for t in captured["tools"]}


@pytest.mark.parametrize("role", ["client", "user", "exec", "admin"])
def test_momobot_max_task_child_keeps_the_parents_ceiling(monkeypatch, tmp_path, role):
    metadata = _assembled_max_metadata(monkeypatch, tmp_path, role=role)
    assert metadata["tool_names"] is not None
    assert set(metadata["tool_names"]) <= set(MOMOBOT_MAX_TOOL_NAMES)  # server value replaced the forged None

    names = _task_child_tools(monkeypatch, metadata)
    assert {"web_search", "write_file"} <= names
    assert {"bash", "propose_action"}.isdisjoint(names)


def test_unset_ceiling_is_unrestricted_and_empty_ceiling_is_no_tools(monkeypatch):
    base = {"tool_groups": None, "mcp_plugins": []}
    assert _task_child_tools(monkeypatch, {**base, "tool_names": None}) == set(CHILD_TOOLS)
    assert _task_child_tools(monkeypatch, {**base, "tool_names": []}) == set()


@pytest.mark.parametrize("role", ["client", "user", "exec", "admin"])
def test_durable_batch_child_keeps_the_parents_ceiling(monkeypatch, tmp_path, role):
    metadata = _assembled_max_metadata(monkeypatch, tmp_path, role=role)

    # batch_task records the ceiling in the durable execution spec ...
    runtime = batch_tool_base._runtime()
    runtime.config["metadata"] = {**metadata, "allowed_subagents": ["general-purpose"]}
    submitter = AsyncMock()
    submitter.submit.return_value = {"id": "b-1", "status": "queued", "total_items": 1}
    tm = batch_tool_base.tool_module
    monkeypatch.setattr(tm, "get_subagent_batch_submitter", lambda: submitter)
    monkeypatch.setattr(tm, "get_available_subagent_names", lambda **_k: ["general-purpose"])
    monkeypatch.setattr(tm, "get_subagent_config", lambda *_a, **_k: SubagentConfig(name="general-purpose", description="General purpose"))
    asyncio.run(
        tm.batch_task.coroutine(
            runtime=runtime,
            title="t",
            items=[BatchTaskItem(key="k", prompt="p")],
            subagent_type="general-purpose",
            tool_call_id="call-1",
        )
    )
    spec = submitter.submit.await_args.args[0].execution_spec
    assert spec["tool_names"] == metadata["tool_names"]

    # ... and the batch service builds the child from that spec.
    spec["subagent_config"] = {"name": "general-purpose", "description": "d", "system_prompt": "s"}
    executor_kwargs = {}
    result = SimpleNamespace(status=batch_service_base.FakeStatus.COMPLETED, result="done", error=None, stop_reason=None, token_usage_records=None)

    class Repository:
        async def claim_items(self, **_kwargs):
            return [{"id": "item-1", "item_key": "k", "prompt": "p", "batch": {"id": "b-1", "thread_id": "thread-1", "user_id": "user-1", "run_id": "run-1", "execution_spec": spec}}]

        async def mark_item_running(self, *_a, **_k):
            return True

        async def renew_item_lease(self, *_a, **_k):
            return {"valid": True, "cancel_requested": False}

        async def finalize_item(self, *_a, **_k):
            return True

    class Executor:
        def __init__(self, **kwargs):
            executor_kwargs.update(kwargs)

        def execute_async(self, _prompt, task_id=None):
            return "execution-1"

    sm = batch_service_base.service_module
    monkeypatch.setattr(sm, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(sm, "resolve_subagent_model_name", lambda *_a, **_k: "model-a")
    monkeypatch.setattr(sm, "SubagentExecutor", Executor)
    monkeypatch.setattr(sm, "SubagentStatus", batch_service_base.FakeStatus)
    monkeypatch.setattr(sm, "get_background_task_result", lambda _id: result)
    monkeypatch.setattr(sm, "cleanup_background_task", lambda _id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kw: [SimpleNamespace(name=n) for n in CHILD_TOOLS])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
        execution_capacity=SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1)),
    )

    async def run():
        await service.run_once(now=sm.datetime.now(sm.UTC))
        await asyncio.gather(*list(service._executions.values()))

    asyncio.run(run())
    names = {t.name for t in executor_kwargs["tools"]}
    assert {"web_search", "write_file"} <= names
    assert {"bash", "propose_action"}.isdisjoint(names)
