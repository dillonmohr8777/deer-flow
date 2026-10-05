"""Opt-in offline acceptance of an already built disposable worker image."""

import json
import os
import subprocess

import pytest


def test_packaged_workers_execute_without_network_or_writable_root():
    image = os.environ.get("MOMOBOT_WORKER_SMOKE_IMAGE")
    if not image:
        pytest.skip("set MOMOBOT_WORKER_SMOKE_IMAGE to an already built reviewed local image")
    docker = ["docker"]
    context = os.environ.get("MOMOBOT_WORKER_SMOKE_CONTEXT")
    if context:
        docker += ["--context", context]
    config = subprocess.run(docker + ["image", "inspect", image, "--format", "{{json .Config.WorkingDir}} {{json .Config.Cmd}}"], check=True, capture_output=True, text=True, timeout=30)
    assert config.stdout.startswith('"/app" ')
    assert "cd backend" in config.stdout
    startup = subprocess.run(
        docker
        + [
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=256m",
            "--env",
            "UV_CACHE_DIR=/tmp/uv-cache",
            "--env",
            "DEER_FLOW_HOME=/tmp/worker-startup-smoke",
            "--env",
            "MOMOBOT_WORKFLOWS_ENABLED=false",
            "--env",
            "MOMOBOT_OPENAI_AGENTS_ENABLED=false",
            "--env",
            "MOMOBOT_BROWSERBASE_ENABLED=false",
            image,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # No private runtime config is baked into the image. The inherited command
    # reaches Gateway lifespan and fails closed at its existing config boundary.
    assert startup.returncode != 0
    assert "config.yaml` file not found" in startup.stderr
    assert "can't cd" not in startup.stderr
    command = docker + [
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--workdir",
        "/app/backend",
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m",
        "--env",
        "PYTHONPATH=.",
        "--entrypoint",
        "/app/backend/.venv/bin/python",
        image,
        "scripts/verify_workflow_workers.py",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["frameworks"] == ["langgraph", "crewai", "deepagents", "mastra", "agno", "agentkit"]
    assert receipt["paid_provider_calls"] == receipt["live_browser_sessions"] == 0
    assert receipt["synthetic_model_handoffs"] == 6 and receipt["stagehand_installed"] is True
    assert receipt["versions"]["crewai"] == receipt["versions"]["agno"] == "3.13"
    gateway = subprocess.run(
        docker + ["run", "--rm", "--network", "none", "--entrypoint", "/app/backend/.venv/bin/python", image, "-c", "import sys, importlib.metadata as m; print('.'.join(map(str,sys.version_info[:2]))); print(m.version('openai'))"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert gateway.stdout.splitlines() == ["3.12", "3.22.1"]
