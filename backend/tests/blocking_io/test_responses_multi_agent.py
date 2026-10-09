"""Durable receipt admission/reconciliation stays off the async event loop."""

import asyncio
from decimal import Decimal

import pytest

from deerflow.models.responses_multi_agent import BudgetPolicy, BudgetProof, CycleJournal, Pilot, UnknownOutcome


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_failure", [False, True])
async def test_receipt_dispatch_and_unknown_recovery_offload_storage(tmp_path, transport_failure):
    policy = BudgetPolicy("strict-cycle", True, Decimal("1"), Decimal("10"), Decimal("8"))
    proof = BudgetProof("offline-fixture", Decimal("1"), True, "offline-contract")
    journal = await asyncio.to_thread(CycleJournal, tmp_path / "receipts.sqlite3", policy=policy, proof=proof)

    async def post(request):
        row = await asyncio.to_thread(journal.receipt, "strict-r1")
        assert row["status"] == "inflight" and row["request_sha256"] == request.sha256
        if transport_failure:
            raise TimeoutError("offline timeout")
        return {
            "id": "strict-resp",
            "status": "completed",
            "model": "openai/gpt-6.1-sol",
            "metadata": {"cycle_id": "strict-cycle", "receipt_id": "strict-r1"},
            "output": [
                {"id": "spawn", "type": "multi_agent_call", "action": "spawn_agent", "call_id": "c1", "agent": {"agent_name": "/root"}},
                {"id": "spawn-result", "type": "multi_agent_call_output", "action": "spawn_agent", "call_id": "c1", "agent": {"agent_name": "/root"}, "output": [{"type": "output_text", "text": '{"task_name":"/root/reviewer"}'}]},
                {"id": "child", "type": "message", "phase": "final_answer", "agent": {"agent_name": "/root/reviewer"}, "content": [{"type": "output_text", "text": "Review"}]},
                {"id": "root-final", "type": "message", "phase": "final_answer", "agent": {"agent_name": "/root"}, "content": [{"type": "output_text", "text": "Result"}]},
            ],
            "usage": {"cost": "0.01", "input_tokens": 10, "output_tokens": 10},
        }

    pilot = Pilot(journal, post)
    if transport_failure:
        with pytest.raises(UnknownOutcome, match="strict-r1"):
            await pilot.submit("source", instructions="review", receipt_id="strict-r1", reservation_usd=Decimal("0.1"))
    else:
        assert (await pilot.submit("source", instructions="review", receipt_id="strict-r1", reservation_usd=Decimal("0.1"))).accepted
    totals = await asyncio.to_thread(journal.totals)
    assert totals["actual_cost_usd"] == (None if transport_failure else Decimal("0.01"))
