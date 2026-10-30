"""Contract checks for the source-only MomoBot Max role bundle set."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = REPO_ROOT / "fleet" / "role-bundles"
EXPECTED_IDENTITIES = {
    "dillon-mohr": "Dillon Mohr",
    "agency-principal": "Agency Principal",
    "sales-lead": "Sales Lead",
    "operations-lead": "Operations Lead",
    "northwind-ops-pair": "Northwind Housing workflow for Jordan Ellis + Avery Brooks",
}
EXPECTED_ROLE_IDS = set(EXPECTED_IDENTITIES)
EXPECTED_SCENARIOS = {
    "dillon-mohr": {
        "strategy_research",
        "code_artifact",
        "source_injection",
        "cross_client_isolation",
    },
    "agency-principal": {
        "agency_health",
        "commercial_opportunity",
        "approval_bypass",
        "cross_client_isolation",
    },
    "sales-lead": {
        "pipeline_qualification",
        "portal_mismatch",
        "identity_disambiguation",
        "meeting_proposal_handoff",
    },
    "operations-lead": {
        "account_health",
        "capacity_training",
        "report_approval_bypass",
        "cross_client_isolation",
    },
    "northwind-ops-pair": {
        "duplicate_review",
        "availability_unknown",
        "tour_human_confirmation",
        "stop_and_status_separation",
        "tenant_isolation",
    },
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_bundle() -> tuple[dict, dict]:
    manifest = _read_json(BUNDLE_DIR / "manifest.v1.json")
    cases = _read_json(BUNDLE_DIR / manifest["acceptance_cases"]["path"])
    return manifest, cases


def test_manifest_has_five_distinct_scoped_role_profiles_with_integrity():
    manifest, _ = _load_bundle()
    roles = manifest["roles"]
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "source_only"
    assert {role["role_id"] for role in roles} == EXPECTED_ROLE_IDS
    assert {role["role_id"]: role["identity"] for role in roles} == EXPECTED_IDENTITIES

    for role in roles:
        profile_ref = role["profile"]
        profile_path = (BUNDLE_DIR / profile_ref["path"]).resolve()
        assert profile_path.is_relative_to(BUNDLE_DIR.resolve())
        content = profile_path.read_bytes()
        assert len(content) == profile_ref["bytes"]
        assert hashlib.sha256(content).hexdigest() == profile_ref["sha256"]
        assert profile_ref["bytes"] <= manifest["profile_surface"]["prompt_limit_bytes"]

        for source in role["source_refs"]:
            assert source["line_start"] > 0
            assert source["line_end"] >= source["line_start"]
            assert source["path"] and source["purpose"]

    for source in manifest["repository_sources"]:
        assert (REPO_ROOT / source["path"]).is_file()
        assert source["symbols"]

    cases_ref = manifest["acceptance_cases"]
    cases_path = (BUNDLE_DIR / cases_ref["path"]).resolve()
    assert cases_path.is_relative_to(BUNDLE_DIR.resolve())
    case_bytes = cases_path.read_bytes()
    assert len(case_bytes) == cases_ref["bytes"]
    assert hashlib.sha256(case_bytes).hexdigest() == cases_ref["sha256"]


def test_profiles_fit_actual_user_profile_models_and_prompt_limit():
    from app.gateway.routers.agents import (
        AgentResponse,
        UserProfileResponse,
        UserProfileUpdateRequest,
        router,
    )
    from deerflow.agents.lead_agent.prompt import _USER_PROFILE_MAX_BYTES

    manifest, _ = _load_bundle()
    surface = manifest["profile_surface"]
    assert surface["prompt_limit_bytes"] == _USER_PROFILE_MAX_BYTES
    assert surface["request_model"] == "UserProfileUpdateRequest"
    assert surface["response_model"] == "UserProfileResponse"

    registered_routes = {(route.path, method) for route in router.routes for method in getattr(route, "methods", set())}
    assert (surface["get_path"], "GET") in registered_routes
    assert (surface["put_path"], "PUT") in registered_routes

    agent_ref = manifest["agent_reference"]
    validated_agent_shape = AgentResponse.model_validate({"name": agent_ref["name"], "builtin": agent_ref["expected_builtin"]})
    assert validated_agent_shape.name == "momobot-max"
    assert validated_agent_shape.builtin is True

    for role in manifest["roles"]:
        content = (BUNDLE_DIR / role["profile"]["path"]).read_text(encoding="utf-8")
        assert len(content.encode("utf-8")) <= _USER_PROFILE_MAX_BYTES
        update = UserProfileUpdateRequest.model_validate({"content": content})
        response = UserProfileResponse.model_validate({"content": update.content})
        assert response.content == content


def test_acceptance_cases_are_synthetic_typed_contracts_with_required_scope_coverage():
    manifest, cases_document = _load_bundle()
    assert cases_document["schema_version"] == 1
    assert cases_document["bundle_set"] == manifest["bundle_set"]
    assert cases_document["synthetic_only"] is True
    cases = cases_document["cases"]
    assert len(cases) == manifest["acceptance_cases"]["case_count"]
    assert len({case["case_id"] for case in cases}) == len(cases)

    counts: Counter[str] = Counter()
    scenario_types: dict[str, set[str]] = {role_id: set() for role_id in EXPECTED_ROLE_IDS}
    all_tags: set[str] = set()
    for case in cases:
        assert set(case) == {"case_id", "role_id", "scenario_type", "tags", "context", "expected_contract"}
        role_id = case["role_id"]
        assert role_id in EXPECTED_ROLE_IDS
        counts[role_id] += 1
        scenario_types[role_id].add(case["scenario_type"])
        all_tags.update(case["tags"])

        context = case["context"]
        sources = context["sources"]
        source_ids = {source["id"] for source in sources}
        assert sources
        assert all(source_id.startswith("SYN-") for source_id in source_ids)
        for source in sources:
            date.fromisoformat(source["as_of"])
            assert isinstance(source["record"], dict)

        expected = case["expected_contract"]
        assert expected["outcome"]
        assert isinstance(expected["facts"], dict)
        assert expected["assertions"]
        assert expected["prohibited_actions"]
        assert set(expected["evidence_sources"]) <= source_ids

    assert set(counts) == EXPECTED_ROLE_IDS
    assert all(count >= 3 for count in counts.values())
    for role_id, required_scenarios in EXPECTED_SCENARIOS.items():
        assert required_scenarios <= scenario_types[role_id]
    assert {"cross_client", "different_person", "source_injection", "approval_bypass"} <= all_tags


def test_bundle_is_context_only_and_requires_storage_isolation_gates():
    manifest, _ = _load_bundle()
    boundary = manifest["authority_boundary"]
    assert boundary == {
        "context_only": True,
        "changes_permissions": False,
        "changes_model_or_usage_entitlement": False,
        "creates_schedule_or_sender": False,
        "authorizes_self_granted_access": False,
        "external_actions_require_existing_permissions_and_action_specific_approval": True,
        "runtime_writes_or_deployment_performed": False,
    }

    for role in manifest["roles"]:
        policy = role["workspace_policy"]
        assert policy["require_source_path_readback"] is True
        if role["role_id"] == "northwind-ops-pair":
            assert policy["stop_if_legacy_shared_fallback_or_tenant_identity_is_uncertain"] is True
            assert policy["kind"] == "verified_authorized_tenant"
            assert policy["never_use_global_user_profile_or_dillon_private_workspace"] is True
            assert policy["require_effective_tenant_only_storage_principal"] is True
        else:
            assert policy["stop_if_legacy_shared_fallback_or_workspace_identity_is_uncertain"] is True
            assert policy["kind"] == "verified_private_user"
            assert policy["require_effective_private_storage_principal"] is True
