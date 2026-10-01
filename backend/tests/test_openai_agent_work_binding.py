"""Synthetic operator exports only: no real clients, credentials or provider I/O."""

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.gateway import openai_agent_work_binding as work

NOW = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
OWNER = "a" * 64


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode()


@pytest.fixture
def packet(tmp_path):
    # Shape of the real canonical graph and Test-MarketingExecutionGraph output;
    # this synthetic fixture never pretends to be a real accepted client result.
    graph = {
        "schemaVersion": 1,
        "workflowId": "marketing-chief-execution-graph",
        "graphRunId": "mgr-synthetic-direct",
        "graphRevision": 2,
        "workItem": {
            "id": "wi-synthetic-1",
            "expectedVersion": 3,
            "contentSha256": "b" * 64,
            "clientId": "synthetic-client",
            "sourceLocator": "clients/synthetic-client/evidence/source.md",
            "definitionOfDone": ["Source claims retain evidence."],
            "nextAction": "Prepare a source-backed local draft.",
            "approval": {"tier": "automatic", "status": "not_required", "gate": "none"},
            "actionClass": "local_draft",
        },
        "queueSnapshot": {"locator": "queue/work-items.json", "revision": 7, "sha256": "c" * 64},
        "scope": {
            "clientRoot": "clients/synthetic-client",
            "graphLocator": "state/execution-graphs/synthetic.json",
            "privacy": "redacted",
            "canonicalWriteAllowed": False,
            "externalActionAllowed": False,
            "durableMemoryWriteAllowed": False,
        },
        "handoffContract": {
            "schema": "schemas/worker-handoff.schema.json",
            "validator": "scripts/Test-MarketingHandoff.ps1",
            "reconciler": "scripts/Accept-WorkerHandoff.ps1",
            "expectedWorkItemVersion": 3,
            "approvalGate": "none",
        },
        "blockers": [],
    }
    validation = {
        "status": "valid",
        "checkedAt": NOW.isoformat(),
        "graphRunId": "mgr-synthetic-direct",
        "graphRevision": 2,
        "workItemId": "wi-synthetic-1",
        "workItemVersion": 3,
        "contentSha256": sha(encode(graph)),
        "problems": [],
        "warnings": [],
        "canonicalWriteAttempted": False,
        "externalActionAttempted": False,
    }
    source = b"Synthetic reviewed source: service scope confirmed; no measured performance claims."
    manifest = {
        "schema_version": 1,
        "packet_type": "canonical-openai-work-packet",
        "execution_id": "direct-synthetic-1",
        "owner_scope": OWNER,
        "canonical_source_commit": "d" * 40,
        "graph_file": "graph.json",
        "graph_sha256": sha(encode(graph)),
        "graph_locator": "state/execution-graphs/synthetic.json",
        "validation_file": "validation.json",
        "validation_sha256": sha(encode(validation)),
        "source_file": "source.txt",
        "source_sha256": sha(source),
        "source_privacy": "redacted",
        "artifact_locator": "clients/synthetic-client/deliverables/draft.pdf",
        "title": "Synthetic draft",
    }
    case = {"root": tmp_path, "graph": graph, "validation": validation, "source": source, "manifest": manifest}
    write(case)
    return case


def write(case, *, update_receipt=True):
    root, graph, validation, manifest = (case[name] for name in ("root", "graph", "validation", "manifest"))
    raw_graph = encode(graph)
    if update_receipt:
        validation["contentSha256"] = sha(raw_graph)
    raw_validation = encode(validation)
    manifest.update(graph_sha256=sha(raw_graph), validation_sha256=sha(raw_validation), source_sha256=sha(case["source"]))
    for name, data in (("graph.json", raw_graph), ("validation.json", raw_validation), ("source.txt", case["source"]), ("manifest.json", encode(manifest))):
        (root / name).write_bytes(data)
    case["manifest_pin"] = sha(encode(manifest))
    case["validation_pin"] = sha(raw_validation)


def load(case, **kwargs):
    options = {"expected_validation_sha256": case["validation_pin"], "now": NOW, **kwargs}
    return work.load_pinned_work_packet(case["root"], "manifest.json", case["manifest_pin"], OWNER, **options)


def evidence(**changes):
    values = dict(
        owner_scope=OWNER,
        execution_id="direct-synthetic-1",
        session_id="local_session",
        root_turn_id="root_turn",
        artifact_id="artifact_file",
        artifact_turn_id="root_turn",
        root_status="completed",
        root_final_present=True,
        history_truncated=False,
        operation_pending=False,
    )
    return work.RootArtifactEvidence(**(values | changes))


