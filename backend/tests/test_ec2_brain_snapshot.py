"""Offline protocol and no-rebuild contract for the optional EC2 Brain snapshot."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ADAPTER = Path(__file__).parents[2] / "deploy/momentum/ec2/brain_readonly_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("brain_readonly_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def snapshot(tmp_path):
    tools = ["brain_now", "brain_client", "brain_open_items", "brain_systems", "brain_search", "brain_capture", "brain_refresh"]
    (tmp_path / "brain.py").write_text(
        "import json\n"
        f"TOOLS = {[{'name': name, 'inputSchema': {'type': 'object'}} for name in tools]!r}\n"
        "def forbidden(*args, **kwargs): raise AssertionError('no collector or upstream')\n"
        "load = build = capture = search = call_tool = forbidden\n"
        "def find_client(data, name): return [data['clients'][name]]\n"
        "def render_card(client): return client['name']\n"
        "def open_text(data, client): return data['open_items'][0]\n"
        "def systems_text(data): return json.dumps(data['systems'])\n",
        encoding="utf-8",
    )
    (tmp_path / "brain.json").write_text(
        json.dumps({"generated_at": "2020-01-01T00:00:00Z", "clients": {"sample": {"name": "Synthetic Client"}}, "open_items": ["Synthetic open item"], "loop_cards": [], "systems": {"sample": "saved"}}), encoding="utf-8"
    )
    (tmp_path / "NOW.md").write_text("Synthetic saved digest", encoding="utf-8")
    for path in tmp_path.iterdir():
        os.utime(path, (1, 1))
        path.chmod(0o444)
    return tmp_path


def test_snapshot_protocol_without_network_or_rebuild(snapshot, monkeypatch):
    module = load_adapter()
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: pytest.fail("snapshot must not build an HTTP client"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()}
    adapter = module.Adapter(module.SnapshotRequester(snapshot), allowed_tools=module.SNAPSHOT_TOOLS, instructions=module.SNAPSHOT_INSTRUCTIONS)
    requests = [{"method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, {"method": "tools/list"}]
    requests += [{"method": "tools/call", "params": {"name": name, "arguments": {"name": "sample"}}} for name in module.SNAPSHOT_TOOLS]
    requests += [{"method": "tools/call", "params": {"name": name}} for name in ["brain_search", "brain_capture", "brain_refresh"]]
    messages = [{"jsonrpc": "2.0", "id": i, **r} for i, r in enumerate(requests)]
    data = "".join(json.dumps(m) + "\n" for m in messages).encode()
    output = io.StringIO()
    module.serve(adapter, io.BytesIO(data), output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["id"] for row in rows] == list(range(len(messages)))
    assert "not live" in rows[0]["result"]["instructions"]
    assert {tool["name"] for tool in rows[1]["result"]["tools"]} == set(module.SNAPSHOT_TOOLS)
    for row in rows[2:6]:
        assert row["result"]["_meta"]["sourceObservedAt"] == "2020-01-01T00:00:00Z"
        assert row["result"]["content"][0]["text"].startswith("Saved snapshot sourceObservedAt=")
    assert "Synthetic Client" in rows[3]["result"]["content"][0]["text"]
    assert all(row["error"]["code"] == -32601 for row in rows[6:])
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()} == before
    # Main must select snapshot mode before reading any HTTP credentials.
    result = subprocess.run(
        [sys.executable, str(ADAPTER)], input=data, capture_output=True, env={**os.environ, "BRAIN_SNAPSHOT_DIR": str(snapshot), "BRAIN_MCP_UPSTREAM_URL": "invalid", "BRAIN_MCP_AUTHORIZATION": "secret-must-not-appear"}, timeout=10
    )
    assert result.returncode == 0
    assert "secret-must-not-appear" not in (result.stdout + result.stderr).decode()
    assert len(result.stdout.splitlines()) == len(messages)


@pytest.mark.parametrize("contents", ["{}", '{"generated_at":"undated"}', '{"generated_at":"2020-01-01"}', '{"generated_at":"2020-01-01T00:00:00Z"}', "not JSON"])
def test_bad_snapshot_fails_closed(snapshot, contents):
    path = snapshot / "brain.json"
    path.chmod(0o644)
    path.write_text(contents, encoding="utf-8")
    result = subprocess.run([sys.executable, str(ADAPTER)], input=b"", capture_output=True, env={**os.environ, "BRAIN_SNAPSHOT_DIR": str(snapshot)}, timeout=10)
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"Brain read-only adapter stopped.\n"


def test_existing_http_allowlist_remains_fixed():
    module = load_adapter()
    forwarded = []

    def requester(message):
        forwarded.append(message)
        return {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in module.ALLOWED_TOOLS]}}

    adapter = module.Adapter(requester)
    result = adapter.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert {tool["name"] for tool in result["result"]["tools"]} == set(module.ALLOWED_TOOLS)
    assert "brain_search" in module.ALLOWED_TOOLS
    denied = adapter.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "brain_refresh"}})
    assert denied["error"]["code"] == -32601
    assert len(forwarded) == 1
    with pytest.raises(module.ConfigurationError):
        module.HTTPRequester("https://untrusted.invalid", "Bearer never-log")
