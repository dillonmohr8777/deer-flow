"""Regression coverage for deploy/momentum/offsite_backup.py's Postgres dump
(f21): the VPS runs workspace.config.postgres.yaml, so users, threads,
checkpoints and run_events live in Postgres, not the deer-flow_gateway-data
volume this script used to be the only thing it backed up. Loads the real
script by path (it is a standalone tool outside every Python package) and
fakes every `docker` invocation so the test needs neither Docker nor Postgres.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "deploy" / "momentum" / "offsite_backup.py"

TAR_BYTES = b"FAKE-GATEWAY-DATA-TAR-PAYLOAD"
PG_DUMP_BYTES = b"FAKE-PG-CUSTOM-FORMAT-DUMP-PAYLOAD"


class FakeCompleted:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b""):
        self.stdout = stdout
        self.stderr = stderr


def _fake_run_factory(*, pg_dump_fails: bool = False):
    def fake_run(cmd, *args, **kwargs):
        assert cmd[0] == "docker", f"unexpected executable: {cmd}"
        rest = tuple(cmd[1:])
        if rest[:2] == ("volume", "create") or rest[:2] == ("volume", "rm"):
            return FakeCompleted()
        if rest and rest[0] == "run":
            idx = rest.index("--entrypoint")
            entrypoint = rest[idx + 1]
            if entrypoint == "python":
                return FakeCompleted(stdout=b'{"state": "PASS", "rows": 3}\n')
            if entrypoint == "tar":
                return FakeCompleted(stdout=TAR_BYTES)
        if rest and rest[0] == "exec":
            if pg_dump_fails:
                raise subprocess.CalledProcessError(1, cmd, stderr=b"pg_dump: error: connection refused")
            return FakeCompleted(stdout=PG_DUMP_BYTES)
        raise AssertionError(f"unexpected docker invocation: {cmd}")

    return fake_run


def _load_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, with_postgres: bool):
    monkeypatch.setenv("MOMOBOT_BACKUP_KEY", str(tmp_path / "secrets" / "momobot-backup.key"))
    monkeypatch.setenv("MOMOBOT_BACKUP_DEST", str(tmp_path / "backups"))
    monkeypatch.setenv("MOMOBOT_BACKUP_VOLUME", "test-volume")
    monkeypatch.setenv("MOMOBOT_BACKUP_IMAGE", "test-image")
    monkeypatch.setenv("MOMOBOT_BACKUP_KEEP", "14")
    if with_postgres:
        monkeypatch.setenv("MOMOBOT_BACKUP_POSTGRES_CONTAINER", "deer-flow-postgres")
        monkeypatch.setenv("MOMOBOT_BACKUP_POSTGRES_USER", "deerflow")
        monkeypatch.setenv("MOMOBOT_BACKUP_POSTGRES_DB", "deerflow")
    else:
        monkeypatch.delenv("MOMOBOT_BACKUP_POSTGRES_CONTAINER", raising=False)
        monkeypatch.delenv("MOMOBOT_BACKUP_POSTGRES_USER", raising=False)
        monkeypatch.delenv("MOMOBOT_BACKUP_POSTGRES_DB", raising=False)

    spec = importlib.util.spec_from_file_location(f"offsite_backup_under_test_{tmp_path.name}", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_without_postgres_container_is_unaffected(monkeypatch, tmp_path):
    """No MOMOBOT_BACKUP_POSTGRES_CONTAINER (SQLite deployment): behaves exactly
    like before this change -- no postgres dump attempted, no dump.enc file, and
    the receipt's new "postgres" field is explicitly null rather than missing."""
    module = _load_module(monkeypatch, tmp_path, with_postgres=False)
    monkeypatch.setattr(module.subprocess, "run", _fake_run_factory())

    assert module.dump_postgres() is None

    result = module.backup()
    assert result["state"] == "PASS"
    assert result["postgres"] is None
    dest = Path(module.DEST)
    assert not list(dest.glob("postgres-*.dump.enc"))
    assert list(dest.glob("gateway-data-*.tgz.enc"))


def test_backup_with_postgres_container_encrypts_and_verifies_the_dump(monkeypatch, tmp_path):
    """MOMOBOT_BACKUP_POSTGRES_CONTAINER set (the VPS kit): the receipt shows a
    real pg_dump was taken and independently restore-checked, mirroring the
    volume tar's own restore check -- this is the "dry run" the accept bar asks
    for, proving a Postgres backup exists instead of a receipt that says PASS
    while the database went unbacked-up."""
    module = _load_module(monkeypatch, tmp_path, with_postgres=True)
    monkeypatch.setattr(module.subprocess, "run", _fake_run_factory())

    assert module.dump_postgres() == PG_DUMP_BYTES

    result = module.backup()
    assert result["state"] == "PASS"
    assert result["postgres"] is not None
    assert result["postgres"]["state"] == "PASS"

    dest = Path(module.DEST)
    pg_files = list(dest.glob("postgres-*.dump.enc"))
    assert len(pg_files) == 1
    assert pg_files[0].name == result["postgres"]["file"]

    # The receipt is what health.sh and a human reading /srv/momobot/backups
    # actually trust; it must be reloadable and carry the postgres block.
    receipt_path = dest / result["file"].replace(".tgz.enc", ".receipt.json")
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert on_disk["postgres"]["state"] == "PASS"

    # Full round trip through restore(): decrypt the dump file back to plaintext
    # and confirm it is byte-for-byte the pg_dump output, the same guarantee
    # restore() already gave the gateway-data volume tar.
    restore_dir = tmp_path / "restore-tmp"
    restore_dir.mkdir()
    monkeypatch.setenv("TEMP", str(restore_dir))
    module.restore(pg_files[0])
    restored = restore_dir / pg_files[0].with_suffix("").name
    assert restored.read_bytes() == PG_DUMP_BYTES


def test_postgres_dump_failure_is_not_silently_marked_pass(monkeypatch, tmp_path):
    """A configured-but-unreachable Postgres container must fail loudly, not
    leave the database out of a PASS receipt -- the exact bug f21 reports."""
    module = _load_module(monkeypatch, tmp_path, with_postgres=True)
    monkeypatch.setattr(module.subprocess, "run", _fake_run_factory(pg_dump_fails=True))

    with pytest.raises(SystemExit):
        module.dump_postgres()

    with pytest.raises(SystemExit):
        module.backup()