def test_load_exact_pinned_actual_receipt_shape_and_immutable_projection(packet):
    binding = load(packet)
    prepared = work.prepare_bound_input(binding)
    assert binding.work_item_version == 3 and binding.queue_revision == 7
    assert binding.source == packet["source"] and binding.work_item_content_sha256 == "b" * 64
    assert packet["source"].decode() in prepared.text
    assert "untrusted data" in prepared.text
    assert prepared.binding_digest == work.prepare_bound_input(load(packet)).binding_digest
    assert prepared.metadata["graph_sha256"] == sha(encode(packet["graph"]))
    assert all(key not in prepared.metadata for key in ("source", "task", "title", "acceptance_criteria"))
    metadata = prepared.metadata
    metadata["client_id"] = "wrong-client"
    assert prepared.metadata["client_id"] == "synthetic-client"
    with pytest.raises(FrozenInstanceError):
        binding.client_id = "other"
    assert type(binding.acceptance_criteria) is tuple
    assert str(packet["root"]) not in prepared.metadata_json


@pytest.mark.parametrize("name", ["manifest.json", "source.txt", "graph.json", "validation.json"])
def test_exact_file_mutation_refuses_without_changing_originals(packet, name):
    path = packet["root"] / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(work.WorkBindingStop, match="digest_mismatch"):
        load(packet)


def test_validation_pin_is_independent_of_operator_manifest(packet):
    with pytest.raises(work.WorkBindingStop, match="canonical_validation_pin_mismatch"):
        load(packet, expected_validation_sha256="0" * 64)
    with pytest.raises(TypeError):
        work.load_pinned_work_packet(packet["root"], "manifest.json", packet["manifest_pin"], OWNER)
    packet["validation"]["status"] = "invented_boolean_verdict"
    write(packet)
    with pytest.raises(work.WorkBindingStop, match="invalid_canonical_validation_or_graph"):
        load(packet)


@pytest.mark.parametrize("where,key,value", [("manifest", "schema_version", True), ("manifest", "schema_version", 1.0), ("validation", "canonicalWriteAttempted", 0)])
def test_receipt_and_manifest_literal_fields_are_strict(packet, where, key, value):
    packet[where][key] = value
    write(packet)
    with pytest.raises(work.WorkBindingStop):
        load(packet)


@pytest.mark.parametrize("mutation", ["item_version", "graph_revision", "item_id", "graph_id", "content", "problem", "missing_receipt_field", "extra_receipt_field"])
def test_actual_validation_receipt_must_match_exact_graph(packet, mutation):
    if mutation == "item_version":
        packet["validation"]["workItemVersion"] += 1
    elif mutation == "graph_revision":
        packet["validation"]["graphRevision"] += 1
    elif mutation == "item_id":
        packet["validation"]["workItemId"] = "wi-other"
    elif mutation == "graph_id":
        packet["validation"]["graphRunId"] = "mgr-other"
    elif mutation == "content":
        packet["validation"]["contentSha256"] = "0" * 64
    elif mutation == "problem":
        packet["validation"]["problems"] = ["Stale work item"]
    elif mutation == "missing_receipt_field":
        del packet["validation"]["contentSha256"]
    else:
        packet["validation"]["accepted"] = True
    write(packet, update_receipt=False)
    with pytest.raises(work.WorkBindingStop):
        load(packet)


@pytest.mark.parametrize("seconds", [-1, 301])
def test_validator_freshness_at_load_and_after_load(packet, seconds):
    binding = load(packet)
    with pytest.raises(work.WorkBindingStop, match="canonical_validation_stale"):
        work.assert_binding_current(binding, OWNER, now=NOW + timedelta(seconds=seconds))
    with pytest.raises(work.WorkBindingStop, match="canonical_validation_stale"):
        load(packet, now=NOW + timedelta(seconds=seconds))
    work.assert_binding_current(binding, OWNER, now=NOW + timedelta(seconds=300))


def test_narrower_operator_validation_expiry_survives_load(packet):
    binding = load(packet, max_validation_age_seconds=30)
    work.assert_binding_current(binding, OWNER, now=NOW + timedelta(seconds=30))
    with pytest.raises(work.WorkBindingStop, match="canonical_validation_stale"):
        work.assert_binding_current(binding, OWNER, now=NOW + timedelta(seconds=31))


