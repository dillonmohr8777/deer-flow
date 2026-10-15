"""Paid-route admission gate: every rule is fail-closed. No network, no provider SDK."""

import json
import threading

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from deerflow.models import paid_admission as pa
from deerflow.models.paid_admission import AdmissionDenied, AdmissionGate, AdmissionHandler

PRICING = {"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0, "input_cache_hit_per_million": 0.5}
NOW = 1_790_000_000  # fixed clock inside one UTC month


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.delenv("MOMO_ADMISSION_KILL", raising=False)
    (tmp_path / "holds.json").write_text('{"holds":[]}')
    return AdmissionGate(tmp_path, clock=lambda: NOW)


def audit(gate):
    return [json.loads(x) for x in gate.audit.read_text().splitlines()]


def denied(gate, route, amount=1_000, key="k"):
    with pytest.raises(AdmissionDenied) as e:
        gate.reserve(route, amount, key)
    return e.value.reason


def test_unknown_route_denied_and_audited(gate):
    assert denied(gate, "mystery") == "unknown_route"
    assert denied(gate, None) == "unknown_route"
    assert [r["reason"] for r in audit(gate) if r["ev"] == "deny"] == ["unknown_route"] * 2


def test_unresolved_hold_blocks_paid_not_local(gate):
    gate.holds.write_text('{"holds":[{"id":"native-0.264","amount_usd":"0.264","resolved":false}]}')
    assert denied(gate, "openrouter") == "unresolved_hold"
    assert gate.reserve("local", 0, "l") is None
    gate.holds.write_text('{"holds":[{"id":"native-0.264","resolved":true}]}')
    assert gate.reserve("openrouter", 1_000, "k")


@pytest.mark.parametrize("content", [None, "not json", '{"holds":"x"}', '{"nope":1}', '{"holds":[1]}'])
def test_holds_file_missing_or_corrupt_denies(gate, content):
    gate.holds.unlink()
    if content is not None:
        gate.holds.write_text(content)
    assert denied(gate, "openrouter") == "holds_unreadable"


def test_x_route_frozen_even_with_registry_override(gate):
    (gate.dir / "registry.json").write_text('{"subcaps":{"x":5000000}}')
    assert denied(gate, "x") == "route_frozen"


def test_kill_switch_file_and_env(gate, monkeypatch):
    gate.kill_file.touch()
    assert denied(gate, "openrouter") == "kill_switch"
    assert gate.reserve("local", 0, "l") is None
    gate.kill_file.unlink()
    monkeypatch.setenv("MOMO_ADMISSION_KILL", "1")
    assert denied(gate, "jevbox_llm") == "kill_switch"


def test_local_route_free_and_audited(gate):
    assert gate.reserve("local", 0, "a") is None
    assert audit(gate)[-1]["ev"] == "local"
    assert gate.status()["used_micro"] == 0


def test_subcap_and_ceiling_are_not_additive(gate):
    gate.reserve("openrouter", 10_000_000, "a")
    assert denied(gate, "openrouter", 1, "b") == "route_subcap"
    gate.reserve("jevbox_llm", 10_000_000, "c")
    assert denied(gate, "brain_forge", 1, "d") == "monthly_ceiling"  # subcap has room, shared ceiling does not
    assert gate.status()["used_micro"] == pa.CEILING_MICRO


def test_registry_can_lower_but_not_add_routes(gate):
    (gate.dir / "registry.json").write_text('{"subcaps":{"reddit":100,"bogus":5}}')
    gate.reserve("reddit", 100, "a")
    assert denied(gate, "reddit", 1, "b") == "route_subcap"
    assert denied(gate, "bogus") == "unknown_route"
    (gate.dir / "registry.json").write_text("garbage")
    assert denied(gate, "reddit", 1, "c") == "registry_unreadable"


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "5"])
def test_invalid_amount_denied(gate, amount):
    assert denied(gate, "openrouter", amount) == "request_invalid"


