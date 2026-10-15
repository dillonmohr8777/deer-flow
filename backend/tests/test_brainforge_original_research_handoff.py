"""Actual original producer on synthetic pages; no collector/state/provider calls.

Optional BRAINFORGE_ORIGINAL_X_SOURCE selects the reviewed generic source root.
The real brief cycle also uses the established BRAINFORGE_BRIEF_SOURCE setting.
No private source, financial state or client evidence is committed here.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.channels.brainforge_cli import verify
from app.channels.brainforge_project import BrainForgeProjectCompiler
from app.channels.brainforge_workflow import BRIEF_MODULES, BrainForgeBriefWorkflow
from deerflow.workflows.catalog import list_workflows


def pin(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path: Path, value: dict) -> dict:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return pin(path)


@pytest.fixture
def original(tmp_path, monkeypatch):
    setting = os.environ.get("BRAINFORGE_ORIGINAL_X_SOURCE", "")
    source = Path(setting) / "_os/automation"
    if not setting or not (source / "lib/marketing_signal_brief.py").is_file():
        pytest.skip("set BRAINFORGE_ORIGINAL_X_SOURCE to the reviewed original generic source")
    root = tmp_path.resolve()
    programs = root / "programs"
    programs.mkdir()
    for name in ("marketing_signal_brief.py", "x_post_pilot.py"):
        shutil.copyfile(source / "lib" / name, programs / name)
    shutil.copyfile(source / "profiles/twitter-pilot16.json", root / "profile.json")
    modules = {}
    for name in ("x_post_pilot", "marketing_signal_brief"):
        spec = importlib.util.spec_from_file_location(name, programs / (name + ".py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    # Loading functions is permitted; financial-state constructors/reads are not.
    for method in ("__init__", "status", "run_page", "_connect"):
        monkeypatch.setattr(modules["x_post_pilot"].Pilot, method, Mock(side_effect=AssertionError("collector state invoked")))
    monkeypatch.setattr(modules["x_post_pilot"].sqlite3, "connect", Mock(side_effect=AssertionError("financial database opened")))
    page = {
        "pilot_id": "twitter-pilot-16-20261002",
        "request_id": "a" * 32,
        "config_sha256": hashlib.sha256(b"synthetic query and window").hexdigest(),
        "observed_at": "2026-10-01T00:00:00Z",
        "returned_count": 2,
        "posts": [
            {
                "id": "123",
                "author_id": None,
                "created_at": None,
                "text": "Measured agent workflow for CRM lead conversion and content. " + "Complete evidence. " * 40 + "完整_END_SENTINEL",
                "url": "https://x.com/i/web/status/123",
                "sourceObservedAt": "2026-10-01T00:00:00Z",
                "untrusted": True,
            },
            {"id": "456", "author_id": "42", "created_at": "2026-09-30T00:00:00Z", "text": "Today I ate an apple.", "url": "https://x.com/i/web/status/456", "sourceObservedAt": "2026-10-01T00:00:00Z", "untrusted": True},
        ],
        "next_token": None,
    }
    save(root / "page.json", page)
    control = root / "CONTROL.md"
    control.write_text("Synthetic Chief owns this fixture queue.", encoding="utf-8")
    config = {"control": pin(control), "catalog": save(root / "catalog.json", {"workflows": [row.model_dump() for row in list_workflows()]}), "inputs": {}, "collector": {"total_budget_usd": 16, "ledger": None}}
    state = SimpleNamespace(root=root, page=page, config=config, snapshot={"clients": [{"id": "synthetic", "status": "active"}], "workItems": []}, producer=modules["marketing_signal_brief"])

    def produce():
        pages = [pin(root / "page.json")]
        proof = state.producer.build_brief(pages, output_root=root / "proposal", observed_at="2026-10-02T00:00:00Z")
        config["research"] = {
            "kind": "original_x_pilot",
            "producer_sources": {name: pin(programs / name) for name in ("marketing_signal_brief.py", "x_post_pilot.py")},
            "profile": pin(root / "profile.json"),
            "proof": save(root / "proof.json", proof),
            "pages": pages,
            "review": {},
        }
        state.review = {
            "kind": "brain_forge_original_pilot_review",
            "pilot_id": "twitter-pilot-16-20261002",
            "accepted_for": "owner_research_proposal",
            "proof_sha256": config["research"]["proof"]["sha256"],
            "profile_sha256": config["research"]["profile"]["sha256"],
            "producer_sha256": {name: item["sha256"] for name, item in config["research"]["producer_sources"].items()},
            "page_sha256": [item["sha256"] for item in pages],
            "reviewed_by": "synthetic-independent-reviewer",
            "reviewed_at": "2026-10-03T00:00:00Z",
            "evidence_mode": "fixture",
            "selected_post_ids": ["123"] if proof["counts"]["relevantCandidates"] else [],
            "research_question": "Which synthetic evidence supports a proposed owner experiment, and what remains unverified?",
        }
        state.proof = proof
        state.bind_review()

    def bind_review():
        config["research"]["review"] = save(root / "review.json", state.review)

    def rebind_outputs():
        for path_key, hash_key in (("briefPath", "briefSha256"), ("envelopePath", "envelopeSha256")):
            state.proof[hash_key] = pin(Path(state.proof[path_key]))["sha256"]
        config["research"]["proof"] = save(root / "proof.json", state.proof)
        state.review["proof_sha256"] = config["research"]["proof"]["sha256"]
        bind_review()

    state.bind_review, state.produce, state.rebind_outputs = bind_review, produce, rebind_outputs
    produce()
    return state


def compile_owner(state):
    return BrainForgeProjectCompiler(state.config).compile(state.snapshot, client_id="__owner__")


def test_actual_original_producer_whole_sources_and_stable_native_request(original, monkeypatch):
    import app.channels.brainforge_project as project

    monkeypatch.setattr(project.subprocess, "run", Mock(side_effect=AssertionError("research compiler executed a subprocess")))
    before = {path: path.read_bytes() for path in original.root.rglob("*") if path.is_file()}
    first, second = compile_owner(original), compile_owner(original)
    assert first == second
    packet = first["lanes"]["research"]
    assert packet["request"]["workflow_id"] == "personal-research-note"
    assert packet["request"]["framework"] == "langgraph" and packet["request"]["supervisor"] is True
    assert set(packet["request"]["inputs"]) == {"brief", "research_question", "source_excerpts", "knowledge_context"}
    sources = json.loads(packet["request"]["inputs"]["source_excerpts"])["sources"]
    assert sources == [original.page["posts"][0]]
    assert "完整_END_SENTINEL" in sources[0]["text"] and len(sources[0]["text"]) > 600
    origin = packet["researchOrigin"]
    assert origin["selectedPostIds"] == ["123"] and origin["omittedPostIds"] == ["456"]
    assert origin["evidenceMode"] == "fixture" and origin["providerBillingUsd"] is None
    assert origin["financialStateVerified"] is False
    assert origin["sourceCommit"] == "5003cdaa1ef0171a2148592f15ff4d784c94c3d8"
    assert len(origin["sourcePins"]) == 8
    assert hashlib.sha256(packet["requestJson"].encode()).hexdigest() == packet["requestSha256"]
    assert first["networkCalls"] == 0 and first["canonicalWritten"] is False and packet["sent"] is False
    assert all(path.read_bytes() == value for path, value in before.items())
    assert set(before) == {path for path in original.root.rglob("*") if path.is_file()}


def test_actual_private_brief_project_save_and_readback(original):
    setting = os.environ.get("BRAINFORGE_BRIEF_SOURCE", "")
    if not setting or not all((Path(setting) / name).is_file() for name in BRIEF_MODULES):
        pytest.skip("set BRAINFORGE_BRIEF_SOURCE for the protected brief cycle")
    root = original.root
    source, canonical = root / "brief-source", root / "canonical"
    source.mkdir()
    for name in BRIEF_MODULES:
        shutil.copyfile(Path(setting) / name, source / name)
    (canonical / "registry").mkdir(parents=True)
    (canonical / "queue").mkdir()
    save(canonical / "registry/clients.json", {"clients": [{"id": "synthetic", "status": "active"}]})
    save(canonical / "queue/work-items.json", {"revision": 7, "updatedAt": "2026-10-02T00:00:00Z", "workItems": [{"id": "one", "clientId": "synthetic", "status": "blocked", "title": "PRIVATE_CANONICAL_SENTINEL"}]})
    (canonical / "CONTROL.md").write_text("Synthetic sole writer fixture.", encoding="utf-8")
    original.config["control"] = pin(canonical / "CONTROL.md")
    config = {
        "brief_source": str(source),
        "canonical_root": str(canonical),
        "artifact_root": str(root / "private-brief-output"),
        "brief_source_hashes": {name: pin(source / name)["sha256"] for name in BRIEF_MODULES},
        "source_hashes": {name: pin(canonical / name)["sha256"] for name in ("registry/clients.json", "queue/work-items.json")},
        "project": original.config,
    }
    before = {path: path.read_bytes() for path in canonical.rglob("*") if path.is_file()}
    result = BrainForgeBriefWorkflow(config).run(job_key="original synthetic cycle", client_id="__owner__", thread_sha256=hashlib.sha256(b"synthetic thread").hexdigest())
    receipt = json.loads(Path(result.receipt_path).read_bytes())
    project = json.loads(Path(receipt["project"]["path"]).read_bytes())
    assert project["lanes"]["research"]["researchOrigin"]["pilotId"] == "twitter-pilot-16-20261002"
    assert "PRIVATE_CANONICAL_SENTINEL" not in json.dumps(project["lanes"]["research"])
    assert result.counts["projectRequestsPrepared"] == 1 and "完整_END_SENTINEL" not in result.text
    saved = verify(result.receipt_path, result.receipt_sha256, config)
    assert saved["projectVerified"] and not saved["runtimeExecuted"] and not saved["slackDeliveryVerified"]
    assert all(path.read_bytes() == value for path, value in before.items())
    for path in (root / "private-brief-output").rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    Path(original.config["research"]["review"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="source drift"):
        verify(result.receipt_path, result.receipt_sha256, config)


@pytest.mark.parametrize("target", ["page", "profile", "proof", "review", "marketing_signal_brief.py", "x_post_pilot.py", "brief", "envelope"])
def test_source_or_output_drift_cannot_be_consumed(original, target):
    compiler = BrainForgeProjectCompiler(original.config)
    if target == "page":
        path = Path(original.config["research"]["pages"][0]["path"])
    elif target in {"brief", "envelope"}:
        path = Path(original.proof[target + "Path"])
    elif target.endswith(".py"):
        path = Path(original.config["research"]["producer_sources"][target]["path"])
    else:
        path = Path(original.config["research"][target]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source drift"):
        compiler.compile(original.snapshot, client_id="__owner__")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(accepted_for="publish"),
        lambda r: r.update(evidence_mode="authenticated_api"),
        lambda r: r.update(selected_post_ids=["999"]),
        lambda r: r.update(selected_post_ids=["123", "123"]),
        lambda r: r.update(proof_sha256="0" * 64),
        lambda r: r.update(profile_sha256="0" * 64),
        lambda r: r.update(reviewed_at="2026-09-01T00:00:00Z"),
        lambda r: r.update(reviewed_by=""),
        lambda r: r.update(accepted=True),
        lambda r: r.update(evidence_mode=[]),
    ],
)
def test_review_cannot_invent_authority_sources_or_time(original, mutate):
    mutate(original.review)
    original.bind_review()
    with pytest.raises(ValueError, match="original research"):
        compile_owner(original)


@pytest.mark.parametrize("secret", ['{"api_key":"synthetic-private-value"}', "hai_" + "s" * 24, "xpl_" + "s" * 24, "Bearer synthetic-private-value", "ghp_" + "s" * 24])
def test_credential_shaped_review_is_held_without_echo(original, secret):
    original.review["research_question"] = secret
    original.bind_review()
    with pytest.raises(ValueError, match="credential-shaped") as exc:
        compile_owner(original)
    assert secret not in str(exc.value)


def test_empty_original_findings_and_nonowner_routes_prepare_nothing(original):
    original.page["posts"][0]["text"] = "An ordinary apple."
    save(original.root / "page.json", original.page)
    original.produce()
    project = compile_owner(original)
    assert project["lanes"]["research"]["reason"] == "empty_original_evidence" and project["requestCount"] == 0
    project = BrainForgeProjectCompiler(original.config).compile(original.snapshot, client_id="synthetic")
    assert project["lanes"]["research"] == {"status": "different_client_scope"}
    assert "source_excerpts" not in json.dumps(project)


def test_original_mode_rejects_override_and_mixed_program_contracts(original):
    original.config["inputs"]["research"] = {"path": "unused", "sha256": "0" * 64}
    with pytest.raises(ValueError, match="overridden"):
        BrainForgeProjectCompiler(original.config)
    original.config["inputs"].clear()
    original.config["research"]["source_files"] = []
    with pytest.raises(ValueError, match="closed shape"):
        compile_owner(original)


@pytest.mark.parametrize("name", ["marketing_signal_brief.py", "x_post_pilot.py", "profile"])
def test_rebound_program_or_profile_cannot_impersonate_original_source(original, name):
    if name == "profile":
        path = Path(original.config["research"]["profile"]["path"])
        path.write_bytes(path.read_bytes() + b" ")
        original.config["research"]["profile"] = pin(path)
        original.review["profile_sha256"] = pin(path)["sha256"]
    else:
        path = Path(original.config["research"]["producer_sources"][name]["path"])
        path.write_bytes(path.read_bytes() + b" ")
        original.config["research"]["producer_sources"][name] = pin(path)
        original.review["producer_sha256"][name] = pin(path)["sha256"]
    original.bind_review()
    with pytest.raises(ValueError, match="exact PR447"):
        compile_owner(original)


def test_override_added_after_construction_still_fails(original):
    compiler = BrainForgeProjectCompiler(original.config)
    original.config["inputs"]["research"] = {"path": "unused", "sha256": "0" * 64}
    with pytest.raises(ValueError, match="overridden"):
        compiler.compile(original.snapshot, client_id="__owner__")


def test_drift_after_request_projection_prevents_publish(original, monkeypatch):
    compiler = BrainForgeProjectCompiler(original.config)
    request = compiler._request

    def mutate_after_request(*args):
        result = request(*args)
        path = original.root / "page.json"
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(compiler, "_request", mutate_after_request)
    with pytest.raises(ValueError, match="source drift"):
        compiler.compile(original.snapshot, client_id="__owner__")


def test_whole_oversized_source_is_held_instead_of_truncated(original):
    original.page["posts"][0]["text"] = "Agent workflow " * 500
    save(original.root / "page.json", original.page)
    original.produce()
    with pytest.raises(ValueError, match="without truncation"):
        compile_owner(original)


def test_finding_or_envelope_cannot_promote_unverified_claim(original):
    path = Path(original.proof["briefPath"])
    brief = json.loads(path.read_bytes())
    brief["findings"][0]["claimStatus"] = "verified and approved"
    save(path, brief)
    original.rebind_outputs()
    with pytest.raises(ValueError, match="remain unverified"):
        compile_owner(original)


def test_envelope_cannot_create_experiment_authority(original):
    path = Path(original.proof["envelopePath"])
    envelope = json.loads(path.read_bytes())
    envelope["candidates"] = [{"decision": "sandbox-test"}]
    save(path, envelope)
    original.rebind_outputs()
    with pytest.raises(ValueError, match="envelope mismatch"):
        compile_owner(original)


def test_duplicate_json_and_nonfinite_values_fail_closed(original):
    for payload in ('{"kind":1,"kind":2}', '{"value":NaN}'):
        path = original.root / "review.json"
        path.write_text(payload, encoding="utf-8")
        original.config["research"]["review"] = pin(path)
        with pytest.raises(ValueError, match="duplicate JSON|nonfinite JSON"):
            compile_owner(original)


def test_symlink_input_is_held(original):
    target = original.root / "review.json"
    linked = original.root / "linked-review.json"
    linked.symlink_to(target)
    original.config["research"]["review"] = dict(pin(target), path=str(linked))
    with pytest.raises(ValueError, match="symlink"):
        compile_owner(original)


def test_unknown_modes_are_rejected_without_original_source(tmp_path):
    root = tmp_path.resolve()
    control = root / "CONTROL.md"
    control.write_text("Synthetic owner.", encoding="utf-8")
    for kind in ("network", {}, False):
        config = {"control": pin(control), "catalog": {}, "inputs": {}, "research": {"kind": kind}, "collector": {"total_budget_usd": 16}}
        with pytest.raises(ValueError, match="unknown research mode"):
            BrainForgeProjectCompiler(copy.deepcopy(config))


def test_legacy_js_default_and_explicit_mode_keep_the_same_request(tmp_path, monkeypatch):
    import app.channels.brainforge_project as project

    root = tmp_path.resolve()
    control = root / "CONTROL.md"
    control.write_text("Synthetic sole writer.", encoding="utf-8")
    programs = root / "legacy-programs"
    programs.mkdir()
    entrypoint = programs / "entrypoint.js"
    entrypoint.write_text("// Synthetic program fixture; subprocess is mocked.\n", encoding="utf-8")
    native_inputs = {"brief": "Synthetic legacy brief", "research_question": "Synthetic question", "source_excerpts": "Synthetic complete source", "knowledge_context": "Synthetic untrusted source"}
    prepared = {"request": {"workflow_id": "personal-research-note", "inputs": native_inputs}, "context": {"sent": False}, "origin": {"synthetic": True}}
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(prepared)))
    monkeypatch.setattr(project.subprocess, "run", runner)
    research = {
        "source_root": str(programs),
        "source_files": [pin(entrypoint)],
        "reviewed_evidence": save(root / "legacy-evidence.json", {"synthetic": True}),
        "entrypoint": str(entrypoint),
        "node_binary": sys.executable,
    }
    config = {"control": pin(control), "catalog": save(root / "catalog.json", {"workflows": [row.model_dump() for row in list_workflows()]}), "inputs": {}, "collector": {"total_budget_usd": 16}, "research": research}
    snapshot = {"clients": [], "workItems": []}
    default = BrainForgeProjectCompiler(config).compile(snapshot, client_id="__owner__")
    config["research"]["kind"] = "reviewed_js"
    explicit = BrainForgeProjectCompiler(config).compile(snapshot, client_id="__owner__")
    assert default == explicit and default["requestCount"] == 1
    assert default["lanes"]["research"]["request"]["inputs"] == native_inputs
    assert runner.call_count == 2
    args, kwargs = runner.call_args
    assert args[0] == [sys.executable, str(entrypoint), "--reviewed-evidence", str(root / "legacy-evidence.json"), "--no-network"]
    assert kwargs == {"capture_output": True, "timeout": 30, "check": False, "env": {"PATH": os.defpath, "LANG": "C.UTF-8"}}
