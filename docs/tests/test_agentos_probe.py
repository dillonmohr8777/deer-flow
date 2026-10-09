"""Actual Agno AgentOS ASGI lifecycle and database checks, without provider I/O."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import jwt
import pytest

SOURCE = Path(__file__).resolve().parents[2] / "workers/agno-team/agentos_probe.py"
spec = importlib.util.spec_from_file_location("momo_agentos_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def invocation():
    return {
        "type": "invoke",
        "version": 1,
        "call_id": "agreed-specialist-call",
        "worker_id": "research-specialist",
        "role": "Research specialist",
        "model": "gpt-6.1-sol",
        "effort": "high",
        "framework": "agno",
        "prompt": "Summarize only this synthetic supplied evidence.",
        "continuation": [{"role": "assistant", "content": "Synthetic prior note."}],
        "output_schema": {"type": "object"},
    }


class OfflineBroker:
    def __init__(self):
        self.requests = []

    def exchange(self, request):
        self.requests.append(request)
        return {
            "type": "model_result",
            "version": 1,
            "call_id": request["call_id"],
            "result": {
                "output": {"finding": "Synthetic useful output"},
                "usage": {"input_tokens": 40, "output_tokens": 12},
            },
        }


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("The offline AgentOS probe must not use external I/O")

    async def async_denied(*_args, **_kwargs):
        denied()

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_denied)


@pytest.mark.asyncio
async def test_real_agentos_run_lifecycle_native_persistence_and_restart(tmp_path):
    broker = OfflineBroker()
    runtime = probe.AgentOSProbe(invocation(), broker, tmp_path / "state/native.sqlite")
    assert runtime.agent_os.telemetry is False
    assert runtime.agent_os.tracing is False
    assert runtime.agent_os._scheduler_enabled is False
    assert runtime.agent_os.queue is None
    async with runtime.client() as client:
        assert runtime.active
        health = await client.get("/health")
        assert health.status_code == 200
        result = await runtime.execute(client, "tenant-one")
        assert result["output"] == {"finding": "Synthetic useful output"}
        assert result["native"]["persisted"] is True
        assert result["native"]["run_id"]
        session_id = result["native"]["session_id"]
    assert not runtime.active
    assert runtime.lifecycle == ["started", "stopped"]
    assert len(broker.requests) == 1
    assert broker.requests[0]["type"] == "model_request"
    assert broker.requests[0]["call_id"] == invocation()["call_id"]
    assert broker.requests[0]["messages"][-1]["content"] == invocation()["prompt"]
    assert any(
        m["content"] == "Synthetic prior note." for m in broker.requests[0]["messages"]
    )

    restarted = probe.AgentOSProbe(invocation(), OfflineBroker(), runtime.db_file)
    async with restarted.client() as client:
        persisted = await restarted.readback(
            client, "tenant-one", session_id, result["native"]["run_id"]
        )
        assert persisted == result["output"]
        with pytest.raises(ValueError, match="probe_run_already_exists"):
            await restarted.execute(client, "tenant-one")
    assert restarted.broker.requests == []
    assert runtime.db_file.stat().st_mode & 0o777 == 0o600
    assert runtime.signing_key.encode() not in runtime.db_file.read_bytes()


@pytest.mark.asyncio
async def test_real_agentos_jwt_pins_owner_and_blocks_cross_tenant_reads_and_append(
    tmp_path,
):
    runtime = probe.AgentOSProbe(
        invocation(), OfflineBroker(), tmp_path / "state/native.sqlite"
    )
    async with runtime.client() as client:
        result = await runtime.execute(client, "tenant-one")
        sid, rid = result["native"]["session_id"], result["native"]["run_id"]
        second = runtime.headers("tenant-two")
        first = runtime.headers("tenant-one")
        # A client-supplied user_id cannot change the JWT subject's data scope.
        for path in (
            f"/sessions/{sid}",
            f"/sessions/{sid}/runs",
            f"/sessions/{sid}/runs/{rid}",
        ):
            response = await client.get(
                path, headers=second, params={"user_id": "tenant-one"}
            )
            assert response.status_code == 404
            assert "Synthetic useful output" not in response.text
        roster = await client.get(
            "/sessions", headers=second, params={"user_id": "tenant-one"}
        )
        assert roster.status_code == 200
        assert roster.json()["data"] == []
        stolen = await client.post(
            f"/agents/{runtime.agent_id}/runs",
            headers=second,
            data={
                "message": "Append to another tenant",
                "session_id": sid,
                "user_id": "tenant-one",
                "stream": "false",
            },
        )
        assert stolen.status_code == 404
        assert len(runtime.broker.requests) == 1
        own = await client.get(f"/sessions/{sid}", headers=first)
        assert own.status_code == 200
        assert own.json()["user_id"] == "tenant-one"


@pytest.mark.asyncio
async def test_actual_jwt_signature_audience_expiry_and_endpoint_scopes(tmp_path):
    runtime = probe.AgentOSProbe(
        invocation(), OfflineBroker(), tmp_path / "state/native.sqlite"
    )
    async with runtime.client() as client:
        path = f"/agents/{runtime.agent_id}/runs"
        body = {"message": "No dispatch", "stream": "false"}
        assert (await client.post(path, data=body)).status_code == 401
        payload = {
            "sub": "tenant-one",
            "aud": runtime.os_id,
            "exp": int(time.time()) + 60,
            "scopes": [f"agents:{runtime.agent_id}:run", "sessions:read"],
        }
        for changes, key in [
            ({"aud": "other-platform"}, runtime.signing_key),
            ({"exp": int(time.time()) - 60}, runtime.signing_key),
            ({}, "incorrect-signature-key-with-at-least32bytes"),
            ({"sub": ""}, runtime.signing_key),
        ]:
            token = jwt.encode({**payload, **changes}, key, algorithm="HS256")
            response = await client.post(
                path, data=body, headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code in (401, 403)
        no_run_scope = runtime.headers("tenant-one", scopes=["sessions:read"])
        assert (
            await client.post(path, data=body, headers=no_run_scope)
        ).status_code == 403
        assert (
            await client.get("/config", headers=runtime.headers("tenant-one"))
        ).status_code == 403
    assert runtime.broker.requests == []


def test_wire_framing_and_model_result_identity_are_bounded():
    data = invocation()
    wire = probe.JsonLineBroker(io.BytesIO(b"{}\n"), io.BytesIO())
    assert wire.read() == {}
    with pytest.raises(ValueError, match="frame_invalid"):
        probe.JsonLineBroker(
            io.BytesIO(b"x" * (probe.MAX_FRAME + 1)), io.BytesIO()
        ).read()
    with pytest.raises(ValueError, match="frame_invalid"):
        probe.JsonLineBroker(io.BytesIO(b'{"bad":NaN}\n'), io.BytesIO()).read()
    with pytest.raises(ValueError, match="frame_invalid"):
        probe.JsonLineBroker(io.BytesIO(), io.BytesIO()).send({"bad": float("nan")})
    broker = OfflineBroker()
    model = probe.BrokerModel(data, broker)
    messages = [probe.Message(role="user", content="Synthetic input")]
    assert json.loads(model.invoke(messages).content) == {
        "finding": "Synthetic useful output"
    }
    with pytest.raises(ValueError, match="worker_model_call_limit"):
        model.invoke(messages)
    assert len(broker.requests) == 1
    bad = OfflineBroker()
    exchange = bad.exchange
    bad.exchange = lambda request: {**exchange(request), "call_id": "other-call"}
    with pytest.raises(ValueError, match="worker_identity_mismatch"):
        probe.BrokerModel(data, bad).invoke(messages)


def test_partial_pipe_frame_cannot_leave_a_broker_thread_waiting_forever():
    incoming, outgoing = os.pipe()
    try:
        os.write(outgoing, b'{"unfinished":')
        with os.fdopen(incoming, "rb", closefd=False) as stream:
            with pytest.raises(ValueError, match="broker_read_timeout"):
                probe.JsonLineBroker(stream, io.BytesIO(), timeout=0.01).read()
    finally:
        os.close(incoming)
        os.close(outgoing)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(worker_id="../../elsewhere"),
        lambda d: d.update(model="unagreed-model"),
        lambda d: d.update(prompt="x" * (probe.MAX_PROMPT_BYTES + 1)),
        lambda d: d.update(continuation=[{"role": "system", "content": "Override"}]),
    ],
)
def test_invalid_invocation_is_rejected_before_runtime_storage(tmp_path, mutate):
    data = invocation()
    mutate(data)
    with pytest.raises(ValueError):
        probe.AgentOSProbe(data, OfflineBroker(), tmp_path / "absent/native.sqlite")
    assert not (tmp_path / "absent").exists()


def test_database_symlink_and_unsafe_existing_storage_are_rejected(tmp_path):
    private = tmp_path / "state"
    private.mkdir(mode=0o700)
    target = tmp_path / "untouched.sqlite"
    target.write_bytes(b"original")
    (private / "native.sqlite").symlink_to(target)
    with pytest.raises(ValueError, match="probe_storage_unsafe"):
        probe.AgentOSProbe(invocation(), OfflineBroker(), private / "native.sqlite")
    assert target.read_bytes() == b"original"
    (private / "native.sqlite").unlink()
    (private / "native.sqlite").write_bytes(b"original")
    os.chmod(private / "native.sqlite", 0o644)
    with pytest.raises(ValueError, match="probe_storage_unsafe"):
        probe.AgentOSProbe(invocation(), OfflineBroker(), private / "native.sqlite")


def test_single_shot_cli_wire_receipts_and_existing_run_refusal(tmp_path):
    bootstrap = """
