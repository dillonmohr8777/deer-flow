"""Synthetic EC2 nightly archives test throwaway restoration only."""

import hashlib
import importlib.util
import io
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/momentum/ec2/restore_check.py"
spec = importlib.util.spec_from_file_location("restore_check", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def pack(root, target):
    with tarfile.open(target, "w:gz") as archive:
        for path in sorted(root.iterdir()):
            archive.add(path, arcname="./" + path.name)


def backup(tmp_path, *, rows=1, corrupt_db=False, bad_hash=False):
    stage = tmp_path / "stage"
    stage.mkdir()
    gateway = tmp_path / "gateway"
    gateway.mkdir()
    db = gateway / "deerflow.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE records (value TEXT)")
        conn.executemany("INSERT INTO records VALUES (?)", [("synthetic",)] * rows)
    if corrupt_db:
        db.write_bytes(b"corrupt sqlite")
    (gateway / ".deployment-backup-receipt.json").write_text(json.dumps({"state": "PASS", "databases": {"deerflow.db": {"integrity": "ok", "rows": {"records": rows}}}}))
    pack(gateway, stage / "gateway-data.tgz")
    mounts = tmp_path / "mounts"
    for name in ("skills", "admission", "lobby-notes", "brand", "evals"):
        (mounts / "data" / name).mkdir(parents=True)
    (mounts / "code").mkdir()
    for name in ("momo_guard.py", "momo_protocol.py", "brain_readonly_adapter.py"):
        (mounts / "code" / name).write_text("# synthetic\n")
    pack(mounts, stage / "ec2-mounts.tgz")
    (stage / "ec2-recovery.json").write_text(
        json.dumps(
            {"settings.env": dict.fromkeys(("MOMOBOT_DOMAIN", "MOMOBOT_ACME_EMAIL", "MOMENTUM_GATEWAY_IMAGE", "MOMENTUM_FRONTEND_IMAGE", "GATEWAY_ENABLE_DOCS"), "synthetic"), "frontend.env": {"MOMO_DAILY_CLOUD_OWNER_USER_ID": "synthetic"}}
        )
    )
    (stage / "config.yaml").write_text("models: []\n")
    (stage / "extensions_config.json").write_text('{"mcpServers": {}}')
    (stage / "redis.rdb").write_bytes(b"REDIS0011synthetic")
    manifest = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}\n" for p in sorted(stage.iterdir()))
    (stage / "MANIFEST.sha256").write_text(manifest.replace(manifest[:64], "0" * 64, 1) if bad_hash else manifest)
    target = tmp_path / "backup.tgz"
    pack(stage, target)
    return target


def test_valid_restore_preserves_source(tmp_path):
    source = backup(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).digest()
    result = checker.verify_backup(source)
    assert result["state"] == "PASS"
    assert result["database_count"] == 1
    assert result["row_count"] == 1
    assert hashlib.sha256(source.read_bytes()).digest() == digest


@pytest.mark.parametrize("kwargs", [{"bad_hash": True}, {"corrupt_db": True}, {"rows": 0}])
def test_damaged_or_empty_backup_fails(tmp_path, kwargs):
    with pytest.raises((ValueError, sqlite3.Error)):
        checker.verify_backup(backup(tmp_path, **kwargs))


@pytest.mark.parametrize("name,kind,link", [("../escape", tarfile.REGTYPE, ""), ("/absolute", tarfile.REGTYPE, ""), ("link", tarfile.SYMTYPE, "../../escape"), ("link", tarfile.LNKTYPE, "../escape"), ("device", tarfile.CHRTYPE, "")])
def test_unsafe_archive_rejected(tmp_path, name, kind, link):
    archive = tmp_path / "unsafe.tgz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(name)
        info.type, info.linkname = kind, link
        info.size = 1 if kind == tarfile.REGTYPE else 0
        handle.addfile(info, io.BytesIO(b"x") if info.size else None)
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError):
        checker.unpack(archive, target)
    assert not (tmp_path / "escape").exists()


def test_missing_payload_fails(tmp_path):
    source = backup(tmp_path)
    (tmp_path / "stage/redis.rdb").unlink()
    pack(tmp_path / "stage", source)
    with pytest.raises(ValueError):
        checker.verify_backup(source)


def test_unpack_budget_and_duplicate_paths(tmp_path):
    archive = tmp_path / "oversize.tgz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("data")
        info.size = 2
        handle.addfile(info, io.BytesIO(b"xx"))
        handle.addfile(info, io.BytesIO(b"xx"))
    for budget in ([1, 10], [10, 0], [10, 10]):
        target = tmp_path / str(budget)
        target.mkdir()
        with pytest.raises(ValueError):
            checker.unpack(archive, target, budget)


def test_receipt_count_mismatch_fails(tmp_path):
    source = backup(tmp_path)
    receipt = tmp_path / "gateway/.deployment-backup-receipt.json"
    payload = json.loads(receipt.read_text())
    payload["databases"]["deerflow.db"]["rows"]["records"] = 99
    receipt.write_text(json.dumps(payload))
    stage = tmp_path / "stage"
    pack(tmp_path / "gateway", stage / "gateway-data.tgz")
    manifest = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}\n" for p in sorted(stage.iterdir()) if p.name != "MANIFEST.sha256")
    (stage / "MANIFEST.sha256").write_text(manifest)
    pack(stage, source)
    with pytest.raises(ValueError, match="row counts"):
        checker.verify_backup(source)


def test_cli_exit_status_and_private_temp_cleanup(tmp_path):
    import os
    import subprocess
    import sys

    source = backup(tmp_path)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env = dict(os.environ, TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary))
    result = subprocess.run([sys.executable, str(SCRIPT), str(source)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["state"] == "PASS"
    assert not list(temporary.iterdir())
    source.write_bytes(b"not-a-backup-private-marker")
    result = subprocess.run([sys.executable, str(SCRIPT), str(source)], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)["state"] == "FAIL"
    assert "private-marker" not in result.stdout + result.stderr
    assert not result.stderr
    assert not list(temporary.iterdir())


@pytest.mark.parametrize("case", ["internal", "escape", "chain-escape", "cycle", "broken", "ancestor"])
def test_deferred_relative_symlinks(tmp_path, case):
    source = tmp_path / "links.tgz"
    with tarfile.open(source, "w:gz") as archive:
        info = tarfile.TarInfo("package/cli.js")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"ok"))
        links = {
            "internal": [("bin/tool", "../package/cli.js"), ("alias", "bin/tool")],
            "escape": [("bin/tool", "../../outside")],
            "chain-escape": [("alias", "bin/tool"), ("bin/tool", "../../outside")],
            "cycle": [("a", "b"), ("b", "a")],
            "broken": [("bin/tool", "missing")],
            "ancestor": [("package", "somewhere")],
        }[case]
        for name, link in links:
            info = tarfile.TarInfo(name)
            info.type, info.linkname = tarfile.SYMTYPE, link
            archive.addfile(info)
    target = tmp_path / "target"
    target.mkdir()
    if case == "internal":
        checker.unpack(source, target)
        assert (target / "alias").read_bytes() == b"ok"
        assert (target / "bin/tool").is_symlink()
    else:
        with pytest.raises(ValueError):
            checker.unpack(source, target)
