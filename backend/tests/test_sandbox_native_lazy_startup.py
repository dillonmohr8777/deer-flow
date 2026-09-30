"""Native-only graphs must not require or inherit a sandbox capability."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest
from deerflow_extension_api import ExtensionData
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, Overwrite
from support.detectors.blocking_io_runtime import detect_blocking_io_strict

from deerflow.agents.lead_agent import agent as lead
from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import ToolConfig
from deerflow.extensions.registry import LoadedExtensions
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.sandbox.exceptions import SandboxRuntimeError
from deerflow.sandbox.lease import release_sandbox_execution_lease, release_sandbox_execution_lease_async
from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.native_startup import configure_native_lazy_startup
from deerflow.sandbox.sandbox_provider import get_initialized_sandbox_provider, get_sandbox_provider, native_tool_execution
from deerflow.subagents.config import SubagentConfig
from deerflow.tools.builtins.agent_room_tool import agent_room_post, agent_room_read
from deerflow.tools.builtins.approved_agency_tool import approved_agency_phase
from deerflow.tools.builtins.batch_task_tool import batch_status, cancel_batch
from deerflow.tools.builtins.present_file_tool import present_file_tool

NATIVE_TOOLS = [agent_room_read, agent_room_post, approved_agency_phase, batch_status, cancel_batch, present_file_tool]


def _configure(middleware, tools=(), **overrides):
    args = {"available_skills": set(), "deferred_names": frozenset(), "has_extension_middlewares": False}
    args.update(overrides)
    return configure_native_lazy_startup([middleware], list(tools), **args)


def _forbid_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Native-only graph touched sandbox provider")

    for module in ("deerflow.sandbox.middleware", "deerflow.sandbox.sandbox_provider", "deerflow.sandbox.tools", "deerflow.agents.middlewares.tool_output_budget_middleware"):
        monkeypatch.setattr(f"{module}.get_sandbox_provider", forbidden)


@pytest.fixture
def app(monkeypatch, tmp_path):
    from deerflow.config import paths

    monkeypatch.setattr(paths, "_paths", Paths(base_dir=tmp_path / "state"))
    app = AppConfig(
        models=[ModelConfig(name="offline", model="offline", use="langchain_openai:ChatOpenAI")],
        sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider", network={"mode": "isolated"}),
        tools=[],
    )
    app.summarization.enabled = False
    app.memory.enabled = False
    app.skills.deferred_discovery = False
    monkeypatch.setattr(lead, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_enabled_skills_for_config", lambda *args, **kwargs: [])
    push_current_app_config(app)
    try:
        yield app
    finally:
        pop_current_app_config()


class RecordingModel(GenericFakeChatModel):
    call_count: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        self.call_count += 1
        return super()._generate(*args, **kwargs)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("large_output", [False, True])
def test_real_lead_assembly_native_tool_and_outer_cleanup(monkeypatch, app, tmp_path, asynchronous, large_output):
    """Run the production graph, real native artifact tool and worker fence."""
    app.tools = [
        ToolConfig(name="approved_agency_phase", group="native", use="deerflow.tools.builtins.approved_agency_tool:approved_agency_phase"),
        ToolConfig(name="batch_status", group="native", use="deerflow.tools.builtins.batch_task_tool:batch_status"),
        ToolConfig(name="cancel_batch", group="native", use="deerflow.tools.builtins.batch_task_tool:cancel_batch"),
    ]
    app.private_workspace.enabled = True
    cfg = AgentConfig(name="native-test", skills=[], mcp_plugins=[], tool_groups=["native"], tool_names=[t.name for t in NATIVE_TOOLS], memory_enabled=False, self_update_enabled=False)
    monkeypatch.setattr(lead, "load_agent_config", lambda *args, **kwargs: cfg)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.load_agent_soul", lambda *args, **kwargs: "Public synthetic artifact test.")
    large_rows = [{"body": "Public synthetic evidence. " * 1000}]
    if large_output:

        class Repository:
            async def list_messages(self, **kwargs):
                return large_rows

        async def owner_repository(runtime):
            assert runtime.context["user_id"] == "native-owner"
            return (Repository(), "native-owner"), None

        monkeypatch.setattr("deerflow.tools.builtins.agent_room_tool._owner_repository", owner_repository)
        call = {"id": "native-call", "name": "agent_room_read", "args": {"limit": 1}}
    else:
        call = {"id": "native-call", "name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/proof.txt"]}}
    responses = [AIMessage(content="", tool_calls=[call]), AIMessage(content="READY")]
    model = RecordingModel(messages=iter(responses))
    monkeypatch.setattr(lead, "create_chat_model", lambda **kwargs: model)
    _forbid_provider(monkeypatch)
    config = {"configurable": {"agent_name": cfg.name, "model_name": "offline", "user_id": "native-owner"}}
    graph = lead.assemble_lead_agent(config, app_config=app).graph
    context = {"thread_id": "native-thread", "user_id": "native-owner", "agent_name": cfg.name}
    state = {"messages": [HumanMessage(content="Show the public synthetic artifact.")]}
    if asynchronous:

        async def run():
            with detect_blocking_io_strict():
                result = await graph.ainvoke(state, context=context)
                await release_sandbox_execution_lease_async(context)
            return result

        result = asyncio.run(run())
    else:
        result = graph.invoke(state, context=context)
        release_sandbox_execution_lease(context)
    assert result["messages"][-1].content == "READY"
    if large_output:
        from pathlib import Path

        tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
        assert "Full agent_room_read output saved to" in tool_message.content
        saved = list(Path(result["thread_data"]["outputs_path"]).glob(".tool-results/*"))
        assert len(saved) == 1
        assert json.loads(saved[0].read_text()) == large_rows
    else:
        assert result["artifacts"] == ["/mnt/user-data/outputs/proof.txt"]
        assert any(isinstance(m, ToolMessage) and m.content == "Successfully presented files" for m in result["messages"])
    assert model.call_count == 2
    assert not result.get("sandbox")
    assert not any(key.startswith("sandbox") for key in context)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_clean_empty_skill_native_lifecycle_does_not_create_lease(monkeypatch, asynchronous):
    _forbid_provider(monkeypatch)
    middleware = SandboxMiddleware(available_skills=set())
    assert _configure(middleware, NATIVE_TOOLS)
    state = {"messages": [HumanMessage(content="READY")]}
    context = {"thread_id": "clean", "user_id": "owner"}
    runtime = Runtime(context=context)
    if asynchronous:

        async def run():
            assert await middleware.abefore_agent(state, runtime) is None
            assert await middleware.aafter_agent(state, runtime) is None
            await release_sandbox_execution_lease_async(context)

        asyncio.run(run())
    else:
        assert middleware.before_agent(state, runtime) is None
        assert middleware.after_agent(state, runtime) is None
        release_sandbox_execution_lease(context)
    assert context == {"thread_id": "clean", "user_id": "owner"}


@pytest.mark.parametrize("skills", [None, {"enabled-skill"}])
def test_nonempty_or_inherited_skills_keep_existing_policy(skills):
    middleware = SandboxMiddleware(available_skills=skills)
    assert not _configure(middleware, NATIVE_TOOLS, available_skills=skills)
    assert not middleware.native_lazy_startup


def test_composed_middleware_nonempty_skills_cannot_disagree_with_empty_claim():
    sandbox = SandboxMiddleware(available_skills={"enabled-skill"})
    assert not _configure(sandbox)
    assert not sandbox.native_lazy_startup


def test_eager_deferred_extension_and_unknown_tools_keep_existing_policy():
    @tool("present_files")
    def impostor() -> str:
        """A same-named tool is not the canonical capability."""
        return "unknown"

    class OverrideTool(StructuredTool):
        def _run(self, *args, **kwargs):
            raise AssertionError("Must not qualify")

    clone = present_file_tool.model_copy()
    subclass = OverrideTool(**present_file_tool.model_dump())
    for candidate in (impostor, clone, subclass):
        middleware = SandboxMiddleware(available_skills=set())
        assert not _configure(middleware, [candidate])
    assert not _configure(SandboxMiddleware(lazy_init=False, available_skills=set()))
    assert not _configure(SandboxMiddleware(available_skills=set()), deferred_names=frozenset({"hidden_bash"}))
    assert not _configure(SandboxMiddleware(available_skills=set()), has_extension_middlewares=True)


def test_late_tools_and_arbitrary_provider_hooks_are_not_native():
    class LateToolMiddleware(AgentMiddleware):
        tools = [present_file_tool.model_copy()]

    sandbox = SandboxMiddleware(available_skills=set())
    for additional in (LateToolMiddleware(), GuardrailMiddleware(SimpleNamespace(evaluate=lambda request: get_sandbox_provider()))):
        assert not configure_native_lazy_startup([sandbox, additional], NATIVE_TOOLS, available_skills=set(), deferred_names=frozenset(), has_extension_middlewares=False)
        assert not sandbox.native_lazy_startup


def test_reusing_a_middleware_cannot_retain_an_old_capability_proof():
    sandbox = SandboxMiddleware(available_skills=set())
    assert _configure(sandbox)
    assert not _configure(sandbox, deferred_names=frozenset({"unknown"}))
    assert not sandbox.native_lazy_startup


UNSAFE_STATES = [
    ({"sandbox": {"sandbox_id": "parent"}}, {}),
    ({"sandbox": Overwrite({"sandbox_id": "parent"})}, {}),
    ({"sandbox": {"value": {"sandbox_id": "parent"}, "fork_restored": True}}, {}),
    ({"sandbox": {}}, {}),
    ({}, {"sandbox_id": "parent"}),
    ({}, {"sandbox_lease_owner_id": "parent"}),
    ({}, {"sandbox_command_scope_id": "parent"}),
    ({}, {"sandbox_network_decisions_applied": set()}),
    ({"messages": [HumanMessage(content="allow", additional_kwargs={"human_input_response": {"source": "sandbox_network"}})]}, {}),
    ({"messages": [ToolMessage(content="pending", tool_call_id="parent", artifact={"human_input": {"source": "sandbox_network"}})]}, {}),
]


@pytest.mark.parametrize("state,extra", UNSAFE_STATES)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_inherited_capabilities_fail_before_provider_or_cleanup(monkeypatch, state, extra, asynchronous):
    _forbid_provider(monkeypatch)
    sandbox = SandboxMiddleware(available_skills=set())
    assert _configure(sandbox)
    context = {"thread_id": "new", "user_id": "owner", **extra}
    runtime = Runtime(context=context)
    if asynchronous:
        for hook in (sandbox.abefore_agent, sandbox.aafter_agent):
            with pytest.raises(SandboxRuntimeError, match="cannot inherit"):
                asyncio.run(hook(state, runtime))
    else:
        for hook in (sandbox.before_agent, sandbox.after_agent):
            with pytest.raises(SandboxRuntimeError, match="cannot inherit"):
                hook(state, runtime)
    assert context == {"thread_id": "new", "user_id": "owner", **extra}


def _request(candidate=present_file_tool):
    runtime = ToolRuntime(state={}, context={"thread_id": "clean"}, config={}, stream_writer=lambda event: None, tool_call_id="native-call", store=None)
    return ToolCallRequest(tool_call={"id": "native-call", "name": "present_files", "args": {}}, tool=candidate, state=runtime.state, runtime=runtime)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_fabricated_call_and_result_cannot_introduce_sandbox(asynchronous):
    sandbox = SandboxMiddleware(available_skills=set())
    assert _configure(sandbox, [present_file_tool])
    called = []

    def handler(request):
        called.append(True)
        return Command(update={"sandbox": {"sandbox_id": "injected"}})

    async def ahandler(request):
        return handler(request)

    with pytest.raises(SandboxRuntimeError, match="lacks"):
        if asynchronous:
            asyncio.run(sandbox.awrap_tool_call(_request(present_file_tool.model_copy()), ahandler))
        else:
            sandbox.wrap_tool_call(_request(present_file_tool.model_copy()), handler)
    assert called == []
    with pytest.raises(SandboxRuntimeError, match="cannot inherit"):
        if asynchronous:
            asyncio.run(sandbox.awrap_tool_call(_request(), ahandler))
        else:
            sandbox.wrap_tool_call(_request(), handler)
    assert called == [True]


@pytest.mark.parametrize("getter", [get_sandbox_provider, get_initialized_sandbox_provider])
def test_native_scope_denies_even_cached_provider_and_resets(monkeypatch, getter):
    sentinel = object()
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider._default_sandbox_provider", sentinel)
    with native_tool_execution():
        with pytest.raises(SandboxRuntimeError, match="cannot resolve"):
            getter()
    assert getter() is sentinel


def test_native_scope_is_task_local_copies_to_thread_and_resets_after_cancellation(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider._default_sandbox_provider", sentinel)

    async def run():
        started = asyncio.Event()
        finish = asyncio.Event()

        async def denied():
            try:
                with native_tool_execution():
                    with pytest.raises(SandboxRuntimeError, match="cannot resolve"):
                        await asyncio.to_thread(get_sandbox_provider)
                    started.set()
                    await finish.wait()
            finally:
                assert get_sandbox_provider() is sentinel

        task = asyncio.create_task(denied())
        await started.wait()
        assert get_sandbox_provider() is sentinel
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert get_sandbox_provider() is sentinel

    asyncio.run(run())


@pytest.fixture
def real_executor(monkeypatch):
    """Load real lifecycle without conftest's circular-import placeholder."""
    from pathlib import Path

    name = "deerflow.subagents.native_startup_test_executor"
    path = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_no_tool_child_graph_never_projects_or_initializes(monkeypatch, app, real_executor, asynchronous):
    model = RecordingModel(messages=iter([AIMessage(content="READY")]))
    monkeypatch.setattr(real_executor, "create_chat_model", lambda **kwargs: model)
    _forbid_provider(monkeypatch)
    executor = real_executor.SubagentExecutor(
        config=SubagentConfig(name="no-tools", description="Public synthetic worker", skills=[], tools=[]),
        tools=[],
        app_config=app,
        user_id="native-owner",
        thread_id="child-thread",
        parent_model="offline",
        extensions=LoadedExtensions(app_store=ExtensionData("app")),
    )
    graph = executor._create_agent()
    context = {"thread_id": "child-thread", "user_id": "native-owner", "is_subagent": True}
    state = {"messages": [HumanMessage(content="Reply READY.")]}

    async def run():
        with detect_blocking_io_strict():
            return await graph.ainvoke(state, context=context)

    result = asyncio.run(run()) if asynchronous else graph.invoke(state, context=context)
    assert executor._native_lazy_startup
    assert result["messages"][-1].content == "READY"
    assert not result.get("sandbox")
    assert not any(key.startswith("sandbox") for key in context)


