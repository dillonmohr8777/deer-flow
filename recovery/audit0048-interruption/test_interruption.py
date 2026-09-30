"""Offline CLI failure-boundary regression against the exact frozen installer.

The proposed one-line patch is applied in memory. Original source is never edited.
Docker calls are replaced with a strict immutable-ID fake transport.
"""

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

FROZEN = Path(
    "/Users/dillonmohr/Documents/Codex/2026-09-30/new-realtime-voice-chat/"
    "audit0048-installation-v4-prepared/install.py"
)
FROZEN_SHA256 = "0bbfef91337f7fed44be772b95b3d8ccd9bd7e88e22488e4e3d807e28579c1d2"
OLD = "    except Exception as error:\n        stopped = driver.failstop()"
NEW = "    except BaseException as error:\n        stopped = driver.failstop()"
CANDIDATE_ID = "a" * 64


def load_installer(patched, monkeypatch):
    raw = FROZEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FROZEN_SHA256
    source = raw.decode()
    assert source.count(OLD) == 1
    if patched:
        source = source.replace(OLD, NEW)
    monkeypatch.syspath_prepend(str(FROZEN.parent))
    module = types.ModuleType("frozen_install_review")
    module.__file__ = str(FROZEN)
    exec(compile(source, str(FROZEN), "exec"), module.__dict__)  # noqa: S102 - exact SHA-bound reviewed source
    return module


def cli_fixture(module, monkeypatch, tmp_path, error, recreated):
    approval = tmp_path / "synthetic-approval.json"
    approval.write_text("{}")
    (tmp_path / "source-bindings.json").write_text(
        json.dumps(
            {
                "authority_scope_review_sha256": "scope",
                "ownership_scope_sha256": "ownership",
            }
        )
    )
    receipt = tmp_path / "receipts"
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr(module, "file_binding", lambda path: {"sha256": "synthetic"})
    monkeypatch.setattr(module, "verify_package", lambda: "frozen")
    monkeypatch.setattr(module, "approval_gate", lambda *args: None)
    monkeypatch.setattr(
        module.shutil,
        "disk_usage",
        lambda path: types.SimpleNamespace(free=20 * 1024**3),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install.py",
            "--execute-approved-migration",
            "--approval",
            str(approval),
            "--approval-sha256",
            "synthetic",
            "--receipt-dir",
            str(receipt),
        ],
    )
    calls = []
    state = {"running": recreated, "nonce": None}

    def interrupted_execute(driver, approval):
        driver.recreation_requested = recreated
        driver.candidate_id = CANDIDATE_ID if recreated else None
        driver.stage = "candidate_recreation_requested" if recreated else "prepared"
        state["nonce"] = driver.run_id
        raise error

    def transport(argv, **kwargs):
        args = argv[3:]
        calls.append(args)
        if args == ["inspect", CANDIDATE_ID]:
            value = {
                "Id": CANDIDATE_ID,
                "Image": module.CANDIDATE,
                "State": {"Running": state["running"]},
                "Config": {
                    "Labels": {
                        module.RUN_LABEL: state["nonce"],
                        "com.docker.compose.project": "momobot-standby",
                        "com.docker.compose.service": "gateway",
                    }
                },
            }
            return subprocess.CompletedProcess(
                argv, 0, json.dumps([value]).encode(), b""
            )
        assert args == ["stop", "--time", "2", CANDIDATE_ID], "unowned Docker action"
        state["running"] = False
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(module.Driver, "execute", interrupted_execute)
    monkeypatch.setattr(subprocess, "run", transport)
    return receipt, state, calls


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_frozen_v4_negative_control_reproduces_missing_failstop(
    monkeypatch, tmp_path, error_type
):
    module = load_installer(False, monkeypatch)
    error = error_type("synthetic interrupt")
    receipt, state, calls = cli_fixture(module, monkeypatch, tmp_path, error, True)
    with pytest.raises(error_type) as raised:
        module.main()
    assert raised.value is error
    assert state["running"] is True
    assert calls == []
    assert not (receipt / "stopped-receipt.json").exists()


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, RuntimeError])
@pytest.mark.parametrize("recreated", [False, True])
def test_patch_cleans_up_and_reraises_identical_failure(
    monkeypatch, tmp_path, error_type, recreated
):
    module = load_installer(True, monkeypatch)
    error = error_type("synthetic interrupt")
    receipt, state, calls = cli_fixture(module, monkeypatch, tmp_path, error, recreated)
    with pytest.raises(error_type) as raised:
        module.main()
    assert raised.value is error
    assert state["running"] is False
    saved = json.loads((receipt / "stopped-receipt.json").read_text())
    assert saved["reason"] == error_type.__name__
    assert saved["automatic_restore_retry_or_downgrade"] is False
    assert saved["native_provider_calls"] == 0
    assert saved["candidate_failstop"]["candidate_stopped"] is recreated
    assert calls == (
        [
            ["inspect", CANDIDATE_ID],
            ["stop", "--time", "2", CANDIDATE_ID],
            ["inspect", CANDIDATE_ID],
        ]
        if recreated
        else []
    )