def test_exact_canonical_opaque_source_locator_supported(packet):
    packet["graph"]["workItem"]["sourceLocator"] = "agent-os-run:synthetic-123/task.json"
    write(packet)
    assert load(packet).source_locator == "agent-os-run:synthetic-123/task.json"


def test_owner_changes_rejected_before_any_input_or_artifact_admission(packet):
    with pytest.raises(work.WorkBindingStop, match="owner_binding_mismatch"):
        work.load_pinned_work_packet(packet["root"], "manifest.json", packet["manifest_pin"], "f" * 64, expected_validation_sha256=packet["validation_pin"], now=NOW)
    binding = load(packet)
    with pytest.raises(work.WorkBindingStop, match="owner_binding_mismatch"):
        work.assert_binding_current(binding, "f" * 64, now=NOW)
    with pytest.raises(work.WorkBindingStop, match="artifact_owner_or_execution_mismatch"):
        work.build_bound_artifact_receipt(binding, evidence(owner_scope="f" * 64), b"bytes")


@pytest.mark.parametrize("mutation", ["approval", "gate", "external", "source_client", "artifact_client", "guarded", "bool_version", "bad_hash", "blocked"])
def test_scope_and_authority_fail_closed(packet, mutation):
    graph, manifest = packet["graph"], packet["manifest"]
    if mutation == "approval":
        graph["workItem"]["approval"]["status"] = "pending"
    elif mutation == "gate":
        graph["handoffContract"]["approvalGate"] = "explicit"
    elif mutation == "external":
        graph["scope"]["externalActionAllowed"] = True
    elif mutation == "source_client":
        graph["workItem"]["sourceLocator"] = "clients/another-client/source.md"
    elif mutation == "artifact_client":
        manifest["artifact_locator"] = "clients/another-client/draft.pdf"
    elif mutation == "guarded":
        manifest["packet_type"] = "ApprovedCycle"
        manifest["cycle_id"] = "held-original"
    elif mutation == "bool_version":
        graph["workItem"]["expectedVersion"] = True
    elif mutation == "bad_hash":
        graph["workItem"]["contentSha256"] = "ad-hoc-serialized-hash"
    else:
        graph["blockers"] = ["Current source unavailable"]
    write(packet)
    with pytest.raises(work.WorkBindingStop):
        load(packet)


def test_complete_binding_digest_tracks_source_task_criteria_versions(packet):
    binding = load(packet)
    original = work.prepare_bound_input(binding).binding_digest
    mutations = [
        replace(binding, task="Different approved task"),
        replace(binding, acceptance_criteria=("Different criterion",)),
        replace(binding, work_item_version=4),
        replace(binding, work_item_content_sha256="f" * 64),
        replace(binding, title="Different title"),
        replace(binding, source=b"Other source", source_sha256=sha(b"Other source")),
        replace(binding, artifact_locator="clients/synthetic-client/other.pdf"),
    ]
    assert all(work.prepare_bound_input(changed).binding_digest != original for changed in mutations)
    with pytest.raises(work.WorkBindingStop, match="invalid_work_binding"):
        work.prepare_bound_input(replace(binding, source=b"Changed without matching hash"))


@pytest.mark.parametrize("kind", ["leaf_symlink", "parent_symlink", "fifo", "directory", "oversize", "invalid_utf8"])
def test_no_follow_bounded_regular_file_source_reads(packet, kind, tmp_path):
    path = packet["root"] / "source.txt"
    if kind == "invalid_utf8":
        packet["source"] = b"\xff\xfe"
        write(packet)
    elif kind == "oversize":
        packet["source"] = b"x" * 65537
        write(packet)
    elif kind == "parent_symlink":
        link = tmp_path / "linked-parent"
        link.symlink_to(packet["root"], target_is_directory=True)
        packet["root"] = link
    else:
        path.unlink()
        if kind == "leaf_symlink":
            outside = packet["root"] / "outside.txt"
            outside.write_bytes(packet["source"])
            path.symlink_to(outside)
        elif kind == "fifo":
            os.mkfifo(path)
        else:
            path.mkdir()
    with pytest.raises(work.WorkBindingStop):
        load(packet)


def test_read_time_mutation_detected_by_actual_no_follow_primitive(packet, monkeypatch):
    real_read = os.read
    changed = False

    def mutate(fd, amount):
        nonlocal changed
        raw = real_read(fd, amount)
        if raw == packet["source"] and not changed:
            changed = True
            (packet["root"] / "source.txt").write_bytes(b"changed" + raw)
        return raw

    monkeypatch.setattr(os, "read", mutate)
    with pytest.raises(work.WorkBindingStop, match="unsafe_or_unreadable_packet"):
        load(packet)
    assert changed


