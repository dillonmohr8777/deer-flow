# Normal lead run limits

The startup-only operator `run` block applies to every normal
`RunManager`-backed lead run, regardless of role or request transport:

```yaml
run:
  execution_timeout_seconds: 2700
  prestart_wait_seconds: 300
```

Each field accepts finite seconds within the UTC timestamp range; `null` or a value at or below zero disables
that field for rollback. Restart all Gateway workers to change admission policy.
Requests cannot override it through metadata, context, configurable or config.
Existing runs retain their captured policy. Neither scheduler queue age, worker
leases, heartbeat renewal nor recursion budgets are execution deadlines.

Admission captures the configured seconds and absolute UTC pre-start deadline.
Only the store's successful pending-to-running compare-and-set stamps execution
start and deadline. Duplicate starts, snapshots, heartbeats, idempotent retries,
hydration and changed manager defaults do not extend those values. Local timers
translate the persisted UTC deadline to monotonic time once per phase. UTC clock
synchronization remains necessary when reading persisted times on another host.

Memory storage has a separate private `run_limits` field. SQL stores a tagged
array containing original kwargs and timing in the existing `kwargs_json`
column. Legacy/API kwargs are objects, so no caller key collides with that
envelope. Store projections unwrap it before returning kwargs. User metadata
remains unchanged and queryable; no control enters thread/checkpoint metadata.
No migration is required. Old object-shaped rows have no captured timing and
retain ordinary orphan recovery. Limit-capable stores keep the existing
`start_run(run_id)` signature; optional timing arguments do not add abstract
methods. Unsupported custom stores reject enabled admission explicitly, and
retain their old protocol when both operator limits are disabled.

The supervisor starts at admission, including when no worker attaches. It
bounds the prior-finalization barrier and pending preflight separately from
execution. `create_worker_task()` owns the preflight coroutine, including
cancellation before its first step. An expiry cancels owned execution through
the existing abort path. The first durable cancellation cause wins; ordinary
interrupt and rollback semantics remain unchanged.

Pre-start expiry is `error` with `stop_reason=prestart_wait_timeout`. Execution
expiry is `timeout` with `stop_reason=execution_timeout`. Both emit the existing
`run.error` contract and one stream END after cleanup. The active durable row
and local finalizing barrier remain held while owned work drains. Internal
timeout cancellation claims cannot be retired by lease recovery or a newer
interrupt/rollback admission; unknown cleanup remains held for operator repair.
An independently detected cleanup failure uses private `cleanup_hold`, active
status and `cleanup_unconfirmed`; it is not mislabeled as an early timeout.
These internal causes are never additional public HTTP cancellation actions.
A persisted expired execution deadline independently fences orphan takeover and
replacement, even if the deadline-time cancellation write failed. Only the
original worker's confirmed terminal drain releases that row. Pending/pre-start,
non-run, legacy and disabled-policy recovery retain their existing behavior.
Pre-deadline partition behavior remains the inherited lease protocol; this is
not a claim of complete distributed fault tolerance.
Timeouts do not settle/refund unknown paid reservations, retry external actions
or decide approvals. Non-run operations, especially durable `upload_write`
holds, receive no clocks and keep their original admission/release rules.

Ordinary `task` children register server-created handles before their first
await. Completion is a cross-loop event set after actual execution, sandbox
release and task-stop cleanup, independently of `Future.cancel()` or a terminal
result object. Cancellation before entry is separately fenced as proven no-work.
The private host tracker is rejected from caller context/configurable and is
never checkpoint data. Durable/independent batch jobs retain their separate
ownership and success semantics; they do not use this ordinary-child tracker.

Managed workers stage root-graph `run.end` events across continuations and
evaluation. They publish one final success only after owned cleanup and
observers finish and cancellation has lost. Standalone journals retain their
existing behavior. Local status remains active during finalization. After owned
child, sandbox and task-stop cleanup drains, the final cause/status is committed
once, the completion callback receives the same real `RunRecord`, then END is
published. Scheduler completion therefore observes final truth.

Gateway web, stream, wait, stateless, delegated/internal and HTTP SDK calls share
this manager. The separate synchronous embedded `DeerFlowClient.stream()` does
not use RunManager and is outside this phase. The optional Momentum SDK offline
reviewer is host-only/default-off and already bounds its synthetic subprocess
to 35 seconds by default, with a 60-second operator maximum and kill/wait cleanup.
This contract establishes source behavior, not provider, native process,
multi-process PostgreSQL, runtime or release acceptance.

Verification: `tests/test_lead_run_limits.py` plus existing manager, repository,
multi-worker ownership, cancel, rollback, metadata and extension lifecycle
controls. Synthetic clocks/events and local SQLite/memory only; no live models.
