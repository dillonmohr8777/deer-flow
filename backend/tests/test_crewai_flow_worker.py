"""Actual isolated Flow -> Crew execution; no provider or persistence involved."""

import json
import subprocess
from pathlib import Path

import pytest

from app.gateway.workflow_adapters import worker_environment

WORKER = Path(__file__).resolve().parents[2] / "workers/browser-teams/python"


@pytest.mark.parametrize("call_id,answer", [("flow_first", "First result"), ("flow_second", "Second result")])
def test_real_flow_crew_is_ephemeral_and_returns_exact_parent_result(tmp_path, call_id, answer):
    output = {"answer": answer}
    invocation = {
        "type": "invoke",
        "version": 1,
        "call_id": call_id,
        "framework": "crewai",
        "model": "gpt-6.1-sol",
        "effort": "low",
        "max_output_tokens": 256,
        "input_token_limit": 60000,
        "worker_id": "offline_writer",
        "role": "Writer",
        "prompt": "Complete the bounded offline fixture.",
        "continuation": [],
        "output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False},
    }
    model_result = {"type": "model_result", "version": 1, "call_id": call_id, "result": {"output": output, "model": "gpt-6.1-sol", "effort": "low", "usage": {"input_tokens": 12, "output_tokens": 8, "cost": None}}}
    completed = subprocess.run(
        [str(WORKER / ".venv/bin/python"), str(WORKER / "worker.py"), "crewai"],
        input=json.dumps(invocation) + "\n" + json.dumps(model_result) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=worker_environment(),
        cwd=tmp_path,
        timeout=30,
        check=False,
    )
    frames = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 0, frames
    assert [frame["type"] for frame in frames] == ["model_request", "result"]
    assert all(frame["call_id"] == call_id for frame in frames)
    assert frames[-1]["output"] == output
    assert frames[-1]["worker_lifecycle"] == {
        "framework": "crewai",
        "flow_steps": 1,
        "crew_calls": 1,
        "model_handoffs": 1,
        "persistence": False,
        "checkpoint": False,
        "memory": False,
        "tracing": False,
        "sqlite_connections_allowed": False,
        "auth_token_access": False,
        "storage_scope": "private_temporary",
    }
    # The worker denies sqlite3.connect before importing either framework.
    # Together with the real kickoff this catches default Flow/Crew storage.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("guarded", [True, False])
def test_disabled_tracing_never_touches_host_auth_or_settings(tmp_path, guarded):
    # Install traps before importing the worker/CrewAI. A real TokenManager
    # storage access or host settings lookup must fail the subprocess, rather
    # than being hidden by the worker's generic CLI error frame.
    wrapper = """
import json, os, runpy, sys, tempfile
from pathlib import Path
from crewai_core.token_manager import TokenManager
attempts = []
def deny_storage():
    attempts.append(True)
    raise AssertionError("host_auth_storage_access")
TokenManager._get_secure_storage_path = staticmethod(deny_storage)
temporary = os.path.realpath(tempfile.gettempdir()) + "/momobot-crewai-"
def audit(event, args):
    if event not in ("open", "os.mkdir") or not isinstance(args[0], (str, bytes)):
        return
    path = os.path.realpath(os.fsdecode(args[0]))
    if "/crewai/credentials" in path:
        raise AssertionError("host_auth_file_access")
    if event == "os.mkdir" and ("/.local/share/" in path or "/Library/Application Support/" in path):
        raise AssertionError("host_settings_access")
    if path.endswith(".crewai_user.json") and not path.startswith(temporary):
        raise AssertionError("host_settings_access")
sys.addaudithook(audit)
worker = sys.argv[1]
guarded = sys.argv[2] == "true"
sys.argv = [worker, "crewai"]
main = runpy.run_path(worker)["main"]
if not guarded:
    main.__globals__["disable_crewai_host_storage"] = lambda _scratch: None
main()
print(json.dumps({"type":"isolation_audit","auth_storage_attempts":len(attempts)}))
"""
    invocation = {
        "type": "invoke",
        "version": 1,
        "call_id": "auth-trap",
        "framework": "crewai",
        "model": "gpt-6.1-sol",
        "effort": "low",
        "max_output_tokens": 256,
        "worker_id": "writer",
        "role": "Writer",
        "prompt": "Return the synthetic JSON object.",
        "continuation": [],
        "output_schema": {"type": "object"},
    }
    reply = {"type": "model_result", "version": 1, "call_id": "auth-trap", "result": {"output": {"answer": "Synthetic guarded Flow"}, "usage": {"input_tokens": 12, "output_tokens": 8, "cost": None}}}
    completed = subprocess.run(
        [str(WORKER / ".venv/bin/python"), "-c", wrapper, str(WORKER / "worker.py"), str(guarded).lower()],
        input=json.dumps(invocation) + "\n" + json.dumps(reply) + "\n",
        text=True,
        capture_output=True,
        env=worker_environment(),
        cwd=tmp_path,
        timeout=30,
    )
    frames = [json.loads(line) for line in completed.stdout.splitlines()]
    if not guarded:
        assert completed.returncode != 0
        assert "host_auth_storage_access" in completed.stderr or "host_settings_access" in completed.stderr
        assert not frames
        assert list(tmp_path.iterdir()) == []
        return
    assert completed.returncode == 0, completed.stderr
    assert [frame["type"] for frame in frames] == ["model_request", "result", "isolation_audit"]
    assert frames[1]["output"] == {"answer": "Synthetic guarded Flow"}
    assert frames[1]["worker_lifecycle"]["model_handoffs"] == 1
    assert frames[-1]["auth_storage_attempts"] == 0
    assert list(tmp_path.iterdir()) == []
