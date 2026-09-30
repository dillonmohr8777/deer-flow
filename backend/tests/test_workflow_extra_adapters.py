"""Actual Agno and Inngest lifecycle handoffs, offline and without credentials."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("framework", ["agno", "agentkit"])
async def test_actual_framework_lifecycle_one_admitted_call_and_exact_output(framework):
    if framework == "agno":
        worker = ROOT / "workers/agno-team"
        command = [str(worker / ".venv/bin/python"), str(worker / "worker.py")]
        if not Path(command[0]).exists():
            pytest.skip("isolated Agno environment not installed")
    else:
        worker = ROOT / "workers/inngest-team"
        if not (worker / "node_modules/@inngest/agent-kit").exists():
            pytest.skip("isolated Inngest environment not installed")
        node = shutil.which("node")
        assert node is not None, "installed AgentKit worker requires the configured Node runtime"
        command = [node, str(worker / "worker.js")]
    data = {
        "type": "invoke",
        "version": 1,
        "call_id": "offline-call",
        "worker_id": "writer",
        "role": "writer",
        "prompt": "Use synthetic evidence to draft JSON",
        "continuation": [],
        "output_schema": {"type": "object", "properties": {"draft": {"type": "string"}}, "required": ["draft"], "additionalProperties": False},
        "model": "gpt-6.1-sol",
        "effort": "low",
        "max_output_tokens": 512,
    }
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=worker,
        env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1", "OTEL_SDK_DISABLED": "true", "AGNO_TELEMETRY": "false"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(20):
            process.stdin.write(json.dumps(data).encode() + b"\n")
            await process.stdin.drain()
            raw = await process.stdout.readline()
            if not raw:
                raise AssertionError((await process.stderr.read()).decode()[:2000])
            request = json.loads(raw)
            assert request["type"] == "model_request"
            assert request["call_id"] == data["call_id"]
            assert any("synthetic evidence" in message["content"] for message in request["messages"])
            output = {"draft": "A real framework lifecycle with a synthetic provider receipt"}
            process.stdin.write(json.dumps({"type": "model_result", "version": 1, "call_id": data["call_id"], "result": {"output": output, "usage": {"input_tokens": 12, "output_tokens": 15, "cost": None}}}).encode() + b"\n")
            await process.stdin.drain()
            final = json.loads(await process.stdout.readline())
            assert final == {"type": "result", "version": 1, "call_id": data["call_id"], "output": output}
            await process.wait()
            assert process.returncode == 0
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