def test_reservation_before_call_and_settle_from_actual(gate):
    rid = gate.reserve("openrouter", 5_000, "k")
    assert gate.status()["used_micro"] == 5_000  # held before any call completes
    assert gate.settle(rid, 1_200) is True
    assert gate.status()["by_route"]["openrouter"] == 1_200  # hold released down to actual


def test_settle_idempotent(gate):
    rid = gate.reserve("openrouter", 5_000, "k")
    assert gate.settle(rid, 700) is True
    assert gate.settle(rid, 700) is False
    assert gate.settle(rid, 9_999) is False  # replay can never change recorded spend
    assert gate.status()["used_micro"] == 700
    assert [r["ev"] for r in audit(gate)].count("settle") == 1
    with pytest.raises(AdmissionDenied):
        gate.settle("nope", 1)


def test_unknown_outcome_keeps_full_hold_and_blocks_late_settle(gate):
    rid = gate.reserve("openrouter", 5_000, "k")
    gate.mark_unknown(rid)
    assert gate.status()["used_micro"] == 5_000
    with pytest.raises(AdmissionDenied):
        gate.settle(rid, 1)


def test_duplicate_key_denied(gate):
    gate.reserve("openrouter", 10, "same")
    assert denied(gate, "openrouter", 10, "same") == "duplicate_key"


def test_overrun_is_recorded_not_hidden(gate):
    rid = gate.reserve("reddit", 100, "k")
    gate.settle(rid, 150)
    assert gate.status()["by_route"]["reddit"] == 150


def test_month_rollover_drops_settled_keeps_holds(tmp_path):
    (tmp_path / "holds.json").write_text('{"holds":[]}')
    now = [NOW]
    g = AdmissionGate(tmp_path, clock=lambda: now[0])
    g.settle(g.reserve("openrouter", 100, "a"), 100)
    g.mark_unknown(g.reserve("openrouter", 50, "b"))
    now[0] += 40 * 86400
    assert g.status()["used_micro"] == 50  # settled spend is monthly; unresolved holds persist


def test_corrupt_ledger_denies(gate):
    gate.reserve("openrouter", 10, "a")
    with open(gate.audit, "a") as f:
        f.write("{not json\n")
    assert denied(gate, "openrouter", 10, "b") == "ledger_corrupt"


def test_audit_failure_denies(gate, monkeypatch):
    def boom(*a, **k):
        raise OSError

    monkeypatch.setattr(pa.os, "fsync", boom)
    assert denied(gate, "openrouter") == "audit_write_failed"


def test_concurrent_reservations_never_exceed_cap(tmp_path):
    (tmp_path / "holds.json").write_text('{"holds":[]}')
    gates = [AdmissionGate(tmp_path, clock=lambda: NOW) for _ in range(4)]  # separate instances: flock, not the RLock, must serialize
    ok, bad = [], []

    def run(i):
        try:
            gates[i % 4].reserve("openrouter", 1_000_000, f"k{i}")
            ok.append(i)
        except AdmissionDenied as e:
            bad.append(e.reason)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(40)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ok) == 10  # openrouter subcap $10 / $1 each
    assert set(bad) == {"route_subcap"}
    assert gates[0].status()["used_micro"] == 10_000_000


# --- LangChain wiring -------------------------------------------------------
def _result(usage=None):
    return LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi", usage_metadata=usage))]])


