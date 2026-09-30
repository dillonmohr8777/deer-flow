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
    }
    # The worker denies sqlite3.connect before importing either framework.
    # Together with the real kickoff this catches default Flow/Crew storage.
    assert list(tmp_path.iterdir()) == []
