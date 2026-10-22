# Private MCP auth binding must not make repository bootstrap import tools.

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("module", ["deerflow.persistence.models", "deerflow.config.agents_config", "app.gateway.services"])
def test_private_scope_preserves_cold_repository_and_gateway_imports(module):
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(backend / "packages/harness"), str(backend), str(backend / "tests")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=backend, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-5000:]
