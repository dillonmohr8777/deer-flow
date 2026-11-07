"""PC host release.sh: backup first, switch both tags, poll readiness, roll back on failure.

Runs the real script against a temp /opt/momobot-style directory with stub docker, curl, systemctl,
backup.sh and pc-up.sh, so nothing touches a host.
"""

from __future__ import annotations

import os
import pathlib
import stat
import subprocess
from types import SimpleNamespace

import pytest

PC_DIR = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "momentum" / "pc"
RELEASE = PC_DIR / "release.sh"
OLD, NEW = "aaaaaaaa", "bbbbbbbb"
OLD_TAGS = (f"deer-flow-gateway:main-{OLD}", f"deer-flow-frontend:main-{OLD}")
NEW_TAGS = (f"deer-flow-gateway:main-{NEW}", f"deer-flow-frontend:main-{NEW}")


def _exe(path: pathlib.Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def host(tmp_path: pathlib.Path) -> SimpleNamespace:
    deploy = tmp_path / "momobot"
    (deploy / "ops").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    env = deploy / ".env"
    env.write_text(
        f"SECRET_KEY=do-not-touch\nMOMENTUM_GATEWAY_IMAGE={OLD_TAGS[0]}\nMOMENTUM_FRONTEND_IMAGE={OLD_TAGS[1]}\n",
        encoding="utf-8",
    )
    env.chmod(0o600)
    # backup.sh succeeds unless the marker file exists
    _exe(deploy / "ops" / "backup.sh", f"echo backup >> {calls}\n[ ! -e {tmp_path}/backup-fails ]\n")
    # pc-up.sh records the gateway tag it sees and fails for the NEW tag when flagged
    _exe(
        deploy / "pc-up.sh",
        f'tag=$(grep ^MOMENTUM_GATEWAY_IMAGE= {env} | cut -d= -f2)\n'
        f'echo "pc-up $tag" >> {calls}\n'
        f'[[ "$tag" == *{NEW} && -e {tmp_path}/new-fails ]] && exit 3\nexit 0\n',
    )
    # docker: only the OLD and NEW images exist locally; `docker images` lists four tags per repo
    _exe(
        bin_dir / "docker",
        'if [[ "$1 $2" == "image inspect" ]]; then [[ "$3" == *-aaaaaaaa || "$3" == *-bbbbbbbb ]]; exit; fi\n'
        'if [[ "$1" == images ]]; then repo=${@: -1}; for t in cccccccc aaaaaaaa bbbbbbbb dddddddd; do echo "$repo:main-$t"; done; exit 0; fi\n'
        f'if [[ "$1 $2" == "image rm" ]]; then echo "rm $3" >> {calls}; exit 0; fi\nexit 0\n',
    )
    # curl: /health/ready is "starting" (503) while the NEW tag is flagged unready, else ready
    _exe(
        bin_dir / "curl",
        f"tag=$(grep ^MOMENTUM_GATEWAY_IMAGE= {env} | cut -d= -f2)\n"
        f'if [[ "$tag" == *{NEW} && -e {tmp_path}/new-unready ]]; then printf \'{{"status":"starting"}}\\n503\'; exit 0; fi\n'
        "printf '{\"status\":\"ready\"}\\n200'\n",
    )
    _exe(bin_dir / "systemctl", "exit 3\n")  # momobot-backup.service is not active
    run_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MOMOBOT_DEPLOY": str(deploy),
        "MOMOBOT_READY_TIMEOUT": "1",
        "MOMOBOT_READY_INTERVAL": "0.2",
    }

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(RELEASE), *args], env=run_env, text=True, capture_output=True, check=False)

    def tags() -> tuple[str, str]:
        lines = env.read_text(encoding="utf-8").splitlines()
        gateway = next(x for x in lines if x.startswith("MOMENTUM_GATEWAY_IMAGE=")).split("=", 1)[1]
        frontend = next(x for x in lines if x.startswith("MOMENTUM_FRONTEND_IMAGE=")).split("=", 1)[1]
        return gateway, frontend

    def recorded() -> list[str]:
        return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    return SimpleNamespace(run=run, tags=tags, recorded=recorded, deploy=deploy, root=tmp_path, env=env)


def test_happy_path_backs_up_first_switches_both_tags_and_clears_maintenance(host):
    result = host.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert host.tags() == NEW_TAGS
    assert host.recorded() == ["backup", f"pc-up {NEW_TAGS[0]}"]
    assert not (host.deploy / "MAINTENANCE").exists()
    assert "SECRET_KEY=do-not-touch" in host.env.read_text(encoding="utf-8")
    assert oct(host.env.stat().st_mode & 0o777) == "0o600"


def test_failed_backup_stops_before_anything_changes(host):
    (host.root / "backup-fails").write_text("")
    result = host.run(NEW)
    assert result.returncode != 0
    assert host.tags() == OLD_TAGS
    assert host.recorded() == ["backup"]
    assert not (host.deploy / "MAINTENANCE").exists()


def test_pc_up_failure_puts_the_previous_tags_back_and_restarts_on_them(host):
    (host.root / "new-fails").write_text("")
    result = host.run(NEW)
    assert result.returncode == 1
    assert host.tags() == OLD_TAGS
    assert host.recorded() == ["backup", f"pc-up {NEW_TAGS[0]}", f"pc-up {OLD_TAGS[0]}"]
    assert not (host.deploy / "MAINTENANCE").exists()
    assert "rolled-back" in (host.deploy / "release.log").read_text(encoding="utf-8")


def test_readiness_timeout_rolls_back(host):
    (host.root / "new-unready").write_text("")
    result = host.run(NEW)
    assert result.returncode == 1
    assert host.tags() == OLD_TAGS
    assert host.recorded()[-1] == f"pc-up {OLD_TAGS[0]}"


def test_same_tags_is_a_no_op(host):
    result = host.run(OLD)
    assert result.returncode == 0
    assert host.recorded() == []
    assert not (host.deploy / "MAINTENANCE").exists()


def test_dry_run_changes_nothing(host):
    result = host.run("--dry-run", NEW)
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert host.tags() == OLD_TAGS
    assert host.recorded() == []


def test_refuses_while_maintenance_exists_and_when_the_image_is_missing(host):
    maintenance = host.deploy / "MAINTENANCE"
    maintenance.write_text("")
    assert host.run(NEW).returncode == 1
    maintenance.unlink()
    assert host.run("deadbeef").returncode == 1
    assert host.recorded() == []


def test_prune_keeps_the_new_and_previous_tags_only(host):
    result = host.run("--prune", NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    removed = sorted(c for c in host.recorded() if c.startswith("rm "))
    assert removed == sorted(f"rm deer-flow-{r}:main-{t}" for r in ("gateway", "frontend") for t in ("cccccccc", "dddddddd"))
