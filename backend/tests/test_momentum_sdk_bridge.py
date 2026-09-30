"""Offline host admission and real isolated SDK round-trip."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.momentum_sdk_access import prepare_sdk_reviewer
from deerflow.community.momentum_sdk.bridge import WorkerSpec
from deerflow.community.momentum_sdk.tools import momentum_sdk_draft
from deerflow.config.tool_config import ToolConfig
from deerflow.constants import MOMENTUM_SDK_CONTEXT_KEY as KEY
from deerflow.constants import MOMENTUM_SDK_TOOL_USE
from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context, _release_run_scoped_references
from deerflow.tools.tools import get_available_tools
from deerflow.tools.types import Runtime


def registry(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "queue").mkdir()
    (tmp_path / "registry/clients.json").write_text(json.dumps({"clients": [{"id": "synthetic-client", "status": "active"}]}))
    (tmp_path / "queue/work-items.json").write_text(json.dumps({"revision": 7, "workItems": []}))
    return tmp_path


def spec():
    interpreter = os.environ.get("MOMENTUM_SDK_TEST_PYTHON")
    if not interpreter:
        pytest.skip("Optional SDK interpreter not supplied; no download")
    return WorkerSpec(Path(interpreter), Path(__file__).resolve().parents[2] / "examples/momentum-sdk-review/worker.py")


def config():
    return SimpleNamespace(
        tools=[ToolConfig(name="momentum_sdk_draft", group="momentum_sdk", use=MOMENTUM_SDK_TOOL_USE)],
        sandbox=SimpleNamespace(use="example.remote:Sandbox"),
        skill_evolution=SimpleNamespace(enabled=False),
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
    )


def test_default_and_explicit_group_admission():
    for kwargs in ({}, {"groups": ["momentum_sdk"]}, {"include_momentum_sdk": True}, {"groups": ["other"], "include_momentum_sdk": True}):
        assert "momentum_sdk_draft" not in [t.name for t in get_available_tools(include_mcp=False, app_config=config(), **kwargs)]
    assert "momentum_sdk_draft" in [t.name for t in get_available_tools(groups=["momentum_sdk"], include_momentum_sdk=True, include_mcp=False, app_config=config())]


@pytest.mark.asyncio
async def test_tool_denies_missing_capability_and_subagent():
    host = AsyncMock()
    for context in ({}, {KEY: host, "is_subagent": True}):
        assert "error" in json.loads(await momentum_sdk_draft.coroutine("synthetic-client", "Synthetic", SimpleNamespace(context=context)))
    host.assert_not_called()


def test_worker_replaces_forged_context_and_cleans_up():
    host = AsyncMock()
    forged = object()
    assert KEY not in _build_runtime_context("t", "r", {KEY: forged})
    runtime = _build_runtime_context("t", "r", {KEY: forged}, momentum_sdk_reviewer=host)
    cfg = {"context": {KEY: forged}, "configurable": {KEY: forged}}
    _install_runtime_context(cfg, runtime)
    assert cfg["context"][KEY] is host and runtime[KEY] is host
    assert KEY not in cfg["configurable"]
    _release_run_scoped_references([cfg], runtime, None)
    assert KEY not in runtime and KEY not in cfg["context"]


@pytest.mark.asyncio
async def test_real_langchain_sdk_packet_exact_scope_readonly(tmp_path, monkeypatch):
    root = registry(tmp_path)
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    kwargs = dict(owner_id="alice", thread_id="t", run_id="r", client_ids={"synthetic-client"}, canonical_root=root, worker=spec())
    assert prepare_sdk_reviewer(**kwargs) is None
    host = prepare_sdk_reviewer(enabled=True, **kwargs)
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_SENTINEL_NOT_FOR_CHILD")
    context = _build_runtime_context("t", "r", {"user_id": "alice"}, momentum_sdk_reviewer=host)
    runtime = Runtime(state={}, context=context, config={}, stream_writer=lambda _: None, tools=[], tool_call_id="synthetic-call", store=None)
    packet = json.loads(await momentum_sdk_draft.ainvoke({"client_id": "synthetic-client", "request": "Synthetic request", "runtime": runtime}))
    assert packet["client_id"] == "synthetic-client" and packet["status"] == "draft"
    assert "synthetic" in packet["found"].lower() and packet["evidence"]
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}
    for client_id in ("alias", "../synthetic-client"):
        assert "error" in json.loads(await momentum_sdk_draft.coroutine(client_id, "Synthetic", SimpleNamespace(context=context)))
    for key in ("user_id", "thread_id", "run_id"):
        assert "error" in json.loads(await momentum_sdk_draft.coroutine("synthetic-client", "Synthetic", SimpleNamespace(context=dict(context, **{key: "wrong"}))))


@pytest.mark.asyncio
async def test_symlink_registry_rejected(tmp_path):
    root = registry(tmp_path)
    target = root / "registry/clients.json"
    other = root / "other.json"
    other.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(other)
    host = prepare_sdk_reviewer(enabled=True, owner_id="alice", thread_id="t", run_id="r", client_ids={"synthetic-client"}, canonical_root=root, worker=spec())
    assert "error" in json.loads(await host(client_id="synthetic-client", request="Synthetic", user_id="alice", thread_id="t", run_id="r"))


def fake_spec(tmp_path, body, timeout=2):
    import sys

    script = tmp_path / "fake_worker.py"
    script.write_text(body)
    return WorkerSpec(Path(sys.executable), script, timeout_seconds=timeout)


def host_for(root, worker):
    return prepare_sdk_reviewer(enabled=True, owner_id="alice", thread_id="t", run_id="r", client_ids={"synthetic-client", "missing-client"}, canonical_root=root, worker=worker)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "import sys; sys.stdout.write('x'*20000)",
        "import sys; sys.stderr.write('SECRET_SENTINEL'*2000); raise SystemExit(2)",
        "print('not json')",
        'print(\'{"client_id":"other","status":"done"}\')',
    ],
)
async def test_output_caps_and_invalid_errors_are_sanitized(tmp_path, body):
    root = registry(tmp_path)
    host = host_for(root, fake_spec(tmp_path, body))
    result = await host(client_id="synthetic-client", request="Synthetic", user_id="alice", thread_id="t", run_id="r")
    assert "error" in json.loads(result) and "SECRET_SENTINEL" not in result and len(result) < 200


@pytest.mark.asyncio
async def test_minimal_child_environment(tmp_path, monkeypatch):
    root = registry(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_SENTINEL")
    monkeypatch.setenv("SLACK_TOKEN", "SECRET_SENTINEL")
    host = host_for(root, fake_spec(tmp_path, "import os,json; print(json.dumps(dict(os.environ)))"))
    output = json.loads(await host._execute(b"{}"))
    assert set(output) <= {"LANG", "LC_CTYPE", "OPENAI_AGENTS_DISABLE_TRACING", "PYTHONDONTWRITEBYTECODE", "__CF_USER_TEXT_ENCODING"}
    assert "SECRET_SENTINEL" not in json.dumps(output)


@pytest.mark.asyncio
async def test_timeout_and_cancellation_drain_process(tmp_path, monkeypatch):
    import asyncio

    root = registry(tmp_path)
    captured = []
    real_spawn = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        proc = await real_spawn(*args, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    worker = fake_spec(tmp_path, "import time; time.sleep(60)", timeout=0.1)
    host = host_for(root, worker)
    result = await host(client_id="synthetic-client", request="Synthetic", user_id="alice", thread_id="t", run_id="r")
    assert "error" in json.loads(result) and captured[-1].returncode is not None
    task = asyncio.create_task(host._execute(b"{}"))
    while len(captured) < 2:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captured[-1].returncode is not None


@pytest.mark.asyncio
async def test_unknown_canonical_and_input_bounds_never_spawn(tmp_path, monkeypatch):
    import asyncio

    root = registry(tmp_path)
    host = host_for(root, fake_spec(tmp_path, "raise RuntimeError('must not launch')"))
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    for client_id, request in (("missing-client", "Synthetic"), ("synthetic-client", ""), ("synthetic-client", "x" * 8001)):
        assert "error" in json.loads(await host(client_id=client_id, request=request, user_id="alice", thread_id="t", run_id="r"))
    spawn.assert_not_called()


def test_worker_symlink_rejected(tmp_path):
    import sys

    target = tmp_path / "target.py"
    target.write_text("print('synthetic')")
    script = tmp_path / "link.py"
    script.symlink_to(target)
    with pytest.raises(OSError):
        WorkerSpec(Path(sys.executable), script)
