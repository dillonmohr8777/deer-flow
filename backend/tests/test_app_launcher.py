"""Offline subprocess-boundary tests for the private app's credential isolation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_momobot_openai_app.py"
_SPEC = importlib.util.spec_from_file_location("private_app_launcher", _SCRIPT)
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


class LaunchCaptured(Exception):
    def __init__(self, executable, argv, env):
        super().__init__("Offline child launch captured; environment values omitted")
        self.executable = str(executable)
        self.argv = argv
        self.env = env.copy()


@pytest.fixture
def launch_setup(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.yaml").write_text("auth:\n  local:\n    allow_registration: false\n")
    source = tmp_path / "private.env"
    source.write_text(
        "OPENAI_API_KEY=fixture-openai-source\n"
        "MOMOBOT_OPENAI_AGENTS_ENABLED=true\n"
        "BROWSERBASE_API_KEY=fixture-browserbase-source\n"
        "MOMOBOT_BROWSERBASE_ENABLED=true\n"
        "MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT=6000\n"
        "DEER_FLOW_AUTH_DISABLED=1\n"
        "DEER_FLOW_ENV=development\n"
        "DEER_FLOW_AUTH_COOKIE_PREFIX=unsafe_\n"
        "GATEWAY_HOST=0.0.0.0\n"
        "UNRELATED_SECRET=fixture-unrelated-source\n"
    )
    source.chmod(0o600)
    for name, value in {
        "OPENAI_API_KEY": "fixture-openai-inherited",
        "BROWSERBASE_API_KEY": "fixture-browserbase-inherited",
        "OPENROUTER_API_KEY": "fixture-openrouter-inherited",
        "UNRELATED_SECRET": "fixture-inherited-secret",
        "DEER_FLOW_AUTH_DISABLED": "1",
        "DEER_FLOW_ENV": "development",
        "DEER_FLOW_AUTH_COOKIE_PREFIX": "unsafe_inherited_",
        "NODE_OPTIONS": "--require /unsafe.js",
        "PYTHONPATH": "/unsafe-module-path",
        "GATEWAY_HOST": "0.0.0.0",
        "GATEWAY_WORKERS": "25",
        "NEXT_PUBLIC_OPENAI_API_KEY": "fixture-public-secret",
    }.items():
        monkeypatch.setenv(name, value)
    chdir = []
    monkeypatch.setattr(launcher.os, "chdir", chdir.append)
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "/offline/bin/node")

    def capture(executable, argv, env):
        raise LaunchCaptured(executable, argv, env)

    monkeypatch.setattr(launcher.os, "execve", capture)

    def invoke(service, *, env_file=source, extra=()):
        argv = [str(_SCRIPT), service, "--state-dir", str(state), "--env-file", str(env_file), *extra]
        monkeypatch.setattr(sys, "argv", argv)
        launcher.main()

    return invoke, state, source, chdir


def test_frontend_never_inherits_provider_or_auth_bypass_environment(launch_setup, monkeypatch):
    import dotenv

    invoke, _state, _source, chdir = launch_setup
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *_args, **_kwargs: pytest.fail("Frontend read Gateway secrets"))
    with pytest.raises(LaunchCaptured) as captured:
        invoke("frontend")
    child = captured.value
    safe_keys = {"PATH", "HOME", "LANG", "TMPDIR", "DEER_FLOW_ENV", "DEER_FLOW_AUTH_COOKIE_PREFIX", "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL"}
    assert set(child.env) <= safe_keys
    assert not any("KEY" in name or "SECRET" in name or "AUTH_DISABLED" in name for name in child.env)
    assert child.env["DEER_FLOW_ENV"] == "production"
    assert child.env["DEER_FLOW_AUTH_COOKIE_PREFIX"] == "momo_agent_"
    assert child.env["DEER_FLOW_INTERNAL_GATEWAY_BASE_URL"] == "http://127.0.0.1:8040"
    assert child.argv[-4:] == ["--hostname", "127.0.0.1", "--port", "3040"]
    assert chdir[-1].name == "frontend"


def test_gateway_loads_only_five_provider_settings_and_forces_auth_production(launch_setup):
    invoke, state, _source, chdir = launch_setup
    with pytest.raises(LaunchCaptured) as captured:
        invoke("gateway")
    child = captured.value
    provider_keys = {"OPENAI_API_KEY", "MOMOBOT_OPENAI_AGENTS_ENABLED", "BROWSERBASE_API_KEY", "MOMOBOT_BROWSERBASE_ENABLED", "MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT"}
    safe_keys = {"PATH", "HOME", "LANG", "TMPDIR", "DEER_FLOW_ENV", "DEER_FLOW_AUTH_COOKIE_PREFIX", "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL", "DEER_FLOW_HOME", "DEER_FLOW_PROJECT_ROOT", "DEER_FLOW_CONFIG_PATH", "GATEWAY_HOST", "GATEWAY_PORT"}
    assert set(child.env) <= provider_keys | safe_keys
    assert provider_keys <= set(child.env)
    assert child.env["OPENAI_API_KEY"] == "fixture-openai-source"
    assert child.env["BROWSERBASE_API_KEY"] == "fixture-browserbase-source"
    assert child.env["DEER_FLOW_ENV"] == "production"
    assert "DEER_FLOW_AUTH_DISABLED" not in child.env
    assert child.env["DEER_FLOW_AUTH_COOKIE_PREFIX"] == "momo_agent_"
    assert child.env["GATEWAY_HOST"] == "127.0.0.1"
    assert child.env["DEER_FLOW_HOME"] == str(state.resolve())
    assert child.env["DEER_FLOW_CONFIG_PATH"] == str(state.resolve() / "config.yaml")
    assert "--workers" not in child.argv
    assert child.argv[-6:] == ["--host", "127.0.0.1", "--port", "8040", "--log-level", "warning"]
    assert chdir[-1].name == "backend"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660, 0o664, 0o666])
def test_gateway_rejects_group_or_world_readable_environment_file(launch_setup, mode):
    invoke, _state, source, chdir = launch_setup
    source.chmod(mode)
    with pytest.raises(SystemExit) as rejected:
        invoke("gateway")
    assert rejected.value.code == 2
    assert chdir == []


def test_gateway_rejects_symlink_secret_source(launch_setup):
    invoke, _state, source, chdir = launch_setup
    symlink = source.with_name("linked.env")
    symlink.symlink_to(source)
    with pytest.raises(SystemExit) as rejected:
        invoke("gateway", env_file=symlink)
    assert rejected.value.code == 2
    assert chdir == []


@pytest.mark.parametrize("service", ["gateway", "frontend"])
@pytest.mark.parametrize("argument,value", [("--gateway-port", "80"), ("--gateway-port", "1023"), ("--gateway-port", "65536"), ("--frontend-port", "0"), ("--frontend-port", "-1"), ("--frontend-port", "65536")])
def test_invalid_ports_are_rejected_before_either_service_launch(launch_setup, service, argument, value):
    invoke, _state, _source, chdir = launch_setup
    with pytest.raises(SystemExit) as rejected:
        invoke(service, extra=(argument, value))
    assert rejected.value.code == 2
    assert chdir == []


@pytest.mark.parametrize("service", ["gateway", "frontend"])
def test_gateway_and_frontend_cannot_claim_the_same_port(launch_setup, service):
    invoke, _state, _source, chdir = launch_setup
    with pytest.raises(SystemExit) as rejected:
        invoke(service, extra=("--gateway-port", "8040", "--frontend-port", "8040"))
    assert rejected.value.code == 2
    assert chdir == []
