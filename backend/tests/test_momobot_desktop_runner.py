"""Desktop runner: quiet-hours gate, STOP file, timeout and claim flow with claude mocked."""

from __future__ import annotations

import importlib.util
import stat
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "momobot_desktop_runner.py"
spec = importlib.util.spec_from_file_location("momobot_desktop_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def _gate(tmp_path, code: int) -> str:
    path = tmp_path / f"gate{code}"
    path.write_text(f"#!/bin/sh\nexit {code}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    folder = tmp_path / "client-a"
    folder.mkdir()
    monkeypatch.setenv("MOMOBOT_STOP_FILE", str(tmp_path / "STOP"))
    monkeypatch.setenv("MOMOBOT_QUIET_HOURS_BIN", _gate(tmp_path, 1))  # 1 = outside quiet hours
    calls: list[tuple[str, str, dict | None]] = []
    queue: list[dict] = []

    def fake_api(method, path, body=None):
        calls.append((method, path, body))
        if path.endswith("/claim"):
            return {"items": [queue.pop(0)] if queue else []}
        return {"valid": True, "cancel_requested": False, "ok": True}

    monkeypatch.setattr(runner, "api", fake_api)
    cfg = {"clients": {"client-a": str(folder)}, "allowed_tools": ["Read", "Grep"], "claude_bin": "claude", "timeout_seconds": 5}
    return SimpleEnv(cfg, calls, queue, folder, tmp_path)


class SimpleEnv:
    def __init__(self, cfg, calls, queue, folder, tmp_path):
        self.cfg, self.calls, self.queue, self.folder, self.tmp_path = cfg, calls, queue, folder, tmp_path

    def item(self, **kw):
        return {"id": "i1", "lane": "desktop", "approval_state": "approved", "client_id": "client-a", "prompt": "do the thing", **kw}

    def fake_claude(self, body: str) -> None:
        path = self.tmp_path / "fakeclaude"
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.cfg["claude_bin"] = str(path)


def test_quiet_hours_gate_claims_nothing_and_missing_gate_fails_closed(env, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MOMOBOT_QUIET_HOURS_BIN", _gate(tmp_path, 0))  # 0 = inside quiet hours
    env.queue.append(env.item())
    assert runner.run_once(env.cfg) == "quiet"
    assert env.calls == []
    monkeypatch.setenv("MOMOBOT_QUIET_HOURS_BIN", str(tmp_path / "does-not-exist"))
    assert runner.run_once(env.cfg) == "quiet"
    assert env.calls == []


def test_stop_file_blocks_claim(env) -> None:
    Path(runner.stop_file()).write_text("")
    assert runner.run_once(env.cfg) == "stopped"
    assert env.calls == []


def test_claim_runs_haiku_in_client_folder_and_finalizes(env, monkeypatch) -> None:
    seen = {}

    def fake_run(cfg, prompt, folder, *, on_tick=None):
        seen.update(prompt=prompt, folder=folder, argv=runner.claude_argv(cfg, prompt, folder))
        return True, "draft ready"

    monkeypatch.setattr(runner, "run_claude", fake_run)
    env.queue.append(env.item())
    assert runner.run_once(env.cfg) == "done"
    assert seen["folder"] == str(env.folder)
    argv = seen["argv"]
    assert argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--allowedTools") + 1] == "Read,Grep"
    assert argv.count("--add-dir") == 1 and argv[argv.index("--add-dir") + 1] == str(env.folder)
    paths = [p for _, p, _ in env.calls]
    assert paths == ["/api/fleet/work/claim", "/api/fleet/work/i1/running", "/api/fleet/work/i1/finalize"]
    final = env.calls[-1][2]
    assert (final["succeeded"], final["result"], final["model_name"]) == (True, "draft ready", "haiku")


@pytest.mark.parametrize("overrides", [{"approval_state": "pending"}, {"lane": "haiku"}, {"client_id": "client-zzz"}])
def test_unapproved_wrong_lane_or_unmapped_client_is_refused_not_run(env, monkeypatch, overrides) -> None:
    monkeypatch.setattr(runner, "run_claude", lambda *a, **k: pytest.fail("claude must not run"))
    env.queue.append(env.item(**overrides))
    assert runner.run_once(env.cfg).startswith("refused")
    assert env.calls[-1][1].endswith("/finalize") and env.calls[-1][2]["succeeded"] is False


def test_stop_file_kills_running_claude(env) -> None:
    env.fake_claude("sleep 30")
    env.cfg["timeout_seconds"] = 60
    threading.Timer(0.5, lambda: runner.stop_file().write_text("")).start()
    assert runner.run_claude(env.cfg, "p", str(env.folder)) == (False, "Killed: STOP file present")


def test_timeout_kills_running_claude(env) -> None:
    env.fake_claude("sleep 30")
    env.cfg["timeout_seconds"] = 0.5
    assert runner.run_claude(env.cfg, "p", str(env.folder)) == (False, "Killed: timed out")


def test_dry_run_never_contacts_gateway_or_claude(env, monkeypatch, capsys) -> None:
    monkeypatch.setattr(runner, "load_config", lambda: env.cfg)
    monkeypatch.setattr(runner, "api", lambda *a, **k: pytest.fail("dry-run must not call the Gateway"))
    monkeypatch.setattr(runner, "run_claude", lambda *a, **k: pytest.fail("dry-run must not start claude"))
    monkeypatch.setenv("MOMOBOT_HOST_KEY", "super-secret-key")
    assert runner.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--model haiku" in out and "host_key_set=True" in out and "super-secret-key" not in out


def test_gateway_calls_carry_a_matching_csrf_pair(monkeypatch):
    """The Gateway's CSRF double-submit check applies to internal-token calls too."""
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=30):
        seen.update({k.lower(): v for k, v in request.header_items()})
        return _Resp()

    monkeypatch.setenv("MOMOBOT_GATEWAY_URL", "http://gw")
    monkeypatch.setenv("MOMOBOT_HOST_KEY", "k")
    monkeypatch.setenv("MOMOBOT_DELEGATION_ID", "d")
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    runner.api("POST", "/api/fleet/work/claim", {"lanes": ["desktop"]})
    token = seen["x-csrf-token"]
    assert token and seen["cookie"] == f"csrf_token={token}"
