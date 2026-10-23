"""Offline contracts for the disabled, non-executing diagnostic spool."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.gateway import wsl_bridge as bridge


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", str(tmp_path.resolve()))
    return bridge.BridgeStore.from_environment()


def enqueue(store, **changes):
    return store.enqueue(organization_id="org", actor_user_id="actor", storage_user_id="storage", thread_id="thread", request_id="request", argv=["/usr/bin/uname", "-s"], timeout=30, **changes)


def receipt(job, **changes):
    output = b"Linux\n"
    return {
        "id": job["id"],
        "key_sha256": job["key_sha256"],
        "state": "done",
        "exit_code": 0,
        "start_utc": "2026-10-22T12:00:00+00:00",
        "end_utc": "2026-10-22T12:00:01+00:00",
        "stdout_sha256": hashlib.sha256(output).hexdigest(),
        "stdout_bytes": len(output),
        "stdout_truncated": False,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_bytes": 0,
        "stderr_truncated": False,
        "stdout_b64": base64.b64encode(output).decode(),
        "stderr_b64": "",
        "duration_seconds": 1.0,
        "resource_limits": bridge.resource_limits(job["timeout"]),
        "limits_applied": True,
        **changes,
    }


def test_default_disabled_and_explicit_root(monkeypatch, tmp_path):
    monkeypatch.delenv("MOMO_WSL_BRIDGE_ENABLED", raising=False)
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", str(tmp_path / "unused"))
    with pytest.raises(bridge.BridgeError):
        bridge.BridgeStore.from_environment()
    assert not (tmp_path / "unused").exists()
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", "relative")
    with pytest.raises(bridge.BridgeError):
        bridge.BridgeStore.from_environment()


def test_identity_dedup_and_claim_restart(store):
    first = enqueue(store)
    expected_key = '["momo-wsl-v1","org","actor","thread","request"]'
    assert first["job"]["id"] == "momo-" + hashlib.sha256(expected_key.encode()).hexdigest()[:16]
    assert enqueue(store) == first
    claimed = store.claim()
    assert claimed["requests"] == [{"job": first["job"], "idempotency_key": expected_key}]
    assert bridge.BridgeStore.from_environment().claim() == claimed
    assert store.status(first["job"]["id"])["state"] == "claimed"


def test_changed_payload_and_short_digest_collision_hold(store, monkeypatch):
    first = enqueue(store)
    with pytest.raises(bridge.BridgeError):
        store.enqueue(organization_id="org", actor_user_id="actor", storage_user_id="storage", thread_id="thread", request_id="request", argv=["/usr/bin/true"], timeout=30)
    assert store.status(first["job"]["id"])["state"] == "held"
    assert store.claim()["requests"] == []
    monkeypatch.setattr(bridge, "job_id_for_digest", lambda digest: first["job"]["id"])
    with pytest.raises(bridge.BridgeError):
        store.enqueue(organization_id="other", actor_user_id="actor", storage_user_id="storage", thread_id="thread", request_id="request", argv=["/usr/bin/true"], timeout=30)


def test_cross_connection_concurrency_creates_one_row(store):
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: enqueue(bridge.BridgeStore.from_environment()), range(16)))
    assert all(result == results[0] for result in results)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("select count(*) from requests").fetchone()[0] == 1


def test_cross_process_enqueue_and_claim_are_fenced(store):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    code = """from app.gateway.wsl_bridge import BridgeStore,compact_json
s=BridgeStore.from_environment()
r=s.enqueue(organization_id='org',actor_user_id='actor',storage_user_id='storage',thread_id='thread',request_id='request',argv=['/usr/bin/uname','-s'],timeout=30)
print(compact_json(s.claim()))
"""
    processes = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(4)]
    try:
        outputs = [process.communicate(timeout=20) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
        assert all(json.loads(output[0]) == json.loads(outputs[0][0]) for output in outputs)
        with sqlite3.connect(store.path) as conn:
            assert conn.execute("select count(*) from requests").fetchone()[0] == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


@pytest.mark.parametrize(
    "changes",
    [
        {"stdout_sha256": "0" * 64},
        {"stdout_bytes": True},
        {"stdout_b64": "!"},
        {"stdout_bytes": 65537},
        {"duration_seconds": float("nan")},
        {"resource_limits": {}},
        {"exit_code": 1},
        {"limits_applied": False},
        {"stdout_truncated": True},
        {"end_utc": "2026-10-21T12:00:00+00:00"},
        {"id": "momo-0000000000000000"},
    ],
)
def test_bad_receipt_is_held_before_attachment(store, changes):
    job = enqueue(store)["job"]
    store.claim()
    with pytest.raises(bridge.BridgeError):
        store.ingest(job["id"], receipt(job, **changes))
    assert store.status(job["id"])["state"] == "held"
    assert store.read(job["id"])["receipt"] is None
    assert store.claim()["requests"] == []


def test_first_valid_receipt_and_metadata_independent_duplicate(store):
    job = enqueue(store)["job"]
    store.claim()
    first = store.ingest(job["id"], receipt(job, _pcw={"verified": True}))
    assert store.ingest(job["id"], receipt(job, _pcw={"verified": False})) == first
    assert first["state"] == "done" and first["attached"] is False
    assert store.claim()["requests"] == []
    with pytest.raises(bridge.BridgeError):
        store.ingest(job["id"], receipt(job, state="failed", exit_code=1))
    assert store.read(job["id"])["receipt"]["state"] == "done"


@pytest.mark.parametrize("state", ["held", "timeout"])
def test_uncertain_never_requeues(store, state):
    job = enqueue(store)["job"]
    store.claim()
    store.ingest(job["id"], receipt(job, state=state, exit_code=None))
    restarted = bridge.BridgeStore.from_environment()
    assert restarted.status(job["id"])["state"] == "unknown"
    assert restarted.claim()["requests"] == []


def test_malformed_partial_record_is_not_dispatched(store):
    job = enqueue(store)["job"]
    with sqlite3.connect(store.path) as conn:
        conn.execute("update requests set record='{}' where id=?", (job["id"],))
    with pytest.raises(bridge.BridgeError):
        store.claim()
    with pytest.raises(bridge.BridgeError):
        store.status(job["id"])


def test_outstanding_bound_and_read_without_creation(store, monkeypatch):
    assert store.claim() == {"protocol": bridge.PROTOCOL, "requests": []}
    assert not store.path.exists()
    monkeypatch.setattr(bridge, "MAX_OUTSTANDING", 1)
    enqueue(store)
    with pytest.raises(bridge.BridgeError):
        store.enqueue(organization_id="org", actor_user_id="actor", storage_user_id="storage", thread_id="thread", request_id="another", argv=["/usr/bin/true"], timeout=1)


def test_cli_protocol_status_claim_and_disabled(store, monkeypatch):
    job = enqueue(store)["job"]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    command = [sys.executable, "-m", "app.gateway.wsl_bridge"]
    claimed = subprocess.run(command + ["claim"], input="", text=True, capture_output=True, env=env, timeout=20)
    assert claimed.returncode == 0, claimed.stderr
    assert json.loads(claimed.stdout)["requests"][0]["job"] == job
    status = subprocess.run(command + ["status"], input=json.dumps({"job_id": job["id"]}), text=True, capture_output=True, env=env, timeout=20)
    assert json.loads(status.stdout)["state"] == "claimed"
    env.pop("MOMO_WSL_BRIDGE_ENABLED")
    disabled = subprocess.run(command + ["claim"], input="", text=True, capture_output=True, env=env, timeout=20)
    assert disabled.returncode != 0
    assert json.loads(disabled.stdout)["error"] == "WSL bridge is disabled"


def test_cli_receipt_calls_shared_ingest(store, monkeypatch, capsys):
    from app.gateway import wsl_bridge_attachment

    job = enqueue(store)["job"]
    store.claim()

    async def ingest(local_store, job_id, value):
        return local_store.ingest(job_id, value)

    monkeypatch.setattr(wsl_bridge_attachment, "ingest_local_receipt", ingest)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"job_id": job["id"], "receipt": receipt(job)}).encode())))
    assert bridge.main(["receipt"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["job_id"] == job["id"] and result["state"] == "done"


@pytest.mark.skipif(os.name != "posix", reason="Secure no-follow attachment is POSIX-only")
def test_fixed_artifact_survives_ack_restart_and_denies_links(tmp_path):
    from app.gateway.wsl_bridge_attachment import _attach_fixed_file

    target = tmp_path.resolve() / "outputs" / "receipt.json"
    _attach_fixed_file(target, b"receipt\n")
    _attach_fixed_file(target, b"receipt\n")
    assert [item.name for item in target.parent.iterdir()] == ["receipt.json"]
    with pytest.raises(bridge.BridgeError):
        _attach_fixed_file(target, b"conflict\n")
    linked = target.parent / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(bridge.BridgeError):
        _attach_fixed_file(linked, b"receipt\n")