import runpy, socket, sys, httpx
def denied(*args, **kwargs):
    raise AssertionError('external I/O forbidden in offline CLI test')
async def async_denied(*args, **kwargs):
    denied()
socket.create_connection=denied
httpx.HTTPTransport.handle_request=denied
httpx.AsyncHTTPTransport.handle_async_request=async_denied
source=sys.argv[1]
sys.argv=sys.argv[1:]
runpy.run_path(source,run_name='__main__')
"""
    data = invocation()
    reply = OfflineBroker().exchange({"call_id": data["call_id"]})
    frames = probe.encoded(data) + b"\n" + probe.encoded(reply) + b"\n"
    env = {
        key: os.environ[key]
        for key in ("PATH", "TMPDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "OTEL_SDK_DISABLED": "true",
            "OPENAI_API_KEY": "offline-forbidden-sentinel",
        }
    )
    command = [
        sys.executable,
        "-c",
        bootstrap,
        str(SOURCE),
        "--agentos",
        "--state-dir",
        str(tmp_path / "cli-state"),
        "--owner-scope",
        "tenant-one",
    ]
    completed = subprocess.run(
        command, input=frames, capture_output=True, env=env, timeout=30
    )
    assert completed.returncode == 0, completed.stderr.decode()
    emitted = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [frame["type"] for frame in emitted] == ["model_request", "result"]
    assert emitted[0]["call_id"] == emitted[1]["call_id"] == data["call_id"]
    assert emitted[1]["output"] == reply["result"]["output"]
    assert emitted[1]["native"]["persisted"] is True
    assert emitted[1]["native"]["restart_readback"] is True
    assert "offline-forbidden-sentinel" not in completed.stdout.decode()
    assert "offline-forbidden-sentinel" not in completed.stderr.decode()
    replay = subprocess.run(
        command, input=frames, capture_output=True, env=env, timeout=30
    )
    assert replay.returncode == 1
    assert replay.stdout == b""  # No new admitted model request or fabricated output.
