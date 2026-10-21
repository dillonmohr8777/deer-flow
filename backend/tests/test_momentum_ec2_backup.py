"""EC2 mount recovery snapshots exclude env credentials and fail on missing mounts."""

from __future__ import annotations

import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/momentum/ec2/backup_extra.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ec2_backup_extra", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_deploy(tmp_path):
    deploy, stage = tmp_path / "deploy", tmp_path / "stage"
    stage.mkdir()
    for name in ("skills", "admission", "lobby-notes", "brand", "evals"):
        path = deploy / "data" / name
        path.mkdir(parents=True)
        (path / "keep.txt").write_text(name)
    (deploy / "code").mkdir()
    for name in ("momo_guard.py", "momo_protocol.py"):
        (deploy / "code" / name).write_text("# recovery module")
    (deploy / "settings.env").write_text("MOMOBOT_DOMAIN=example.test\nMOMENTUM_GATEWAY_IMAGE=gateway:test\nSECRET=do-not-back-up\n")
    (deploy / "frontend.env").write_text("MOMO_DAILY_CLOUD_OWNER_USER_ID=owner-test\nSECRET=do-not-back-up\n")
    return deploy, stage


def test_snapshot_roundtrip_and_credentials_excluded(tmp_path):
    module = load_module()
    deploy, stage = make_deploy(tmp_path)
    (deploy / "data/skills/.env").write_text("do-not-back-up")
    (deploy / "data/skills/private.env").write_text("do-not-back-up")
    module.snapshot(deploy, stage)
    with tarfile.open(stage / "ec2-mounts.tgz") as archive:
        names = archive.getnames()
        assert len([m for m in archive.getmembers() if m.isfile()]) == 7
        assert not any(name.endswith(".env") for name in names)
        assert archive.extractfile("data/skills/keep.txt").read() == b"skills"
    settings = json.loads((stage / "ec2-recovery.json").read_text())
    assert settings["settings.env"]["MOMOBOT_DOMAIN"] == "example.test"
    assert settings["frontend.env"] == {"MOMO_DAILY_CLOUD_OWNER_USER_ID": "owner-test"}
    assert "do-not-back-up" not in json.dumps(settings)


def test_missing_required_mount_fails_snapshot(tmp_path):
    module = load_module()
    deploy, stage = make_deploy(tmp_path)
    (deploy / "code/momo_guard.py").unlink()
    with pytest.raises(FileNotFoundError):
        module.snapshot(deploy, stage)


def test_symlink_is_refused_instead_of_archiving_external_data(tmp_path):
    module = load_module()
    deploy, stage = make_deploy(tmp_path)
    outside = tmp_path / "external-secret"
    outside.write_text("do-not-back-up")
    (deploy / "data/skills/link").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        module.snapshot(deploy, stage)