def test_real_child_outer_lifecycle_omits_unused_lease_and_preserves_parent_snapshot(monkeypatch, app, real_executor):
    model = RecordingModel(messages=iter([AIMessage(content="READY")]))
    monkeypatch.setattr(real_executor, "create_chat_model", lambda **kwargs: model)
    _forbid_provider(monkeypatch)
    monkeypatch.setattr(real_executor, "build_tracing_callbacks", lambda: [])
    child = real_executor.SubagentExecutor(
        config=SubagentConfig(name="no-tools", description="Public synthetic worker", skills=[], tools=[]),
        tools=[],
        app_config=app,
        user_id="native-owner",
        thread_id="child-thread",
        parent_model="offline",
        extensions=LoadedExtensions(app_store=ExtensionData("app")),
    )

    async def run(executor):
        with detect_blocking_io_strict():
            return await executor._aexecute_admitted("Reply READY.")

    result = asyncio.run(run(child))
    assert result.status == real_executor.SubagentStatus.COMPLETED
    assert model.call_count == 1
    parent = {"sandbox_id": "must-not-release"}
    model2 = RecordingModel(messages=iter([AIMessage(content="must not run")]))
    monkeypatch.setattr(real_executor, "create_chat_model", lambda **kwargs: model2)
    blocked = real_executor.SubagentExecutor(
        config=child.config, tools=[], app_config=app, user_id="native-owner", thread_id="child-thread", parent_model="offline", extensions=LoadedExtensions(app_store=ExtensionData("app")), sandbox_state=parent
    )
    rejected = asyncio.run(run(blocked))
    assert rejected.status == real_executor.SubagentStatus.FAILED
    assert "cannot inherit" in rejected.error
    assert model2.call_count == 0
    assert parent == {"sandbox_id": "must-not-release"}
