"""The loop runner: bounded attempts, stop on evidence, one receipt.

Rules this file enforces, each with a test:

* Stop on evidence. The loop ends when the spec's acceptance checks pass. A
  worker returning `done=True` without passing them is retried, not believed.
* Bounded. `1 + spec.max_retries` attempts, then escalate to `spec.escalate_to`.
* Idempotent. A unit with an accepted receipt returns that receipt and calls
  neither the worker nor the budget gate, so a restart replays no paid work.
* Fail closed on money. Every attempt reserves before the worker runs; a
  denial ends the run with no work done. An attempt that crashes is marked
  `unknown` so the gate keeps the full hold instead of freeing it for a retry.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from .budget import BudgetDenied, BudgetGate, FreeGate
from .contract import CheckResult, Receipt, ReceiptLog, RunOutput, TaskSpec, layer_reached

Worker = Callable[[TaskSpec, int], RunOutput]


def run_task(
    spec: TaskSpec,
    worker: Worker,
    *,
    receipts: ReceiptLog,
    gate: BudgetGate | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Receipt:
    """Run one unit of work and return the receipt it earned."""
    gate = gate or FreeGate()
    run_key = spec.run_key

    done = receipts.accepted(run_key)
    if done is not None:
        return done  # completed unit: no worker call, no reservation, no spend

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    begin = clock()
    spent = 0
    billed = False
    model = ""
    results: tuple[CheckResult, ...] = ()
    evidence: tuple[str, ...] = ()
    reason = ""

    for attempt in range(1, spec.max_retries + 2):
        try:
            rid = gate.reserve(spec.route, spec.cap_micro, f"{run_key}:{attempt}")
        except BudgetDenied as denied:
            # Nothing ran, so no layer was reached. Retrying a denial only
            # writes more deny rows, so this is terminal.
            return _write(
                receipts,
                spec,
                run_key,
                layer=None,
                ok=False,
                model=model,
                spent=spent,
                duration=clock() - begin,
                attempts=attempt - 1,
                results=results,
                evidence=evidence,
                reason=f"budget_denied:{denied.reason}",
                escalated_to=spec.escalate_to,
                started_at=started_at,
            )

        try:
            output = worker(spec, attempt)
        except Exception as exc:
            if rid is not None:
                gate.mark_unknown(rid)  # outcome unknown: keep the full hold
            reason = f"worker_error:{type(exc).__name__}: {exc}"[:400]
            continue

        if not isinstance(output, RunOutput):
            if rid is not None:
                gate.mark_unknown(rid)
            reason = "worker_output_invalid"
            continue

        spent += max(0, int(output.cost_micro))
        model = output.model or model
        evidence = output.evidence
        if rid is not None:
            gate.settle(rid, max(0, int(output.cost_micro)))
            billed = billed or output.cost_micro > 0

        results = tuple(check(spec, output) for check in spec.checks)
        reached = layer_reached(results, prepared=True, billed=billed)
        if reached in ("accepted", "billed"):
            return _write(
                receipts,
                spec,
                run_key,
                layer=reached,
                ok=True,
                model=model,
                spent=spent,
                duration=clock() - begin,
                attempts=attempt,
                results=results,
                evidence=evidence,
                reason="",
                escalated_to="",
                started_at=started_at,
            )
        failed = [r.name for r in results if not r.ok]
        reason = f"checks_failed:{','.join(failed)}" if failed else "acceptance_not_claimed"
        if output.done:
            reason = f"worker_reported_done_without_evidence; {reason}"

    attempts = spec.max_retries + 1
    return _write(
        receipts,
        spec,
        run_key,
        layer=layer_reached(results, prepared=bool(results or evidence), billed=billed),
        ok=False,
        model=model,
        spent=spent,
        duration=clock() - begin,
        attempts=attempts,
        results=results,
        evidence=evidence,
        reason=reason or "no_attempt_completed",
        escalated_to=spec.escalate_to,
        started_at=started_at,
    )


def _write(
    receipts: ReceiptLog,
    spec: TaskSpec,
    run_key: str,
    *,
    layer: str | None,
    ok: bool,
    model: str,
    spent: int,
    duration: float,
    attempts: int,
    results: tuple[CheckResult, ...],
    evidence: tuple[str, ...],
    reason: str,
    escalated_to: str,
    started_at: str,
) -> Receipt:
    # Rounded here, not at serialization, so the receipt in memory and the
    # receipt read back off disk compare equal.
    receipt = Receipt(
        task_id=spec.id,
        client_id=spec.client_id,
        run_key=run_key,
        layer=layer,
        ok=ok,
        route=spec.route,
        model=model,
        cost_micro=spent,
        duration_s=round(duration, 3),
        attempts=attempts,
        checks=results,
        evidence=evidence,
        reason=reason,
        escalated_to=escalated_to,
        started_at=started_at,
    )
    receipts.append(receipt)
    return receipt