def test_handler_reserves_then_settles_from_usage(gate):
    h = AdmissionHandler(gate, "openrouter", PRICING, 1000)
    h.on_chat_model_start({}, [[AIMessage(content="x" * 100)]], run_id="r1")
    assert gate.status()["used_micro"] > 100 * 5 + 10 * 25
    h.on_llm_end(_result({"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}), run_id="r1")
    assert gate.status()["used_micro"] == 100 * 5 + 10 * 25  # tokens * $/M == micro-USD
    h.on_llm_end(_result({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}), run_id="r1")  # replay is a no-op
    assert gate.status()["used_micro"] == 100 * 5 + 10 * 25


def test_handler_no_usage_or_error_keeps_hold(gate):
    h = AdmissionHandler(gate, "openrouter", PRICING, 1000)
    h.on_chat_model_start({}, [[AIMessage(content="x")]], run_id="r1")
    h.on_llm_end(_result(), run_id="r1")
    held = gate.status()["used_micro"]
    assert held > 0
    h.on_chat_model_start({}, [[AIMessage(content="x")]], run_id="r2")
    h.on_llm_error(RuntimeError("x"), run_id="r2")
    assert gate.status()["used_micro"] == held * 2


def test_handler_denies_missing_pricing_unknown_and_frozen(gate):
    for route, pricing, reason in [("openrouter", None, "pricing_unavailable"), (None, PRICING, "unknown_route"), ("x", PRICING, "route_frozen")]:
        with pytest.raises(AdmissionDenied) as e:
            AdmissionHandler(gate, route, pricing, 10).on_chat_model_start({}, [[AIMessage(content="x")]], run_id="r")
        assert e.value.reason == reason


def test_denial_blocks_real_model_invoke(gate):
    """raise_error=True means a denied reservation stops the call before the model runs."""
    paid = FakeListChatModel(responses=["paid"], callbacks=[AdmissionHandler(gate, None, PRICING, 10)])
    with pytest.raises(AdmissionDenied):
        paid.invoke("hello")
    local = FakeListChatModel(responses=["free"], callbacks=[AdmissionHandler(gate, "local", None, None)])
    assert local.invoke("hello").content == "free"


def test_resolve_route():
    assert pa.resolve_route(None, "https://openrouter.ai/api/v1") == "openrouter"
    assert pa.resolve_route(None, "http://127.0.0.1:8080/v1") is None  # loopback may be the paid glm-team proxy
    assert pa.resolve_route(None, "https://evil-openrouter.ai.example.com/v1") is None
    assert pa.resolve_route(None, None) is None
    assert pa.resolve_route("brain_forge", "https://x.example") == "brain_forge"


def test_cost_micro_cache_and_bad_pricing():
    assert pa.cost_micro(PRICING, 1000, 100, cache_read=400) == 600 * 5 + 400 * 0.5 + 100 * 25
    assert pa.cost_micro({"input_per_million": "x", "output_per_million": 1}, 1, 1) is None
    assert pa.cost_micro({**PRICING, "currency": "EUR"}, 1, 1) is None


def test_factory_wires_gate_default_on_and_off_switch(monkeypatch, tmp_path):
    from deerflow.config.model_config import ModelConfig

    monkeypatch.setenv("MOMO_ADMISSION_DIR", str(tmp_path))
    monkeypatch.setattr(pa, "_gate", None)
    cfg = ModelConfig(name="m", use="langchain_openai:ChatOpenAI", model="x", pricing=PRICING, admission_route="openrouter")
    on = FakeListChatModel(responses=["x"])
    monkeypatch.delenv("MOMO_ADMISSION_GATE", raising=False)
    pa.attach_admission(on, cfg, {"max_tokens": 5})
    assert any(isinstance(c, AdmissionHandler) for c in on.callbacks)
    off = FakeListChatModel(responses=["x"])
    monkeypatch.setenv("MOMO_ADMISSION_GATE", "off")
    pa.attach_admission(off, cfg, {})
    assert not off.callbacks


@pytest.mark.parametrize("route", ["cloud_spark_80h", "glm_team_proxy", "dot_ultrafast"])
def test_gap_review_routes_registered_but_denied_until_allowed(gate, route):
    assert denied(gate, route) == "route_subcap"  # known (not unknown_route) yet subcap 0
    (gate.dir / "registry.json").write_text(json.dumps({"subcaps": {route: 5_000}}))
    assert gate.reserve(route, 5_000, "ok")
    assert denied(gate, route, 1, "over") == "route_subcap"