def test_framing_exact_character_limit_and_multibyte_boundary(packet):
    binding = load(packet)
    overhead = len(work.prepare_bound_input(replace(binding, source=b"x", source_sha256=sha(b"x"))).text) - 1
    raw = b"x" * (work.MAX_INPUT_CHARS - overhead)
    exact = replace(binding, source=raw, source_sha256=sha(raw))
    assert len(work.prepare_bound_input(exact).text) == work.MAX_INPUT_CHARS
    with pytest.raises(work.WorkBindingStop, match="framed_input_limit"):
        work.prepare_bound_input(replace(exact, source=raw + b"x", source_sha256=sha(raw + b"x")))
    raw_unicode = ("\U0001f642" * (work.MAX_INPUT_CHARS - overhead)).encode()
    assert len(work.prepare_bound_input(replace(binding, source=raw_unicode, source_sha256=sha(raw_unicode))).text) == work.MAX_INPUT_CHARS


@pytest.mark.parametrize("changes", [{"root_status": "in_progress"}, {"root_final_present": False}, {"history_truncated": True}, {"operation_pending": True}])
def test_nonterminal_child_only_truncated_or_missing_root_output_cannot_export(changes):
    with pytest.raises(ValidationError):
        evidence(**changes)


@pytest.mark.parametrize("changes", [{"root_final_present": 1}, {"history_truncated": 0}, {"operation_pending": 0}, {"root_status": True}])
def test_completion_evidence_is_strict_not_truthy(changes):
    with pytest.raises(ValidationError):
        evidence(**changes)


def test_module_import_is_inert_without_file_credentials_or_provider_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected import-time I/O")

    actual_getenv = os.getenv

    def safe_library_environment(name, *args):
        # Pydantic queries its own plugin setting during schema construction;
        # the work adapter must not query credential or activation variables.
        assert name == "PYDANTIC_DISABLE_PLUGINS"
        return actual_getenv(name, *args)

    spec = importlib.util.spec_from_file_location("_binding_inert_probe", work.__file__)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, spec.name, module)
        patch.setattr(os, "open", forbidden)
        patch.setattr(os, "getenv", safe_library_environment)
        spec.loader.exec_module(module)


def test_binary_receipt_has_exact_bytes_and_unproved_acceptance(packet):
    binding = load(packet)
    raw = b"\x00\xff\xfe%PDF synthetic\x00"
    receipt = work.build_bound_artifact_receipt(binding, evidence(), raw)
    assert receipt.artifact_sha256 == sha(raw) and receipt.bytes == len(raw)
    assert receipt.semantic_acceptance == "not_evaluated" and receipt.canonical_adoption == "not_performed"
    assert receipt.metadata() == work.build_bound_artifact_receipt(binding, evidence(), raw).metadata()
    assert work.build_bound_artifact_receipt(binding, evidence(), raw + b"x").artifact_sha256 != receipt.artifact_sha256
    assert json.loads(json.dumps(receipt.metadata())) == receipt.metadata()
    with pytest.raises(work.WorkBindingStop, match="artifact_root_turn_mismatch"):
        work.build_bound_artifact_receipt(binding, evidence(artifact_turn_id="child_turn"), raw)
    with pytest.raises(work.WorkBindingStop, match="artifact_owner_or_execution_mismatch"):
        work.build_bound_artifact_receipt(binding, evidence(execution_id="direct-other"), raw)
    for data in (b"", "text", bytearray(raw), b"x" * (work.MAX_ARTIFACT_BYTES + 1)):
        with pytest.raises(work.WorkBindingStop, match="artifact_size_or_type_limit"):
            work.build_bound_artifact_receipt(binding, evidence(), data)


def test_duplicate_json_missing_receipt_and_sanitized_errors(packet):
    (packet["root"] / "validation.json").unlink()
    with pytest.raises(work.WorkBindingStop) as error:
        load(packet)
    assert str(error.value) == "unsafe_or_unreadable_packet" and str(packet["root"]) not in str(error.value)
    write(packet)
    raw = b'{"schema_version":1,"schema_version":1}'
    (packet["root"] / "manifest.json").write_bytes(raw)
    packet["manifest_pin"] = sha(raw)
    with pytest.raises(work.WorkBindingStop, match="invalid_packet_json"):
        load(packet)
