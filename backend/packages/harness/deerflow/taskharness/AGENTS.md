# Momo task harness

`spec -> worker -> verifier -> receipt`. Deliberately thin: no graph, no
scheduler, no adapter registry. `deerflow.workflows` is the durable LangGraph
kernel; this package is the small accountable wrapper a client workflow is
written in, and the two do not depend on each other.

A workflow is a `TaskSpec` (contract.py), a `Worker` callable, and a tuple of
checks (verify.py). `run_task` (runner.py) runs it and appends one `Receipt`.

Invariants, each pinned by a test in `tests/test_task_harness.py`:

- A spec with no checks, or with no `accepted` check, is rejected. A run can
  then only stop on evidence, never on a worker's `done=True`.
- `layer_reached` claims `prepared -> tested -> installed -> accepted -> billed`
  in order. A layer with no checks is passed through unclaimed; a layer with a
  failed check stops the climb. `billed` needs an accepted run and settled spend.
- Receipts are append-only JSONL, mode 0600, fsynced. The log is also the
  checkpoint: a unit with an accepted receipt returns it and calls neither the
  worker nor the gate, so a restart replays no paid work. A corrupt line fails
  closed.
- Money is reserved before the worker runs and settled from the actual cost. A
  denial is terminal. A crashed attempt is marked `unknown`, so the gate keeps
  the full hold. The default `FreeGate` refuses any nonzero amount.
- `JudgeCheck` fails on refutation **and** on an unavailable or off-contract
  judge, so it can fail a run whose deterministic checks are all green.
- `fan_out` (swarm.py) blocks `client_private` specs from contributor-tier
  models from `spec.data_class`, not from prompt wording, and walks the scale
  rungs 1 -> 10 -> N from `ScaleGuard` state.

Budget wiring lives in budget.py: the thin `BudgetGate` interface plus
`AdmissionGateAdapter`, which wraps `deerflow.models.paid_admission.AdmissionGate`
once that branch merges. `FakeGate` is the test double; no state dir, no money.

`weekly_reports.py` is the reference port (build -> QA at 390/768/1440 ->
deploy -> post, dry run by default). `python -m deerflow.taskharness.weekly_reports`
runs it end to end in a temp dir and prints the receipt.
