"""Offline checks for deploy/momentum/ec2/release.sh: the box half against stub systemctl/docker/curl.

A real git origin and checkout stand in for /opt/momobot/src; nothing touches Docker, systemd or the network.
The stub stack "runs" whatever image tags settings.env holds, so a smoke failure on a bad image proves the
automatic rollback restores the previous source and tags.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash release script")

REPO = Path(__file__).parents[2]
SCRIPT = REPO / "deploy/momentum/ec2/release.sh"

STUBS = {
    "systemctl": 'echo "$*" >> "$STUB_LOG"',
    "flock": "exit 0",
    "df": "printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nfake 1 1 99999999 1%% /\\n'",
    # `docker image inspect` misses (forces a build); `docker inspect -f ... <name>` reports what settings.env holds.
    "docker": """[[ "$1" == image ]] && exit 1
key=MOMENTUM_GATEWAY_IMAGE; [[ "${!#}" == deer-flow-frontend ]] && key=MOMENTUM_FRONTEND_IMAGE
sed -n "s/^$key=//p" "$MOMOBOT_DEPLOY_DIR/settings.env\"""",
    # Readiness always passes; the public smoke answers 502 while BAD_IMAGE is the configured gateway.
    "curl": """url="${!#}"
if [[ "$url" == https://* ]] && grep -qx "MOMENTUM_GATEWAY_IMAGE=${BAD_IMAGE:-none}" "$MOMOBOT_DEPLOY_DIR/settings.env"; then echo 502; else echo 200; fi""",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def box(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (bin_dir / name).chmod(0o755)

    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    deploy = tmp_path / "deploy"
    src = deploy / "src"
    _git(tmp_path, "clone", "-q", str(origin), str(src))
    for args in (("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        _git(src, *args)
    (src / "deploy/momentum/vps").mkdir(parents=True)
    (src / "deploy/momentum/lightsail").mkdir(parents=True)
    (src / "deploy/momentum/vps/dotenv-get.sh").write_text((REPO / "deploy/momentum/vps/dotenv-get.sh").read_text())
    (src / "deploy/momentum/lightsail/up.sh").write_text('#!/usr/bin/env bash\necho "build $MOMENTUM_GATEWAY_IMAGE $MOMENTUM_FRONTEND_IMAGE" >> "$STUB_LOG"\n')
    for f in ("vps/dotenv-get.sh", "lightsail/up.sh"):
        (src / "deploy/momentum" / f).chmod(0o755)
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "A")
    old = _git(src, "rev-parse", "HEAD")
    _git(src, "commit", "-q", "--allow-empty", "-m", "B")
    new = _git(src, "rev-parse", "HEAD")
    _git(src, "push", "-q", "origin", "HEAD:main")
    _git(src, "checkout", "-q", "--detach", old)

    (deploy / "settings.env").write_text("MOMOBOT_DOMAIN=example.test\nMOMENTUM_GATEWAY_IMAGE=gw:old\nMOMENTUM_FRONTEND_IMAGE=fe:old\n")
    (tmp_path / "env").write_text("MOMOBOT_DOMAIN=example.test\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MOMOBOT_DEPLOY_DIR": str(deploy),
        "MOMOBOT_ENV_FILE": str(tmp_path / "env"),
        "MOMOBOT_RELEASE_LEDGER": str(tmp_path / "releases.jsonl"),
        "MOMOBOT_RELEASE_LOCK": str(tmp_path / "lock"),
        "STUB_LOG": str(tmp_path / "stub.log"),
    }

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True, timeout=60)

    def state() -> dict:
        settings = dict(line.split("=", 1) for line in (deploy / "settings.env").read_text().splitlines())
        ledger = tmp_path / "releases.jsonl"
        return {
            "head": _git(src, "rev-parse", "HEAD"),
            "gateway": settings["MOMENTUM_GATEWAY_IMAGE"],
            "frontend": settings["MOMENTUM_FRONTEND_IMAGE"],
            "ledger": [json.loads(x) for x in ledger.read_text().splitlines()] if ledger.exists() else [],
            "stub": (tmp_path / "stub.log").read_text() if (tmp_path / "stub.log").exists() else "",
            "prev": (deploy / "release-prev.env").read_text() if (deploy / "release-prev.env").exists() else "",
        }

    return run, state, old, new


def test_release_builds_swaps_and_records_previous(box):
    run, state, old, new = box
    result = run("box-release", new)
    assert result.returncode == 0, result.stderr
    s = state()
    tag = f"main-{new[:8]}"
    assert (s["head"], s["gateway"], s["frontend"]) == (new, f"deer-flow-gateway:{tag}", f"deer-flow-frontend:{tag}")
    assert f"build deer-flow-gateway:{tag} deer-flow-frontend:{tag}" in s["stub"] and "restart momobot" in s["stub"]
    assert s["prev"] == f"PREV_SRC={old}\nPREV_GATEWAY=gw:old\nPREV_FRONTEND=fe:old\n"
    assert [(e["action"], e["ok"]) for e in s["ledger"]] == [("release", True)]

    rolled = run("box-rollback")
    assert rolled.returncode == 0, rolled.stderr
    assert (state()["head"], state()["gateway"], state()["frontend"]) == (old, "gw:old", "fe:old")


def test_failed_smoke_rolls_back_on_its_own(box):
    run, state, old, new = box
    result = run("box-release", new, BAD_IMAGE=f"deer-flow-gateway:main-{new[:8]}")
    assert result.returncode != 0 and "rolled back" in result.stderr
    s = state()
    assert (s["head"], s["gateway"], s["frontend"]) == (old, "gw:old", "fe:old")
    assert [(e["action"], e["ok"]) for e in s["ledger"]] == [("release", False), ("auto-rollback", True)]
    assert s["stub"].count("restart momobot") == 2 and s["prev"] == ""


def test_refuses_commit_not_on_main(box):
    run, state, _old, _new = box
    result = run("box-release", "0" * 40)
    assert result.returncode != 0
    assert state()["stub"] == "" and state()["gateway"] == "gw:old"
