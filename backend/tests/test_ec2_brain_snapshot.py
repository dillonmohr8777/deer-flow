"""Offline protocol and no-rebuild contract for the optional EC2 Brain snapshot."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ADAPTER = Path(__file__).parents[2] / "deploy/momentum/ec2/brain_readonly_adapter.py"
PUBLISHER = ADAPTER.with_name("publish_brain_snapshot.py")


def load_adapter():
    spec = importlib.util.spec_from_file_location("brain_readonly_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def snapshot(tmp_path):
    tmp_path = tmp_path.resolve()
    tools = ["brain_now", "brain_client", "brain_open_items", "brain_systems", "brain_search", "brain_capture", "brain_refresh"]
    (tmp_path / "brain.py").write_text(
        "import json\n"
        f"TOOLS = {[{'name': name, 'inputSchema': {'type': 'object'}} for name in tools]!r}\n"
        "def forbidden(*args, **kwargs): raise AssertionError('no collector or upstream')\n"
        "load = build = capture = search = call_tool = forbidden\n"
        "def find_client(data, name): return [data['clients'][name]]\n"
        "def render_card(client): return client['name']\n"
        "def open_text(data, client): return data['open_items'][0]\n"
        "def systems_text(data): return json.dumps(data['systems'])\n"
        "def render_now(data): return data['digest']\n",
        encoding="utf-8",
    )
    (tmp_path / "brain.json").write_text(
        json.dumps({"generated_at": "2020-01-01T00:00:00Z", "clients": {"sample": {"name": "Synthetic Client"}}, "open_items": ["Synthetic open item"], "loop_cards": [], "systems": {"sample": "saved"}, "digest": "Synthetic saved digest"}),
        encoding="utf-8",
    )
    (tmp_path / "NOW.md").write_text("Synthetic saved digest", encoding="utf-8")
    for path in tmp_path.iterdir():
        os.utime(path, (1, 1))
        path.chmod(0o444)
    return tmp_path


@pytest.fixture
def publication(snapshot, tmp_path_factory, monkeypatch):
    module = load_adapter()
    monkeypatch.setitem(sys.modules, "brain_readonly_adapter", module)
    spec = importlib.util.spec_from_file_location("publish_brain_snapshot", PUBLISHER)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    root = tmp_path_factory.mktemp("published").resolve()
    shutil.copyfile(snapshot / "brain.py", root / "brain.py")
    renderer_hash = hashlib.sha256((root / "brain.py").read_bytes()).hexdigest()
    # Windows cannot fsync directory handles; POSIX runs exercise that boundary.
    if os.name == "nt":
        monkeypatch.setattr(publisher, "_fsync_directory", lambda path: None)
    return module, publisher, root, renderer_hash


def revise(snapshot, *, observed="2020-01-02T00:00:00Z", label="B"):
    path = snapshot / "brain.json"
    path.chmod(0o600)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(generated_at=observed, clients={"sample": {"name": f"Synthetic Client {label}"}}, open_items=[f"Synthetic item {label}"], systems={"sample": label}, digest=f"Synthetic digest {label}")
    path.write_text(json.dumps(data), encoding="utf-8")
    now = snapshot / "NOW.md"
    now.chmod(0o600)
    now.write_text(data["digest"], encoding="utf-8")


def call(adapter, name="brain_now"):
    return adapter.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {"name": "sample"}}})


def snapshot_adapter(module, requester):
    return module.Adapter(requester, allowed_tools=module.SNAPSHOT_TOOLS, instructions=module.SNAPSHOT_INSTRUCTIONS)


def assert_unavailable(adapter):
    assert call(adapter) == {"jsonrpc": "2.0", "id": 7, "error": {"code": -32603, "message": "Brain upstream unavailable."}}
    listed = adapter.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert listed["error"] == {"code": -32603, "message": "Brain upstream unavailable."}


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
    assert result.stderr.decode().replace("\r\n", "\n") == "Brain read-only adapter stopped.\n"


def test_running_requester_adopts_complete_generations(snapshot, publication, monkeypatch):
    module, publisher, root, renderer_hash = publication
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: pytest.fail("snapshot must stay offline"))
    before_root = root.stat().st_ino
    first = publisher.publish(snapshot, root, renderer_hash)
    requester = module.SnapshotRequester(root)
    adapter = snapshot_adapter(module, requester)
    assert call(adapter)["result"]["_meta"] == {"sourceObservedAt": "2020-01-01T00:00:00Z", "generation": first["generation"]}
    pointer = (root / "current.json").read_bytes()
    assert publisher.publish(snapshot, root, renderer_hash)["changed"] is False
    assert (root / "current.json").read_bytes() == pointer
    revise(snapshot)
    second = publisher.publish(snapshot, root, renderer_hash)
    assert first["generation"] != second["generation"]
    for name in module.SNAPSHOT_TOOLS:
        result = call(adapter, name)["result"]
        assert result["_meta"] == {"sourceObservedAt": "2020-01-02T00:00:00Z", "generation": second["generation"]}
        assert "B" in result["content"][0]["text"]
    listed = adapter.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})["result"]["tools"]
    assert all(tool["_meta"]["generation"] == second["generation"] for tool in listed)
    assert root.stat().st_ino == before_root
    assert (root / "generations" / first["generation"]).is_dir()
    # Explicitly selecting a retained, fully validated generation supports rollback.
    (root / "current.json").write_bytes(pointer)
    assert call(adapter)["result"]["_meta"]["generation"] == first["generation"]


@pytest.mark.parametrize("failure", ["payload", "before_replace", "directory_fsync"])
def test_failed_publication_preserves_previous_pointer(snapshot, publication, monkeypatch, failure):
    module, publisher, root, renderer_hash = publication
    first = publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    pointer = (root / "current.json").read_bytes()
    revise(snapshot)

    def fail(*args, **kwargs):
        assert call(adapter)["result"]["_meta"]["generation"] == first["generation"]
        raise OSError("synthetic failure with private-sentinel")

    if failure == "payload":
        monkeypatch.setattr(publisher, "_write_private", fail)
    elif failure == "before_replace":
        monkeypatch.setattr(publisher.os, "replace", fail)
    else:
        monkeypatch.setattr(publisher, "_fsync_directory", fail)
    with pytest.raises(OSError):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() == pointer
    assert call(adapter)["result"]["_meta"]["generation"] == first["generation"]
    assert not (root / ".publish.lock").exists()


def test_mixed_pair_rejected_even_with_matching_mtimes(snapshot, publication):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    pointer = (root / "current.json").read_bytes()
    revise(snapshot)
    (snapshot / "NOW.md").write_text("Synthetic saved digest", encoding="utf-8")
    for name in ("brain.json", "NOW.md"):
        os.utime(snapshot / name, (1, 1))
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() == pointer


@pytest.mark.parametrize("token", ["1e400", "-1e400", "NaN", "Infinity", "-Infinity"])
def test_non_finite_source_cannot_replace_current_generation(snapshot, publication, token):
    module, publisher, root, renderer_hash = publication
    first = publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    pointer = (root / "current.json").read_bytes()
    revise(snapshot)
    path = snapshot / "brain.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["systems"]["sample"] = "SYNTHETIC_NUMBER_TOKEN"
    path.write_text(json.dumps(data).replace('"SYNTHETIC_NUMBER_TOKEN"', token), encoding="utf-8")
    with pytest.raises((module.ConfigurationError, ValueError)):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() == pointer
    assert call(adapter)["result"]["_meta"]["generation"] == first["generation"]
    with pytest.raises((module.ConfigurationError, ValueError)):
        module.SnapshotRequester(snapshot)


def test_finite_exponent_source_still_publishes_and_reads(snapshot, publication):
    module, publisher, root, renderer_hash = publication
    path = snapshot / "brain.json"
    path.chmod(0o600)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["systems"]["sample"] = "SYNTHETIC_NUMBER_TOKEN"
    path.write_text(json.dumps(data).replace('"SYNTHETIC_NUMBER_TOKEN"', "1.25e200"), encoding="utf-8")
    published = publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    result = call(adapter, "brain_systems")["result"]
    assert result["_meta"]["generation"] == published["generation"]
    assert "1.25e+200" in result["content"][0]["text"]


@pytest.mark.parametrize("contents", [b"not JSON", b"{}", b'{"schemaVersion":1,"generation":"../outside"}', b'{"schemaVersion":1,"generation":"' + b"f" * 64 + b'"}', b"x" * 4097])
def test_changed_pointer_fails_closed(snapshot, publication, contents):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    (root / "current.json").write_bytes(contents)
    assert_unavailable(adapter)
    (root / "current.json").unlink()
    assert_unavailable(adapter)


@pytest.mark.parametrize("damage", ["json_hash", "now_hash", "manifest", "renderer", "timestamp", "semantic_pair", "oversized"])
def test_selected_damaged_generation_fails_closed(snapshot, publication, damage):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    revise(snapshot)
    second = publisher.publish(snapshot, root, renderer_hash)
    directory = root / "generations" / second["generation"]
    manifest_path = directory / "manifest.json"
    if damage == "oversized":
        (directory / "brain.json").write_bytes(b"x" * (module.MAX_RESPONSE_BYTES + 1))
    elif damage in ("json_hash", "now_hash"):
        path = directory / ("brain.json" if damage == "json_hash" else "NOW.md")
        path.write_text("private-sentinel", encoding="utf-8")
    elif damage == "manifest":
        manifest_path.write_text("{}", encoding="utf-8")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if damage == "renderer":
            manifest["rendererSha256"] = "0" * 64
        elif damage == "timestamp":
            manifest["sourceObservedAt"] = "undated"
        else:
            (directory / "NOW.md").write_text("private-sentinel", encoding="utf-8")
            manifest["files"]["NOW.md"] = hashlib.sha256((directory / "NOW.md").read_bytes()).hexdigest()
        # A self-consistent manifest/id must still pass timestamp, renderer and pair checks.
        metadata = {key: value for key, value in manifest.items() if key != "generation"}
        new_id = module.generation_id(metadata)
        manifest["generation"] = new_id
        manifest_path.write_bytes(module.snapshot_json(manifest))
        directory.rename(directory.with_name(new_id))
        (root / "current.json").write_bytes(module.snapshot_json({"schemaVersion": 1, "generation": new_id}))
    assert_unavailable(adapter)


@pytest.mark.parametrize("filename", ["brain.json", "NOW.md", "manifest.json"])
@pytest.mark.parametrize("damage", ["corrupt", "delete"])
def test_unchanged_pointer_detects_damage_after_successful_read(snapshot, publication, filename, damage):
    module, publisher, root, renderer_hash = publication
    first = publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    assert call(adapter)["result"]["_meta"]["generation"] == first["generation"]
    pointer = (root / "current.json").read_bytes()
    path = root / "generations" / first["generation"] / filename
    if damage == "delete":
        path.unlink()
    else:
        path.write_bytes(b"private-sentinel")
    assert (root / "current.json").read_bytes() == pointer
    assert_unavailable(adapter)


def test_pointer_change_during_validation_fails_closed(snapshot, publication, monkeypatch):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    revise(snapshot)
    publisher.publish(snapshot, root, renderer_hash)
    load = module.load_generation

    def change(*args, **kwargs):
        state = load(*args, **kwargs)
        (root / "current.json").write_text("{}", encoding="utf-8")
        return state

    monkeypatch.setattr(module, "load_generation", change)
    assert_unavailable(adapter)


def test_legacy_is_frozen_coherent_and_migrates_without_restart(snapshot, monkeypatch):
    module = load_adapter()
    requester = module.SnapshotRequester(snapshot)
    adapter = snapshot_adapter(module, requester)
    assert call(adapter)["result"]["_meta"]["generation"] == "legacy"
    revise(snapshot)
    assert call(adapter)["result"]["_meta"]["sourceObservedAt"] == "2020-01-01T00:00:00Z"
    monkeypatch.setitem(sys.modules, "brain_readonly_adapter", module)
    spec = importlib.util.spec_from_file_location("publish_brain_snapshot", PUBLISHER)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    if os.name == "nt":
        monkeypatch.setattr(publisher, "_fsync_directory", lambda path: None)
    published = publisher.publish(snapshot, snapshot, hashlib.sha256((snapshot / "brain.py").read_bytes()).hexdigest())
    assert call(adapter)["result"]["_meta"]["generation"] == published["generation"]
    (snapshot / "current.json").unlink()
    assert_unavailable(adapter)


@pytest.mark.parametrize("name", ["brain.json", "NOW.md", "brain.py", "current.json", "generations", "generation"])
def test_symlink_bounds(snapshot, publication, tmp_path_factory, name):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    adapter = snapshot_adapter(module, module.SnapshotRequester(root))
    outside = tmp_path_factory.mktemp("outside").resolve()
    if name in ("brain.json", "NOW.md", "generation"):
        revise(snapshot)
        generation = publisher.publish(snapshot, root, renderer_hash)["generation"]
        path = root / "generations" / generation
        if name != "generation":
            path = path / name
    else:
        path = root / name
    moved = outside / name
    path.rename(moved)
    try:
        path.symlink_to(moved, target_is_directory=moved.is_dir())
    except OSError:
        if os.name != "nt":
            raise
        pytest.skip("symlink creation unavailable on this Windows host")
    assert_unavailable(adapter)


def test_publisher_bounds_conflicts_and_regression(snapshot, publication):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    pointer = (root / "current.json").read_bytes()
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, "0" * 64)
    revise(snapshot, observed="2019-01-01T00:00:00Z")
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    (root / ".publish.lock").write_text("synthetic owner", encoding="utf-8")
    with pytest.raises(FileExistsError):
        publisher.publish(snapshot, root, renderer_hash)
    (root / ".publish.lock").unlink()
    (snapshot / "brain.json").write_bytes(b"x" * (module.MAX_RESPONSE_BYTES + 1))
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() == pointer


@pytest.mark.parametrize("observed", ["undated", "2020-01-01T00:00:00", "2020-01-01", None])
def test_complete_source_with_invalid_timestamp_is_rejected(snapshot, publication, observed):
    module, publisher, root, renderer_hash = publication
    revise(snapshot, observed=observed)
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    assert not (root / "current.json").exists()


def test_legacy_mixed_pair_rejected(snapshot):
    module = load_adapter()
    (snapshot / "NOW.md").chmod(0o600)
    (snapshot / "NOW.md").write_text("private-sentinel", encoding="utf-8")
    with pytest.raises(module.ConfigurationError):
        module.SnapshotRequester(snapshot)


def test_publisher_never_executes_source_directory_code(snapshot, publication):
    _, publisher, root, renderer_hash = publication
    (snapshot / "brain.py").chmod(0o600)
    (snapshot / "brain.py").write_text("raise AssertionError('source code must not execute')", encoding="utf-8")
    assert publisher.publish(snapshot, root, renderer_hash)["changed"] is True


def test_hardlinked_source_is_rejected(snapshot, publication, tmp_path_factory):
    module, publisher, root, renderer_hash = publication
    outside = tmp_path_factory.mktemp("hardlink").resolve() / "brain.json"
    os.link(snapshot / "brain.json", outside)
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    assert not (root / "current.json").exists()


def test_publisher_detects_out_of_band_pointer_change(snapshot, publication, monkeypatch):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    revise(snapshot)
    write = publisher._write_private

    def conflict(path, raw):
        write(path, raw)
        if path.name.startswith(".current-"):
            (root / "current.json").write_bytes(b"{}")

    monkeypatch.setattr(publisher, "_write_private", conflict)
    with pytest.raises(module.ConfigurationError):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() == b"{}"


def test_failure_after_commit_does_not_claim_previous_pointer_preserved(snapshot, publication, monkeypatch):
    module, publisher, root, renderer_hash = publication
    publisher.publish(snapshot, root, renderer_hash)
    pointer = (root / "current.json").read_bytes()
    revise(snapshot)
    fsync = publisher._fsync_directory

    def fail_after_commit(path):
        if path == root and (root / "current.json").read_bytes() != pointer:
            raise OSError("synthetic post-commit failure")
        fsync(path)

    monkeypatch.setattr(publisher, "_fsync_directory", fail_after_commit)
    with pytest.raises(OSError):
        publisher.publish(snapshot, root, renderer_hash)
    assert (root / "current.json").read_bytes() != pointer
    assert call(snapshot_adapter(module, module.SnapshotRequester(root)))["result"]["_meta"]["sourceObservedAt"] == "2020-01-02T00:00:00Z"


def test_publisher_cli_failure_is_generic(snapshot, publication):
    _, _, root, _ = publication
    result = subprocess.run([sys.executable, str(PUBLISHER), "--source-dir", str(snapshot), "--snapshot-dir", str(root), "--renderer-sha256", "private-sentinel"], capture_output=True, timeout=10)
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr.decode().replace("\r\n", "\n") == "Brain snapshot publication failed.\n"


@pytest.mark.skipif(os.name != "posix", reason="native directory fsync and POSIX modes require POSIX")
def test_native_publisher_cli_is_metadata_only_and_private(snapshot, publication):
    module, _, root, renderer_hash = publication
    result = subprocess.run([sys.executable, str(PUBLISHER), "--source-dir", str(snapshot), "--snapshot-dir", str(root), "--renderer-sha256", renderer_hash], capture_output=True, timeout=10)
    assert result.returncode == 0
    assert result.stderr == b""
    receipt = json.loads(result.stdout)
    assert set(receipt) == {"generation", "sourceObservedAt", "changed"}
    assert receipt["sourceObservedAt"] == "2020-01-01T00:00:00Z"
    assert receipt["changed"] is True
    generation = root / "generations" / receipt["generation"]
    assert stat.S_IMODE(generation.stat().st_mode) == 0o700
    for path in (root / "current.json", generation / "manifest.json", *(generation / name for name in module.SNAPSHOT_FILES)):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


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
