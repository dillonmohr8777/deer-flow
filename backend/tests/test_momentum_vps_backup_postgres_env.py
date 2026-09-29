"""Regression coverage for deploy/momentum/vps/backup.sh's Postgres wiring
(f21): the script must hand offsite_backup.py enough to find and dump the
VPS's live Postgres container, detected only from POSTGRES_PASSWORD's
presence in .env (the same signal compose.postgres.yaml itself requires),
and must never leak that password's value into the environment it hands off.

Runs the real backup.sh with a stubbed `docker` on PATH (no real Docker or
Postgres needed) that snapshots the shell's environment the moment
backup.sh's own `docker image inspect` check runs -- after the script has
derived and exported the Postgres variables, but before it hands off to
offsite_backup.py. What happens after that point (which needs real Docker)
is not this test's concern; `check=False` deliberately ignores it.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SH = REPO_ROOT / "deploy" / "momentum" / "vps" / "backup.sh"
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")


def _write_executable(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_backup_sh(tmp_path: Path, env_file_body: str, *, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured = tmp_path / "captured-env.txt"
    # Dumps the environment on every invocation; the first is backup.sh's own
    # `docker image inspect`, which runs right after the variables under test
    # are exported and before the script hands off to offsite_backup.py.
    _write_executable(bin_dir / "docker", f"#!/usr/bin/env bash\nenv > {captured}\nexit 0\n")

    env_file = tmp_path / ".env"
    env_file.write_text(env_file_body, encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["MOMOBOT_ENV_FILE"] = str(env_file)
    # In case the stubbed docker lets the real offsite_backup.py run further
    # than expected, keep every path it might touch confined to tmp_path
    # rather than the script's Windows-shaped, cwd-relative defaults.
    env["MOMOBOT_BACKUP_KEY"] = str(tmp_path / "secrets" / "momobot-backup.key")
    env["MOMOBOT_BACKUP_DEST"] = str(tmp_path / "backups")
    env.pop("MOMOBOT_BACKUP_POSTGRES_CONTAINER", None)
    env.pop("MOMOBOT_PROJECT", None)
    if extra_env:
        env.update(extra_env)

    # check=False: past the docker-image check, the real script execs the
    # system python3 against the real offsite_backup.py, which needs real
    # Docker to succeed. Irrelevant here -- the environment was already
    # captured by the stub `docker image inspect` call above.
    subprocess.run([BASH, str(BACKUP_SH)], cwd=tmp_path, env=env, check=False, capture_output=True)
    assert captured.exists(), "docker was never invoked; backup.sh did not reach its image check"
    lines = captured.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_no_postgres_password_leaves_postgres_env_unset(tmp_path):
    captured = _run_backup_sh(tmp_path, "MOMENTUM_GATEWAY_IMAGE=test-image\n")
    assert "MOMOBOT_BACKUP_POSTGRES_CONTAINER" not in captured
    assert "MOMOBOT_BACKUP_POSTGRES_USER" not in captured
    assert "MOMOBOT_BACKUP_POSTGRES_DB" not in captured


def test_postgres_password_present_derives_default_container_and_role(tmp_path):
    captured = _run_backup_sh(
        tmp_path,
        "MOMENTUM_GATEWAY_IMAGE=test-image\nPOSTGRES_PASSWORD=super-secret-value\n",
    )
    assert captured["MOMOBOT_BACKUP_POSTGRES_CONTAINER"] == "deer-flow-postgres"
    assert captured["MOMOBOT_BACKUP_POSTGRES_USER"] == "deerflow"
    assert captured["MOMOBOT_BACKUP_POSTGRES_DB"] == "deerflow"
    # The password's own value must never appear anywhere in what gets handed
    # to offsite_backup.py -- pg_dump runs inside the container's own trusted
    # local socket and never needs it.
    assert not any("super-secret-value" in value for value in captured.values())


def test_postgres_password_present_honors_project_and_custom_role(tmp_path):
    captured = _run_backup_sh(
        tmp_path,
        "MOMENTUM_GATEWAY_IMAGE=test-image\nPOSTGRES_PASSWORD=x\nPOSTGRES_USER=momo\nPOSTGRES_DB=momodb\n",
        extra_env={"MOMOBOT_PROJECT": "hermes"},
    )
    assert captured["MOMOBOT_BACKUP_POSTGRES_CONTAINER"] == "hermes-postgres"
    assert captured["MOMOBOT_BACKUP_POSTGRES_USER"] == "momo"
    assert captured["MOMOBOT_BACKUP_POSTGRES_DB"] == "momodb"
