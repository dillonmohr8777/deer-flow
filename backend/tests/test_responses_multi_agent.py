"""Offline contract/admission tests; no provider credentials or network."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from deerflow.models.responses_multi_agent import (
    ActivationError,
    BudgetPolicy,
    BudgetProof,
    CycleJournal,
    OpenRouterTransport,
    Pilot,
    RequestLimits,
    UnknownOutcome,
    build_ordinary_tool_probe,
    build_request,
    parse_ordinary_tool_probe,
    parse_response,
)


def native_response(response_id="resp_1", *, cost="0.04", input_tokens=100, output_tokens=40):
    return {
        "id": response_id,
        "model": "openai/gpt-6.1-sol",
        "status": "completed",
        "output": [
            {"type": "message", "id": "progress", "agent": {"agent_name": "/root"}, "phase": "commentary", "content": [{"type": "output_text", "text": "Working"}]},
            {"type": "multi_agent_call", "id": "spawn", "call_id": "c1", "action": "spawn_agent", "agent": {"agent_name": "/root"}, "arguments": "{}"},
            {"type": "multi_agent_call_output", "id": "spawn_result", "call_id": "c1", "action": "spawn_agent", "agent": {"agent_name": "/root"}, "output": [{"type": "output_text", "text": '{"task_name":"/root/reviewer"}'}]},
            {"type": "message", "id": "child", "agent": {"agent_name": "/root/reviewer"}, "phase": "final_answer", "content": [{"type": "output_text", "text": "Worker findings"}]},
            {"type": "agent_message", "id": "mail", "author": "/root/reviewer", "recipient": "/root", "agent": {"agent_name": "/root"}, "content": [{"type": "encrypted_content", "encrypted_content": "opaque"}]},
            {"type": "message", "id": "final", "agent": {"agent_name": "/root"}, "phase": "final_answer", "content": [{"type": "output_text", "text": "Accepted result"}]},
        ],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost": cost},
    }


@pytest.fixture
def policy():
    return BudgetPolicy(cycle_id="cycle-1", approved=True, pilot_usd=Decimal("1"), account_remaining_usd=Decimal("10"), account_reserve_usd=Decimal("8"), max_requests=3)


@pytest.fixture
def proof():
    # Offline test attestation only. It is not evidence about any real provider.
    return BudgetProof(capability_response_id="canary-verified", aggregate_limit_usd=Decimal("1"), covers_descendants_and_continuations=True, evidence_reference="offline-fixture")


def make_journal(tmp_path, policy, proof):
    return CycleJournal(tmp_path / "receipts.sqlite3", policy=policy, proof=proof)


def test_build_request_pins_route_beta_privacy_and_empty_tool_allowlist():
    request = build_request("source packet", instructions="produce and independently review", receipt_id="r1", cycle_id="cycle-1")
    payload = json.loads(request.body)
    assert request.url == "https://openrouter.ai/api/v1/responses"
    assert request.headers["OpenAI-Beta"] == "responses_multi_agent=v1"
    assert payload["model"] == "openai/gpt-6.1-sol"
    assert payload["multi_agent"] == {"enabled": True, "max_concurrent_subagents": 2}
    assert payload["provider"] == {"only": ["OpenAI"], "allow_fallbacks": False, "data_collection": "deny", "require_parameters": True}
    assert payload["tools"] == [] and payload["store"] is False and payload["stream"] is False
    assert "max_tool_calls" not in payload
    assert "previous_response_id" not in payload


@pytest.mark.parametrize("limits", [RequestLimits(max_concurrent_subagents=0), RequestLimits(max_concurrent_subagents=3), RequestLimits(max_output_tokens=0), RequestLimits(max_output_tokens=2049), RequestLimits(max_input_bytes=0)])
def test_bad_limits_refused(limits):
    with pytest.raises(ActivationError):
        build_request("packet", instructions="instruction", receipt_id="r1", cycle_id="cycle-1", limits=limits)


def test_input_limit_counts_utf8_instructions_and_prompt():
    with pytest.raises(ActivationError, match="input"):
        build_request("éé", instructions="ab", receipt_id="r1", cycle_id="cycle-1", limits=RequestLimits(max_input_bytes=5))


def test_root_final_and_worker_progress_are_distinct():
    result = parse_response(native_response())
    assert result.accepted and result.root_final == "Accepted result"
    assert result.actual_cost_usd == Decimal("0.04")
    assert result.input_tokens == 100 and result.output_tokens == 40
    assert result.spawned_agents == ("/root/reviewer",)
    assert result.events[0].phase == "commentary"
    assert result.events[3].agent_name == "/root/reviewer"
    assert result.events[3].text == "Worker findings"
    assert result.events[4].author == "/root/reviewer" and result.events[4].text is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(output=[r["output"][-1]]),
        lambda r: r["output"].pop(2),
        lambda r: r["output"][2].update(output=[{"type": "output_text", "text": '{"error":"failed"}'}]),
        lambda r: r["output"].__setitem__(slice(3, 5), []),
        lambda r: r["output"][-1].pop("agent"),
        lambda r: r["output"][-1].update(phase="commentary"),
        lambda r: r["output"][-1].pop("id"),
        lambda r: r["output"][1].update(action="execute_shell"),
        lambda r: r["output"][-1].update(id="child"),
        lambda r: r.update(status="incomplete"),
        lambda r: r.update(model="openai/gpt-6-luna"),
        lambda r: r.update(output_text="I created two subagents", output=[]),
        lambda r: r["output"].append({"type": "function_call", "id": "write", "name": "write_file", "arguments": "{}", "agent": {"agent_name": "/root/reviewer"}}),
    ],
)
def test_ignored_beta_unpaired_spawn_unattributed_final_and_tools_rejected(mutation):
    response = native_response()
    mutation(response)
    result = parse_response(response)
    assert not result.accepted and result.errors
    # Even rejected responses may have incurred a bill: retain known cost.
    assert result.actual_cost_usd == Decimal("0.04")


@pytest.mark.parametrize("cost", [None, True, -1, "nan", "Infinity", "bad"])
def test_cost_unknown_is_not_zero(cost):
    result = parse_response(native_response(cost=cost))
    assert result.actual_cost_usd is None and not result.accepted


@pytest.mark.parametrize("tokens", [None, True, -1, "100"])
def test_missing_or_invalid_usage_refuses_accounting(tokens):
    result = parse_response(native_response(input_tokens=tokens))
    assert result.input_tokens is None and not result.accepted


@pytest.mark.parametrize(
    "change",
    [
        {"approved": False},
        {"pilot_usd": Decimal("3")},
        {"account_remaining_usd": Decimal("NaN")},
        {"max_requests": 0},
    ],
)
def test_activation_policy_refused_before_journal_write(tmp_path, policy, proof, change):
    with pytest.raises(ActivationError):
        make_journal(tmp_path, replace(policy, **change), proof)
    assert not (tmp_path / "receipts.sqlite3").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"capability_response_id": None},
        {"aggregate_limit_usd": None},
        {"aggregate_limit_usd": Decimal("2")},
        {"covers_descendants_and_continuations": False},
        {"evidence_reference": ""},
    ],
)
def test_unverified_provider_aggregate_limits_cannot_activate(tmp_path, policy, proof, change):
    with pytest.raises(ActivationError):
        make_journal(tmp_path, policy, replace(proof, **change))
    assert not (tmp_path / "receipts.sqlite3").exists()


def test_atomic_reservation_precedes_transport_and_survives_restart(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    observed = []

    async def post(request):
        reopened = make_journal(tmp_path, policy, proof)
        row = reopened.receipt("r1")
        observed.append(row["status"])
        assert row["request_sha256"] == request.sha256
        return native_response()

    result = asyncio.run(Pilot(journal, post).submit("packet", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2")))
    assert result.accepted and observed == ["inflight"]
    assert make_journal(tmp_path, policy, proof).receipt("r1")["status"] == "settled"
    assert journal.totals()["actual_cost_usd"] == Decimal("0.04")
    assert (tmp_path / "receipts.sqlite3").stat().st_mode & 0o077 == 0


def test_unknown_outcome_holds_budget_and_cannot_blind_retry(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    calls = []

    async def timeout(request):
        calls.append(request.sha256)
        raise TimeoutError("secret provider error must not be persisted")

    pilot = Pilot(journal, timeout)
    with pytest.raises(UnknownOutcome, match="r1"):
        asyncio.run(pilot.submit("packet", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2")))
    assert journal.receipt("r1")["status"] == "unknown"
    assert journal.totals()["actual_cost_usd"] is None
    for receipt_id in ("r1", "r2"):
        with pytest.raises(ActivationError):
            asyncio.run(pilot.submit("packet", instructions="review", receipt_id=receipt_id, reservation_usd=Decimal("0.2")))
    assert len(calls) == 1
    assert "secret provider error" not in str(journal.receipt("r1"))
    # Retrieval is external; reconciliation never calls the provider.
    recovered = journal.recover("r1", native_response())
    assert recovered.accepted
    assert journal.recover("r1", native_response()).accepted
    assert journal.totals()["actual_cost_usd"] == Decimal("0.04")
    assert len(calls) == 1


def test_crashed_inflight_receipt_blocks_a_new_dispatch(tmp_path, policy, proof):
    first = make_journal(tmp_path, policy, proof)
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    first.reserve("r1", request, Decimal("0.2"))
    reopened = make_journal(tmp_path, policy, proof)
    with pytest.raises(ActivationError):
        reopened.reserve("r2", request, Decimal("0.2"))


def test_continuations_require_verified_parent_and_sum_aggregate_usage(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    calls = []

    async def post(request):
        calls.append(json.loads(request.body))
        return native_response(f"resp_{len(calls)}", cost="0.06", input_tokens=20, output_tokens=10)

    pilot = Pilot(journal, post)
    with pytest.raises(ActivationError, match="parent"):
        asyncio.run(pilot.submit("next", instructions="review", receipt_id="bad", reservation_usd=Decimal("0.2"), previous_response_id="foreign"))
    asyncio.run(pilot.submit("first", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2")))
    asyncio.run(pilot.submit("second", instructions="review", receipt_id="r2", reservation_usd=Decimal("0.2"), previous_response_id="resp_1"))
    assert calls[1]["previous_response_id"] == "resp_1"
    assert journal.totals() == {"actual_cost_usd": Decimal("0.12"), "known_cost_usd": Decimal("0.12"), "input_tokens": 40, "output_tokens": 20, "requests": 2}


def test_concurrent_budget_admission_has_one_durable_winner(tmp_path, policy, proof):
    make_journal(tmp_path, policy, proof)

    def reserve(index):
        journal = make_journal(tmp_path, policy, proof)
        request = build_request("packet", instructions="review", receipt_id=f"r{index}", cycle_id=policy.cycle_id)
        try:
            journal.reserve(f"r{index}", request, Decimal("0.7"))
            return True
        except ActivationError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1
    assert make_journal(tmp_path, policy, proof).totals()["requests"] == 1


def test_known_overrun_and_missing_cost_stop_the_cycle(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    journal.reserve("r1", request, Decimal("0.2"))
    result = journal.recover("r1", native_response(cost="0.3"))
    assert not result.accepted
    assert journal.totals()["known_cost_usd"] == Decimal("0.3")
    with pytest.raises(ActivationError):
        journal.reserve("r2", request, Decimal("0.2"))


def test_recovery_cannot_reassign_response_id_or_change_settled_payload(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    journal.reserve("r1", request, Decimal("0.2"))
    journal.recover("r1", native_response())
    with pytest.raises(ActivationError):
        journal.recover("r1", native_response(cost="0.09"))
    second_request = build_request("packet", instructions="review", receipt_id="r2", cycle_id=policy.cycle_id)
    journal.reserve("r2", second_request, Decimal("0.2"))
    with pytest.raises(ActivationError):
        journal.recover("r2", native_response())
    assert journal.totals()["known_cost_usd"] == Decimal("0.04")


def test_journal_configuration_cannot_be_changed_on_restart(tmp_path, policy, proof):
    make_journal(tmp_path, policy, proof)
    with pytest.raises(ActivationError, match="policy"):
        make_journal(tmp_path, replace(policy, max_requests=4), proof)


def test_real_http_serialization_has_no_redirect_retry_or_implicit_tools(tmp_path, policy, proof):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url == "https://openrouter.ai/api/v1/responses"
        assert request.headers["OpenAI-Beta"] == "responses_multi_agent=v1"
        assert json.loads(request.content)["tools"] == []
        return httpx.Response(200, json=native_response())

    async def run():
        transport = OpenRouterTransport("offline-key", transport=httpx.MockTransport(handler))
        try:
            return await Pilot(make_journal(tmp_path, policy, proof), transport).submit("packet", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2"))
        finally:
            await transport.aclose()

    assert asyncio.run(run()).accepted and len(requests) == 1


def test_http_redirect_is_unknown_without_following_or_retry(tmp_path, policy, proof):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://not-approved.example/responses"})

    async def run():
        transport = OpenRouterTransport("offline-key", transport=httpx.MockTransport(handler))
        try:
            await Pilot(make_journal(tmp_path, policy, proof), transport).submit("packet", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2"))
        finally:
            await transport.aclose()

    with pytest.raises(UnknownOutcome):
        asyncio.run(run())
    assert len(requests) == 1 and make_journal(tmp_path, policy, proof).receipt("r1")["status"] == "unknown"


def test_ordinary_sol_probe_omits_beta_and_has_one_narrow_read_only_tool():
    request = build_ordinary_tool_probe("public-packet", receipt_id="probe-1", cycle_id="probe-cycle")
    payload = json.loads(request.body)
    assert payload["model"] == "openai/gpt-6.1-sol"
    assert "multi_agent" not in payload and "OpenAI-Beta" not in request.headers
    assert payload["provider"]["data_collection"] == "deny" and payload["provider"]["allow_fallbacks"] is False
    assert payload["tool_choice"] == {"type": "function", "name": "get_source_packet"}
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "get_source_packet",
            "description": "Read the single explicitly supplied source packet; no writes or external actions.",
            "strict": True,
            "parameters": {"type": "object", "properties": {"packet_id": {"type": "string", "enum": ["public-packet"]}}, "required": ["packet_id"], "additionalProperties": False},
        }
    ]


def ordinary_response():
    return {
        "id": "ordinary_1",
        "model": "openai/gpt-6.1-sol",
        "status": "completed",
        "output": [{"type": "function_call", "id": "fc1", "call_id": "c1", "name": "get_source_packet", "arguments": '{"packet_id":"public-packet"}'}],
        "usage": {"cost": "0.01", "input_tokens": 5, "output_tokens": 4},
    }


def test_ordinary_probe_needs_actual_exact_function_call_not_text_claim():
    result = parse_ordinary_tool_probe(ordinary_response(), packet_id="public-packet")
    assert result.accepted and result.actual_cost_usd == Decimal("0.01")
    assert result.function_call_id == "c1" and result.response_id == "ordinary_1"
    assert not parse_response(ordinary_response()).accepted


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(output=[{"type": "message", "content": [{"type": "output_text", "text": "I called get_source_packet"}]}]),
        lambda r: r["output"][0].update(name="write_file"),
        lambda r: r["output"][0].update(arguments='{"packet_id":"other"}'),
        lambda r: r["output"][0].update(arguments='{"packet_id":"public-packet","path":"secret"}'),
        lambda r: r["output"][0].update(arguments="invalid json"),
        lambda r: r["output"][0].pop("call_id"),
        lambda r: r.update(model="openai/gpt-6-luna"),
        lambda r: r.update(usage=None),
        lambda r: r.update(status="incomplete"),
        lambda r: r["output"].append(dict(r["output"][0])),
    ],
)
def test_ordinary_probe_rejects_unsupported_or_unaccounted_routes(mutation):
    response = ordinary_response()
    mutation(response)
    assert not parse_ordinary_tool_probe(response, packet_id="public-packet").accepted


def test_unknown_cost_can_be_reconciled_without_changing_result(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    journal.reserve("r1", request, Decimal("0.2"))
    assert not journal.recover("r1", native_response(cost=None)).accepted
    assert journal.totals()["actual_cost_usd"] is None
    assert journal.recover("r1", native_response(cost="0.04")).accepted
    assert journal.totals()["actual_cost_usd"] == Decimal("0.04")
    history = journal.history("r1")
    assert [entry["kind"] for entry in history] == ["reserved", "response_recorded", "accounting_reconciled"]
    assert json.loads(history[1]["payload"])["usage"]["cost"] is None
    assert json.loads(history[2]["payload"])["usage"]["cost"] == "0.04"
    journal.recover("r1", native_response(cost="0.04"))
    assert journal.history("r1") == history  # no duplicated accounting event
    second = build_request("packet", instructions="review", receipt_id="r2", cycle_id=policy.cycle_id)
    journal.reserve("r2", second, Decimal("0.2"))


def test_request_count_and_cumulative_dollars_cannot_reset_with_continuation(tmp_path, policy, proof):
    journal = make_journal(tmp_path, replace(policy, max_requests=1), proof)
    first = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    second = build_request("packet", instructions="review", receipt_id="r2", cycle_id=policy.cycle_id, previous_response_id="resp_1")
    journal.reserve("r1", first, Decimal("0.9"))
    journal.recover("r1", native_response(cost="0.8"))
    with pytest.raises(ActivationError, match="request limit"):
        journal.reserve("r2", second, Decimal("0.1"))


def test_request_headers_cannot_mutate_after_reservation():
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id="cycle-1")
    request.headers["OpenAI-Beta"] = "ignored"
    assert request.headers["OpenAI-Beta"] == "responses_multi_agent=v1"


def test_forged_request_cannot_bypass_empty_tool_policy(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    request = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    payload = json.loads(request.body)
    payload["tools"] = [{"type": "local_shell"}]
    with pytest.raises(ActivationError, match="request"):
        journal.reserve("r1", replace(request, body=json.dumps(payload).encode()), Decimal("0.2"))
    assert journal.totals()["requests"] == 0


def test_cumulative_reservation_preserves_external_ceiling(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, replace(proof, aggregate_limit_usd=Decimal("0.5")))
    first = build_request("packet", instructions="review", receipt_id="r1", cycle_id=policy.cycle_id)
    second = build_request("packet", instructions="review", receipt_id="r2", cycle_id=policy.cycle_id, previous_response_id="resp_1")
    journal.reserve("r1", first, Decimal("0.4"))
    journal.recover("r1", native_response(cost="0.4"))
    with pytest.raises(ActivationError, match="budget"):
        journal.reserve("r2", second, Decimal("0.2"))
    assert journal.totals()["requests"] == 1


def test_cancelled_dispatch_retains_unknown_receipt_and_is_not_retried(tmp_path, policy, proof):
    journal = make_journal(tmp_path, policy, proof)
    calls = []

    async def run():
        dispatched = asyncio.Event()
        release = asyncio.Event()

        async def post(request):
            calls.append(request.sha256)
            dispatched.set()
            await release.wait()
            return native_response()

        task = asyncio.create_task(Pilot(journal, post).submit("packet", instructions="review", receipt_id="r1", reservation_usd=Decimal("0.2")))
        await dispatched.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(calls) == 1
    assert journal.receipt("r1")["status"] == "unknown"


def test_private_journal_rejects_symlinks_and_public_modes(tmp_path, policy, proof):
    public = tmp_path / "public.sqlite3"
    public.write_bytes(b"")
    public.chmod(0o644)
    with pytest.raises(ActivationError, match="private"):
        CycleJournal(public, policy=policy, proof=proof)
    private = tmp_path / "private.sqlite3"
    private.write_bytes(b"")
    private.chmod(0o600)
    link = tmp_path / "link.sqlite3"
    link.symlink_to(private)
    with pytest.raises(ActivationError, match="private"):
        CycleJournal(link, policy=policy, proof=proof)
