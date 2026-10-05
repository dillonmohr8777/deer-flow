"""Synthetic original-owner ledgers only: no credentials or provider I/O."""

import asyncio
import fcntl
import hashlib
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_brainforge_hai_native import SyntheticResponses
from test_workflow_adapters import request
from test_workflow_native_runtime import create, drain

from app.gateway.workflow_adapters import HAI_MODEL, HAI_ROUTE, ROUTE_ENV, AdapterError, WorkflowModelAdapter
from app.gateway.workflow_hai_budget import LOCK_SECONDS, SECTION, BudgetBridgeError, OriginalOwnerJPYBridge, create_workflow_model_adapter
from app.gateway.workflow_service import WorkflowService
from deerflow.config.reload_boundary import is_startup_only_field

KEY = "hai_SYNTHETIC_ONLY_NOT_A_CREDENTIAL"
SOURCE_OWNER = "synthetic-original-owner-thread"
ACCOUNT = "a" * 64
CONTEXT = {"owner_scope": "synthetic-owner-scope", "actor": "synthetic-actor", "organization": "synthetic-org", "storage_user": "synthetic-actor", "run_id": "synthetic-run", "workflow_id": "personal-research-note"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, data):
    raw = (json.dumps(data, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha(raw)}


def synthetic_config(tmp_path, *, purpose="real_work_comparison", initial=5):
    now = datetime.now(UTC)
    cap = 300 if purpose == "real_work_comparison" else 150
    ledger = tmp_path / ("hai-real-work-reservations.jsonl" if cap == 300 else "hai-test-reservations.jsonl")
    prefix = (json.dumps({"check": "original-uncertain-hold", "reserved_jpy": initial, "cap_jpy": cap}) + "\n").encode()
    ledger.write_bytes(prefix)
    info = ledger.stat()
    cfg = {"enabled": True, "purpose": purpose, "ledger": {"path": str(ledger), "prefix_bytes": len(prefix), "prefix_sha256": sha(prefix), "device": info.st_dev, "inode": info.st_ino}}
    cfg["approved_budget"] = write_json(
        tmp_path / "approved-budget.json",
        {"source_thread": SOURCE_OWNER, "currency": "USD", "new_cash_spend_cap": 10, "qualification_reservation_cap_jpy": 150, "real_work_comparison_cap_jpy": 300, "automatic_recharge": False, "subscription": False},
    )
    cfg["pricing"] = write_json(
        tmp_path / "pricing.json",
        {
            "kind": "brain_forge_hai_price_evidence",
            "observed_at_utc": now.isoformat(),
            "provider": "hai",
            "model": HAI_MODEL,
            "currency": "JPY",
            "input_jpy_per_million_tokens": "600",
            "output_jpy_per_million_tokens": "1000",
            "billing_quantum_jpy": "0.000001",
            "credit_jpy": "1",
            "prices_tax_inclusive": True,
            "reasoning_included_in_output_tokens": True,
            "responses_input_includes_cache_tokens": True,
            "cache_discount_not_assumed_for_reservations": True,
            "provider_minimum_charge": False,
            "sources": [
                {"url": url, "status_code": 200, "required_terms_verified": True, "body_sha256": "b" * 64}
                for url in ["https://hai.hcloud.ltd/models/glm-5.3-uncensored", "https://hai.hcloud.ltd/pricing", "https://hai.hcloud.ltd/docs/billing/", "https://hai.hcloud.ltd/docs/reasoning/"]
            ],
        },
    )
    common = {"observed_at_utc": now.isoformat(), "provider": "hai", "source_owner_thread": SOURCE_OWNER, "credential_reference": "Keychain:hai.primary", "fixed_origin": "https://hai-api.hcloud.ltd"}
    cfg["read_metadata"] = write_json(tmp_path / "read.json", {"kind": "brain_forge_hai_protected_read_metadata", **common, "requests": {"me": {"status_code": 200, "owner_account_sha256": ACCOUNT}}})
    cfg["billing_readback"] = write_json(
        tmp_path / "billing.json",
        {
            "kind": "brain_forge_hai_billing_readback",
            **common,
            "requests": {"account": {"status_code": 200, "owner_account_sha256": ACCOUNT, "balance_jpy": "1000.000000"}, "billing": {"status_code": 200, "rows": 3, "pagination_limit": 200, "returned_rows_debitedJpy_sum": "20.000000"}},
        },
    )
    team_path = tmp_path / "glm_team/state/budget.jsonl"
    team_path.parent.mkdir(parents=True)
    cfg["related_owner_ledger"] = write_json(team_path, {"amount": "1", "event": "reserve", "id": "synthetic-related-hold", "route": "hai", "time": now.timestamp() - 1})
    allocation = {
        "policy": "conservative_billing_and_unsettled_holds",
        "selected_ledger_path": str(ledger),
        "purpose": purpose,
        "cap_jpy": cap,
        "amount_jpy": "21.000000",
        "billing_component_jpy": "20.000000",
        "related_unsettled_hai_component_jpy": "1",
        "billing_readback_sha256": cfg["billing_readback"]["sha256"],
        "related_owner_ledger_sha256": cfg["related_owner_ledger"]["sha256"],
        "related_owner_ledger_disposition": "overlap_unverified_all_unsettled_holds_retained",
    }
    binding = {
        "kind": "brain_forge_hai_owner_bridge_acceptance",
        "accepted": True,
        "accepted_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "source_owner_thread": SOURCE_OWNER,
        "owner_account_sha256": ACCOUNT,
        "credential_sha256": sha(KEY.encode()),
        "purpose": purpose,
        "ledger_path": str(ledger),
        "ledger_prefix_bytes": len(prefix),
        "ledger_prefix_sha256": sha(prefix),
        "cap_jpy": cap,
        "current_activity_reconciled": True,
        "activity_allocation": allocation,
        "observed_billing_total_debited_jpy": "20.000000",
        "original_request_cost_attribution": "unverified",
        "retained_original_holds": True,
        "new_cash_spend_cap_usd": 10,
        "automatic_recharge": False,
        "native_workflows_authorized": True,
        "accepted_workflow_ids": ["personal-research-note"],
        **{k: v for k, v in CONTEXT.items() if k not in {"run_id", "workflow_id"}},
    }
    for name in ("approved_budget", "pricing", "read_metadata", "billing_readback"):
        binding[f"{name}_sha256"] = cfg[name]["sha256"]
    mapping_raw = json.dumps(binding, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    cfg["source_acceptance"] = write_json(
        tmp_path / "source-acceptance.json",
        {
            "kind": "brain_forge_hai_original_owner_acceptance_proof",
            "source_thread": SOURCE_OWNER,
            "source_role": "user",
            "source_actor": CONTEXT["actor"],
            "source_message_id": "synthetic-accepted-user-record",
            "source_message_sha256": "0" * 64,
            "accepted_mapping_sha256": sha(mapping_raw),
            "verification_method": "operator_attested_original_owner_user_record",
        },
    )
    binding["source_acceptance_sha256"] = cfg["source_acceptance"]["sha256"]
    cfg["owner_binding"] = write_json(tmp_path / "binding.json", binding)
    return cfg


def bridge(cfg):
    return OriginalOwnerJPYBridge(cfg, credential_sha256=sha(KEY.encode()))


def admission(**updates):
    return {**CONTEXT, "provider": "hai", "model": HAI_MODEL, "call_id": "call-one", "effort": "low", "input_token_limit": 60000, "max_output_tokens": 2048, "request_sha256": "c" * 64, "serialized_payload_bytes": 1000, **updates}


def rows(cfg):
    return [json.loads(row, parse_float=Decimal) for row in Path(cfg["ledger"]["path"]).read_text().splitlines()]


def edit_receipt(cfg, name, updates):
    path = Path(cfg[name]["path"])
    data = json.loads(path.read_text())
    data.update(updates)
    cfg[name] = write_json(path, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose,cap", [("qualification", 150), ("real_work_comparison", 300)])
async def test_same_original_ledger_numeric_holds_usage_audit_and_replay_fence(tmp_path, purpose, cap):
    cfg = synthetic_config(tmp_path, purpose=purpose)
    original = Path(cfg["ledger"]["path"]).read_bytes()
    guard = bridge(cfg)
    value = admission()
    assert await guard(value) is True
    proof = {"model": HAI_MODEL, "response_id": "synthetic-response", "input_tokens": 12, "output_tokens": 8, "output_sha256": "d" * 64}
    await guard.record_usage(value, proof)
    ledger = rows(cfg)
    assert len(ledger) == 4 and Path(cfg["ledger"]["path"]).read_bytes().startswith(original)
    assert ledger[2]["reserved_jpy"] == Decimal("13.478400") and ledger[2]["cap_jpy"] == cap
    assert ledger[3]["reserved_jpy"] == 0 and ledger[3]["brainforge_native"]["actual_billed_cost_jpy"] is None
    assert ledger[3]["brainforge_native"]["reservation_released"] is False
    plain = [json.loads(line) for line in Path(cfg["ledger"]["path"]).read_text().splitlines()]
    assert sum(float(item["reserved_jpy"]) for item in plain) == pytest.approx(39.4784)
    assert all(float(item["cap_jpy"]) == cap for item in plain)
    for operation in (guard(value), guard.record_usage(value, proof)):
        with pytest.raises(BudgetBridgeError):
            await operation
    assert len(rows(cfg)) == 4


@pytest.mark.asyncio
async def test_original_helper_later_append_and_concurrent_restart_share_cap(tmp_path):
    cfg = synthetic_config(tmp_path, initial=260)
    results = await asyncio.gather(bridge(cfg)(admission()), bridge(cfg)(admission(call_id="call-two", run_id="another-run")), return_exceptions=True)
    assert sum(value is True for value in results) == sum(isinstance(value, BudgetBridgeError) for value in results) == 1
    with pytest.raises(BudgetBridgeError):
        await bridge(cfg)(admission(call_id="call-three", run_id="restart-run"))
    assert len(rows(cfg)) == 3
    with Path(cfg["ledger"]["path"]).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps({"check": "original-compatible-later", "reserved_jpy": 1, "cap_jpy": 300}) + "\n")
    with pytest.raises(BudgetBridgeError):
        await bridge(cfg)(admission(call_id="call-four"))
    assert len(rows(cfg)) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"actor": "foreign"},
        {"organization": None},
        {"storage_user": "foreign"},
        {"owner_scope": "foreign"},
        {"workflow_id": "unapproved-profile"},
        {"effort": "medium"},
        {"model": "gpt-6.1-sol"},
        {"provider": "openai"},
        {"serialized_payload_bytes": True},
        {"max_output_tokens": 2049},
        {"api_key": "hai_SYNTHETIC_SECRET"},
    ],
)
async def test_scope_model_profile_and_unknown_fields_fail_closed(tmp_path, updates):
    cfg = synthetic_config(tmp_path)
    with pytest.raises(BudgetBridgeError, match="^provider_allowance_unverified$"):
        await bridge(cfg)(admission(**updates))
    assert len(rows(cfg)) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"accepted": False},
        {"current_activity_reconciled": False},
        {"retained_original_holds": False},
        {"native_workflows_authorized": False},
        {"observed_billing_total_debited_jpy": "0.000000"},
        {"owner_account_sha256": "e" * 64},
        {"credential_sha256": "f" * 64},
        {"new_cash_spend_cap_usd": 11},
        {"cap_jpy": 301},
        {"original_request_cost_attribution": "assumed_paid"},
        {"expires_at_utc": "2020-01-01T00:00:00Z"},
        {"unknown": "hai_SYNTHETIC_SECRET"},
    ],
)
def test_missing_acceptance_reconciliation_cap_and_credential_binding_denied(tmp_path, updates):
    cfg = synthetic_config(tmp_path)
    edit_receipt(cfg, "owner_binding", updates)
    with pytest.raises(BudgetBridgeError, match="^provider_allowance_unverified$"):
        bridge(cfg)
    assert len(rows(cfg)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        '{"check":"later","reserved_jpy":NaN,"cap_jpy":300}',
        '{"check":"later","reserved_jpy":-1,"cap_jpy":300}',
        '{"check":"later","reserved_jpy":1,"cap_jpy":301}',
        '{"check":"original-uncertain-hold","reserved_jpy":1,"cap_jpy":300}',
        '{"check":"later","reserved_jpy":1,"reserved_jpy":2,"cap_jpy":300}',
        '{"check":"later","reserved_jpy":"hai_SYNTHETIC_SECRET","cap_jpy":300}',
    ],
)
async def test_corrupt_suffix_cannot_reserve(tmp_path, line):
    cfg = synthetic_config(tmp_path)
    path = Path(cfg["ledger"]["path"])
    with path.open("a") as handle:
        handle.write(line + "\n")
    before = path.read_bytes()
    with pytest.raises(BudgetBridgeError):
        await bridge(cfg)(admission())
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["truncate", "rewrite", "replace"])
async def test_immutable_prefix_and_file_identity_detect_replacement(tmp_path, mode):
    cfg = synthetic_config(tmp_path)
    guard, path = bridge(cfg), Path(cfg["ledger"]["path"])
    old = path.read_bytes()
    if mode == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(old)
        os.replace(replacement, path)
    else:
        path.write_bytes(old[:-1] if mode == "truncate" else old.replace(b"5", b"4", 1))
    before = path.read_bytes()
    with pytest.raises(BudgetBridgeError):
        await guard(admission())
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_cancellation_lock_deadline_drain_worker_before_return(tmp_path, monkeypatch):
    cfg = synthetic_config(tmp_path)
    guard, entered = bridge(cfg), threading.Event()
    original = guard._append

    def announce(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(guard, "_append", announce)
    with Path(cfg["ledger"]["path"]).open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        task = asyncio.create_task(guard(admission()))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        with pytest.raises(BudgetBridgeError):
            await asyncio.wait_for(guard(admission(call_id="deadline-call")), LOCK_SECONDS + 1)
        fcntl.flock(handle, fcntl.LOCK_UN)
    await asyncio.sleep(0.05)
    assert len(rows(cfg)) == 1


def test_absent_disabled_unknown_startup_configuration_preserves_default(monkeypatch):
    monkeypatch.delenv(ROUTE_ENV, raising=False)
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    for extras in ({}, {SECTION: {"enabled": False}}):
        assert create_workflow_model_adapter(SimpleNamespace(model_extra=extras)).provider == "openai"
    with pytest.raises(BudgetBridgeError):
        create_workflow_model_adapter(SimpleNamespace(model_extra={SECTION: {"enabled": False, "base_url": "https://unapproved"}}))
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    held = create_workflow_model_adapter(SimpleNamespace(model_extra={SECTION: {"enabled": False}}))
    assert held.provider_admission is None and held.capabilities()["langgraph"]["available"] is False
    assert is_startup_only_field(SECTION)


@pytest.mark.asyncio
async def test_mock_native_maker_checker_startup_bridge_same_ledger_no_refunds(tmp_path, monkeypatch):
    cfg = synthetic_config(tmp_path)
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    adapter = create_workflow_model_adapter(SimpleNamespace(model_extra={SECTION: cfg}))
    adapter.client = client = SyntheticResponses()
    service = WorkflowService(tmp_path / "native.sqlite", checkpointer=InMemorySaver(), adapter=adapter)
    await service.start()
    try:
        admitted = await create(service)
        await drain(service)
        result = await service.snapshot(CONTEXT["owner_scope"], admitted["id"])
        assert result["status"] == "completed" and result["accepted"] is True and len(client.calls) == 3
        ledger = rows(cfg)
        assert len(ledger) == 8 and sum(row["reserved_jpy"] for row in ledger) > 5
        assert len([row for row in ledger if row.get("brainforge_native", {}).get("event") == "accepted_usage_audit"]) == 3
        assert result["usage"]["cost"] is None
        before = Path(cfg["ledger"]["path"]).read_bytes()
        assert (await create(service))["id"] == admitted["id"]
        await drain(service)
        assert Path(cfg["ledger"]["path"]).read_bytes() == before
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_transport_ambiguity_keeps_jpy_hold_and_sanitizes_errors(tmp_path, monkeypatch):
    cfg = synthetic_config(tmp_path)
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    client = SyntheticResponses(error=RuntimeError("hai_SYNTHETIC_SECRET"))
    adapter = WorkflowModelAdapter(client=client, provider_admission=bridge(cfg))
    with pytest.raises(AdapterError, match="^provider_request_failed$"):
        await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
    assert len(rows(cfg)) == 3 and len(client.calls) == 1 and rows(cfg)[1]["reserved_jpy"] > 0


@pytest.mark.parametrize("role", ["assistant", "tool"])
def test_source_provenance_cannot_be_an_assistant_or_tool_acceptance(tmp_path, role):
    cfg = synthetic_config(tmp_path)
    edit_receipt(cfg, "source_acceptance", {"source_role": role})
    with pytest.raises(BudgetBridgeError):
        bridge(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["reserved_jpy", "cap_jpy"])
async def test_legacy_numeric_fields_cannot_be_json_strings(tmp_path, field):
    cfg = synthetic_config(tmp_path)
    row = {"check": "string-compatibility-conflict", "reserved_jpy": 1, "cap_jpy": 300}
    row[field] = str(row[field])
    with Path(cfg["ledger"]["path"]).open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    with pytest.raises(BudgetBridgeError):
        await bridge(cfg)(admission())
    assert len(rows(cfg)) == 2


def test_owner_acceptance_cannot_predate_billing_or_price_evidence(tmp_path):
    cfg = synthetic_config(tmp_path)
    edit_receipt(cfg, "owner_binding", {"accepted_at_utc": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})
    with pytest.raises(BudgetBridgeError):
        bridge(cfg)


@pytest.mark.asyncio
async def test_accepted_usage_audit_failure_preserves_hold_and_known_tokens(tmp_path, monkeypatch):
    cfg = synthetic_config(tmp_path)
    guard = bridge(cfg)
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    monkeypatch.setattr(guard, "record_usage", lambda *_: (_ for _ in ()).throw(RuntimeError("hai_SYNTHETIC_SECRET")))
    adapter = WorkflowModelAdapter(client=SyntheticResponses(), provider_admission=guard)
    with pytest.raises(AdapterError, match="^provider_reconciliation_unverified$") as caught:
        await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
    assert caught.value.usage == {"input_tokens": 12, "output_tokens": 8, "cost": None}
    assert len(rows(cfg)) == 3


@pytest.mark.asyncio
async def test_actual_sdk3_wire_hash_and_payload_bytes_include_unicode(monkeypatch):
    import httpx
    from openai import AsyncOpenAI

    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    admitted = []

    async def guard(value):
        admitted.append(value)
        return True

    async def transport(sent):
        assert sent.url.host == "hai-api.hcloud.ltd" and sent.url.path == "/v1/responses"
        assert admitted[0]["request_sha256"] == sha(sent.content)
        assert admitted[0]["serialized_payload_bytes"] == len(sent.content)
        assert "Café 日本語" in sent.content.decode()
        return httpx.Response(
            200,
            json={
                "id": "synthetic-wire",
                "object": "response",
                "created_at": 1,
                "model": HAI_MODEL,
                "status": "completed",
                "output": [{"id": "synthetic-message", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": '{"answer":"Café"}', "annotations": []}]}],
                "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            },
        )

    client = AsyncOpenAI(api_key=KEY, base_url="https://hai-api.hcloud.ltd/v1", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport), follow_redirects=False, trust_env=False))
    adapter = WorkflowModelAdapter(client=client, provider_admission=guard)
    try:
        result = await adapter.call(**request(model=HAI_MODEL, prompt="Café 日本語"), provider_admission_context=CONTEXT)
        assert result["output"] == {"answer": "Café"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_native_key_is_pinned_in_memory_against_later_env_rotation(tmp_path, monkeypatch):
    cfg = synthetic_config(tmp_path)
    monkeypatch.setenv(ROUTE_ENV, HAI_ROUTE)
    monkeypatch.setenv("HAI_API_KEY", KEY)
    adapter = create_workflow_model_adapter(SimpleNamespace(model_extra={SECTION: cfg}))
    monkeypatch.setenv("HAI_API_KEY", "hai_OTHER_SYNTHETIC_KEY")
    adapter.client = SyntheticResponses()
    result = await adapter.call(**request(model=HAI_MODEL), provider_admission_context=CONTEXT)
    assert result["model"] == HAI_MODEL and adapter._hai_api_key == KEY
    assert len(rows(cfg)) == 4


@pytest.mark.parametrize("mode", ["settle_without_reserve", "duplicate_reserve", "duplicate_settle", "route_mismatch", "settle_above_reserve", "stop"])
def test_related_owner_protocol_conflicts_fail_closed(tmp_path, mode):
    cfg = synthetic_config(tmp_path)
    path = Path(cfg["related_owner_ledger"]["path"])
    initial = json.loads(path.read_text())
    if mode == "stop":
        path.parent.joinpath("STOP").write_text("synthetic operator hold")
    else:
        later = dict(initial, event="settle")
        if mode == "settle_without_reserve":
            later["id"] = "unknown-id"
        elif mode == "duplicate_reserve":
            later["event"] = "reserve"
        elif mode == "route_mismatch":
            later["route"] = "spark"
        elif mode == "settle_above_reserve":
            later["amount"] = "2"
        suffix = json.dumps(later) + "\n"
        if mode == "duplicate_settle":
            suffix += suffix
        with path.open("a") as handle:
            handle.write(suffix)
        cfg["related_owner_ledger"]["sha256"] = sha(path.read_bytes())
    with pytest.raises(BudgetBridgeError):
        bridge(cfg)
    assert len(rows(cfg)) == 1
