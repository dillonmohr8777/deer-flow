"""Private preparation is append-only, backed up and fenced; globals stay unchanged."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.runtime.events.store import make_run_event_store
from deerflow.runtime.events.store.db import DbRunEventStore

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_momobot_openai_app.py"
SPEC = importlib.util.spec_from_file_location("private_journal_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def private_config(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    config = state / "config.yaml"
    raw = (
        b"# Preserve this owner configuration exactly.\n"
        b"auth:\n  local:\n    allow_registration: false\n"
        b"database:\n  backend: sqlite\n  sqlite_dir: /synthetic/existing/data\n"
        b"sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n"
        b"models: []\n# Credentials remain raw references: $PRIVATE_PROVIDER_KEY\n"
    )
    config.write_bytes(raw)
    config.chmod(0o600)
    return state, config, raw


def test_missing_private_journal_gets_db_without_rewriting_owner_bytes(private_config, monkeypatch):
    state, config, raw = private_config
    result = launcher.prepare_private_config(state, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert result["changed"] is True
    assert config.read_bytes() == raw + b"\nrun_events:\n  backend: db\n"
    backup = Path(result["backup"])
    assert backup.read_bytes() == raw
    assert backup.stat().st_mode & 0o777 == 0o600
    assert config.stat().st_mode & 0o777 == 0o600
    parsed = yaml.safe_load(config.read_bytes())
    configuration = AppConfig.model_validate(parsed)
    assert configuration.database.backend == "sqlite"
    assert configuration.database.sqlite_dir == "/synthetic/existing/data"
    assert configuration.run_events.backend == "db"
    factory = object()
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: factory)
    assert isinstance(make_run_event_store(configuration.run_events), DbRunEventStore)
    assert RunEventsConfig().backend == "memory"
    assert "$PRIVATE_PROVIDER_KEY" in config.read_text()


@pytest.mark.parametrize("backend", ["db", "memory", "jsonl"])
def test_explicit_owner_backend_is_preserved_without_backup(private_config, backend):
    state, config, raw = private_config
    original = raw + f"run_events:\n  backend: {backend}\n  max_trace_content: 2048\n".encode()
    config.write_bytes(original)
    result = launcher.prepare_private_config(state)
    assert result["changed"] is False and result["backend"] == backend
    assert config.read_bytes() == original
    assert sorted(path.name for path in state.iterdir()) == ["config.yaml"]


@pytest.mark.parametrize("section", ["run_events: null\n", "run_events: []\n", "run_events:\n  backend: unsafe\n"])
def test_invalid_explicit_owner_setting_fails_closed(private_config, section):
    state, config, raw = private_config
    original = raw + section.encode()
    config.write_bytes(original)
    with pytest.raises(ValueError, match="private_run_events_invalid"):
        launcher.prepare_private_config(state)
    assert config.read_bytes() == original
    assert len(list(state.iterdir())) == 1


def test_existing_memory_database_cannot_silently_fall_back_after_db_preparation(private_config):
    state, config, raw = private_config
    original = raw.replace(b"backend: sqlite", b"backend: memory")
    config.write_bytes(original)
    with pytest.raises(ValueError, match="private_sqlite_backend_required"):
        launcher.prepare_private_config(state)
    assert config.read_bytes() == original
    assert len(list(state.iterdir())) == 1


def test_expected_configuration_hash_fences_a_changed_owner_config(private_config):
    state, config, raw = private_config
    with pytest.raises(ValueError, match="private_config_changed"):
        launcher.prepare_private_config(state, expected_sha256="0" * 64)
    assert config.read_bytes() == raw
    assert len(list(state.iterdir())) == 1


@pytest.mark.parametrize("unsafe", ["state_mode", "config_mode", "config_symlink"])
def test_private_preparation_rejects_unsafe_paths_before_writing(private_config, unsafe):
    state, config, raw = private_config
    if unsafe == "state_mode":
        state.chmod(0o755)
    elif unsafe == "config_mode":
        config.chmod(0o644)
    else:
        target = state / "owner-source.yaml"
        config.rename(target)
        config.symlink_to(target)
    before = sorted(path.name for path in state.iterdir())
    with pytest.raises(ValueError, match="private_config_path_invalid"):
        launcher.prepare_private_config(state)
    assert config.read_bytes() == raw
    assert sorted(path.name for path in state.iterdir()) == before


def test_prepare_command_reads_no_provider_env_and_launches_no_service(private_config, monkeypatch, capsys):
    import dotenv

    state, config, raw = private_config
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *_args: pytest.fail("Preparation read provider credentials"))
    monkeypatch.setattr(launcher.os, "execve", lambda *_args: pytest.fail("Preparation launched a service"))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "prepare-config", "--state-dir", str(state), "--expected-config-sha256", hashlib.sha256(raw).hexdigest()])
    launcher.main()
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] and result["backend"] == "db"
    assert result["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert "PRIVATE_PROVIDER_KEY" not in json.dumps(result)


def test_failed_atomic_replacement_preserves_owner_config_and_exact_backup(private_config, monkeypatch):
    state, config, raw = private_config

    def reject_replace(*_args):
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr(launcher.os, "replace", reject_replace)
    with pytest.raises(OSError):
        launcher.prepare_private_config(state)
    assert config.read_bytes() == raw
    backups = list(state.glob("config.yaml.before-run-events-db-*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    assert not list(state.glob(".config-run-events-*"))


def test_preparation_never_reads_or_changes_signing_secret_or_database(private_config):
    state, _config, _raw = private_config
    secret = state / ".jwt_secret"
    secret.write_bytes(b"synthetic-do-not-read-or-regenerate")
    database = state / "data/deerflow.db"
    database.parent.mkdir()
    database.write_bytes(b"synthetic-existing-account-records")
    launcher.prepare_private_config(state)
    assert secret.read_bytes() == b"synthetic-do-not-read-or-regenerate"
    assert database.read_bytes() == b"synthetic-existing-account-records"
