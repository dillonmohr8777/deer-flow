"""Regression coverage for deploy/momentum/vps/health.sh (f25): a backup whose
restore check failed still writes a fresh receipt, and health.sh used to look
only at the newest receipt's mtime, so a FAIL backup reported "ok":true. Also
pins portability: the Mac reuses this script, and BSD stat/date have no
`stat -c` / `date -Is`.

Runs the real script with stub `docker` and `curl` on PATH, so neither Docker
nor a network is needed.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH_SH = REPO_ROOT / "deploy" / "momentum" / "vps" / "health.sh"
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")


def _write_executable(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_health(tmp_path: Path, receipt: dict | None) -> tuple[int, dict]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "docker", "#!/usr/bin/env bash\nexit 0\n")
    # health.sh's probe() only reads curl's -w '%{http_code}' output.
    _write_executable(bin_dir / "curl", "#!/usr/bin/env bash\nprintf 200\n")
    backups = tmp_path / "backups"
    backups.mkdir()
    if receipt is not None:
        (backups / "gateway-data-20260928-031500.receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    log = tmp_path / "log" / "health.jsonl"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["MOMOBOT_DOMAIN"] = ""
    env["MOMOBOT_ENV_FILE"] = str(tmp_path / "missing.env")
    env["MOMOBOT_BACKUP_DEST"] = str(backups)
    env["MOMOBOT_HEALTH_LOG"] = str(log)
    proc = subprocess.run([BASH, str(HEALTH_SH)], env=env, capture_output=True, text=True, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no output; stderr={proc.stderr}"
    return proc.returncode, json.loads(lines[-1])


def test_fresh_pass_receipt_is_healthy(tmp_path):
    code, line = _run_health(tmp_path, {"state": "PASS", "file": "gateway-data-x.tgz.enc"})
    assert line["backupAgeHours"] == 0
    assert line["ok"] is True
    assert code == 0


def test_fresh_fail_receipt_is_unhealthy(tmp_path):
    code, line = _run_health(tmp_path, {"state": "FAIL", "file": "gateway-data-x.tgz.enc"})
    assert line["ok"] is False
    assert code == 1


def test_nested_pass_does_not_mask_top_level_fail(tmp_path):
    # f90: offsite_backup.py always embeds a PASS snapshot receipt even when
    # the overall backup fails, so a naive "does PASS appear anywhere" check
    # reports healthy on a real FAIL receipt.
    code, line = _run_health(
        tmp_path,
        {
            "state": "FAIL",
            "file": "gateway-data-x.tgz.enc",
            "snapshot": {"state": "PASS"},
            "postgres": {"state": "FAIL"},
        },
    )
    assert line["ok"] is False
    assert code == 1


def test_missing_receipt_is_unhealthy(tmp_path):
    code, line = _run_health(tmp_path, None)
    assert line["backupAgeHours"] is None
    assert line["ok"] is False
    assert code == 1
