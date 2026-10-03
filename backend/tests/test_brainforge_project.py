"""One private project joins briefs and native requests without dispatching them."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.channels.brainforge_project import WORKFLOW_LANES, BrainForgeProjectCompiler


def pinned(path: Path, value: dict) -> dict:
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def project(tmp_path):
    # The fixture path resolves macOS's /var symlink before admission.
    root = tmp_path.resolve()
    control = root / "CONTROL.md"
    control.write_text("Synthetic Chief ownership rules", encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {"brief": {"type": "string"}},
        "required": ["brief"],
        "additionalProperties": False,
    }
    catalog = {"workflows": [{"id": identifier, "input_schema": schema} for identifier in WORKFLOW_LANES.values()]}
    config = {
        "control": {"path": str(control), "sha256": hashlib.sha256(control.read_bytes()).hexdigest()},
        "catalog": pinned(root / "catalog.json", catalog),
        "inputs": {},
        "research": None,
        "collector": {"total_budget_usd": 16, "ledger": None},
    }
    snapshot = {
        "clients": [{"id": "example", "status": "active"}, {"id": "other", "status": "active"}],
        "workItems": [
            {"id": "blocked", "clientId": "example", "status": "blocked", "title": "Private blocker", "owner": "Recorded owner", "nextAction": "Recorded next step"},
            {"id": "done", "clientId": "example", "status": "done"},
            {"id": "other", "clientId": "other", "status": "blocked"},
            {"id": "unresolved", "clientId": "missing", "status": "blocked"},
        ],
    }
    return root, config, snapshot


def test_project_joins_all_lanes_with_source_backed_actions_and_no_dispatch(project):
    root, config, snapshot = project
    config["inputs"]["crm"] = pinned(root / "crm.json", {"clientId": "example", "inputs": {"brief": "Synthetic reviewed CRM input"}})
    result = BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")
    assert set(result["lanes"]) == set(WORKFLOW_LANES)
    assert [row["workId"] for row in result["prioritizedActions"]] == ["blocked"]
    assert result["prioritizedActions"][0]["owner"] == "Recorded owner"
    assert result["prioritizedActions"][0]["nextAction"] == "Recorded next step"
    assert result["lanes"]["crm"]["status"] == "prepared_request"
    assert result["lanes"]["offers"]["status"] == "needs_reviewed_inputs"
    assert result["collector"]["status"] == "original_ledger_unresolved"
    assert result["networkCalls"] == 0
    assert result["canonicalWritten"] is False
    assert result["requestCount"] == 1


def test_wrong_client_packet_cannot_route_to_another_client(project):
    root, config, snapshot = project
    config["inputs"]["crm"] = pinned(root / "crm.json", {"clientId": "other", "inputs": {"brief": "Other client"}})
    result = BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")
    assert result["lanes"]["crm"]["status"] == "different_client_scope"
    assert result["requestCount"] == 0
    assert "Other client" not in json.dumps(result)


def test_unknown_and_inactive_clients_are_held(project):
    _, config, snapshot = project
    snapshot["clients"][0]["status"] = "inactive"
    result = BrainForgeProjectCompiler(config).compile(snapshot, client_id="__owner__")
    assert [row["workId"] for row in result["prioritizedActions"]] == ["other"]
    assert result["heldRoutes"] == 2


def test_source_drift_rejected_and_originals_preserved(project):
    root, config, snapshot = project
    compiler = BrainForgeProjectCompiler(config)
    (root / "CONTROL.md").write_text("Changed owner", encoding="utf-8")
    with pytest.raises(ValueError, match="source drift"):
        compiler.compile(snapshot, client_id="example")


def test_native_closed_schema_rejects_unsupported_input(project):
    root, config, snapshot = project
    config["inputs"]["crm"] = pinned(root / "crm.json", {"clientId": "example", "inputs": {"brief": "Reviewed", "invented": True}})
    with pytest.raises(ValueError, match="native input schema"):
        BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")


def test_oversize_and_symlink_packets_refused(project):
    root, config, _ = project
    target = root / "target.json"
    pin = pinned(target, {"workflows": []})
    link = root / "linked.json"
    link.symlink_to(target)
    config["catalog"] = dict(pin, path=str(link))
    with pytest.raises(ValueError, match="symlink"):
        BrainForgeProjectCompiler(config)


def test_request_digest_matches_exact_native_body_and_is_stable(project):
    root, config, snapshot = project
    config["inputs"]["reporting"] = pinned(root / "reporting.json", {"clientId": "example", "inputs": {"brief": "Synthetic measured report input"}})
    compiler = BrainForgeProjectCompiler(config)
    first = compiler.compile(snapshot, client_id="example")
    second = compiler.compile(snapshot, client_id="example")
    packet = first["lanes"]["reporting"]
    assert packet == second["lanes"]["reporting"]
    assert hashlib.sha256(packet["requestJson"].encode()).hexdigest() == packet["requestSha256"]
    assert json.loads(packet["requestJson"])["supervisor"] is True
    assert packet["sent"] is False


def test_duplicate_json_keys_rejected(project):
    root, config, _ = project
    path = root / "catalog.json"
    path.write_text('{"workflows": [], "workflows": []}', encoding="utf-8")
    config["catalog"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="duplicate JSON"):
        BrainForgeProjectCompiler(config)


def test_unrecognized_lane_cannot_reach_native_contract(project):
    root, config, _ = project
    config["inputs"]["unbounded"] = pinned(root / "unknown.json", {"clientId": "example", "inputs": {"brief": "Unknown"}})
    with pytest.raises(ValueError, match="unknown project lane"):
        BrainForgeProjectCompiler(config)


def test_schema_cannot_fetch_external_references(project):
    root, config, _ = project
    catalog = {"workflows": [{"id": "lead-quality-analysis", "input_schema": {"$ref": "https://example.com/schema"}}]}
    config["catalog"] = pinned(root / "catalog.json", catalog)
    with pytest.raises(ValueError, match="references"):
        BrainForgeProjectCompiler(config)


def test_private_credentials_are_refused_before_request_output(project):
    root, config, snapshot = project
    config["inputs"]["crm"] = pinned(root / "crm.json", {"clientId": "example", "inputs": {"brief": "api_key=synthetic-secret"}})
    with pytest.raises(ValueError, match="credential-shaped"):
        BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")


def test_tested_full_model_proof_is_bound_without_claiming_live_momo(project):
    root, config, snapshot = project
    proof = pinned(root / "synthetic-model-proof.json", {"synthetic": True, "toolLoop": "passed"})
    config["model"] = pinned(
        root / "model-route.json",
        {
            "kind": "brain_forge_model_route",
            "provider": "hai",
            "model": "glm-5.3-uncensored",
            "base_url": "https://hai-api.hcloud.ltd/v1",
            "route_status": "tested_provider_route",
            "transport": "responses",
            "tested_reasoning_effort": "low",
            "evidence_files": [proof],
            "serving_revision": None,
            "actual_cost": None,
        },
    )
    compiler = BrainForgeProjectCompiler(config)
    result = compiler.compile(snapshot, client_id="example")
    assert result["model"]["testedReasoningEffort"] == "low"
    assert result["model"]["costPerRequest"] is None
    assert result["model"]["servingRevision"] is None
    assert "live installation unverified" in result["model"]["status"]
    (root / "synthetic-model-proof.json").write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="source drift"):
        compiler.compile(snapshot, client_id="example")


def test_flash_receipt_cannot_qualify_full_model(project):
    root, config, snapshot = project
    config["model"] = pinned(
        root / "model-route.json",
        {
            "kind": "brain_forge_model_route",
            "provider": "hai",
            "model": "glm-5.3-flash-uncensored",
            "base_url": "https://hai-api.hcloud.ltd/v1",
        },
    )
    with pytest.raises(ValueError, match="reviewed full GLM"):
        BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")


def test_existing_three_field_native_api_has_no_unsupported_supervisor_field(project):
    root, config, snapshot = project
    config["native_request_supervisor"] = False
    config["inputs"]["crm"] = pinned(root / "crm.json", {"clientId": "example", "inputs": {"brief": "Synthetic reviewed input"}})
    result = BrainForgeProjectCompiler(config).compile(snapshot, client_id="example")
    packet = result["lanes"]["crm"]
    assert set(packet["request"]) == {"workflow_id", "inputs", "framework"}
    assert packet["supervisorRequested"] is False
    assert packet["sent"] is False
