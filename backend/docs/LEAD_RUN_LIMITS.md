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

Memory storage has a separate private `run_limits` field. SQL stores the same
host-owned capture in nullable `runs.run_limits_json`. `kwargs_json` remains the
original object and public metadata retains its original values. Neither field
can replace the private capture; snapshots preserve the admission column even
when callers omit timing, spoof it in metadata/kwargs, or use disabled defaults.
No control enters thread/checkpoint metadata. Old rows have no captured timing
and retain ordinary orphan recovery. Limit-capable stores keep the existing
`start_run(run_id)` signature; unsupported custom stores reject enabled admission
explicitly and keep their old protocol when both operator limits are disabled.

This one additive nullable JSON column is an explicit exception to the normal
Alembic revision rule. After successful ordinary bootstrap, its existing lock
owns an idempotent helper that adds the column or rejects incompatible shape.
The helper changes no revision, index, constraint, default, existing data or
unknown-revision allowlist. The known `0052_board_portal` stamp stays readable
by the accepted rollback images. Fresh databases get the same nullable shape
from the ORM. Actual accepted `dc420` bootstrap and repositories must read new
histories with exact original kwargs, write metadata/kwargs without clearing
private captures, and insert rows the new reader can consume. The matching
`1fde` bootstrap/decoder bytes are pinned in the source receipt. Code rollback
still requires draining all active work and unknown cleanup holds before old
writers start; disabling limits changes future admission only.

The supervisor starts at admission, including when no worker attaches. It
bounds the prior-finalization barrier and pending preflight separately from
execution. `create_worker_task()` owns the preflight coroutine, including
cancellation before its first step. An expiry cancels owned execution through
the existing abort path. The first durable cancellation cause wins; interrupt
keeps the checkpoint and rollback restores the pre-run checkpoint.

Actual services metadata preparation owns and drains its metadata and abort
children before the outer preflight returns, including repeated cancellation.
Metadata work is created only inside the admitted worker; refused or reused
admissions do not create that child. The lead worker joins its shielded finalizer
through child, sandbox and task-stop cleanup, final status, callback and END.
Host cancellation cannot abandon that owned cleanup. The existing completion
callback tail remains cancellable after final status commits; its interruption
still reaches the final END and local cleanup.
If host cancellation interrupts metadata preflight after a public interrupt or
rollback, the same owned preflight guard finishes that first cause after the
metadata child drains. It persists `interrupted` or rollback `error`, calls the
existing completion hook once with the same real final record, then publishes
one END. This path never constructs the graph or restores a checkpoint for work
that never started. Unknown cleanup holds, non-run operations and historical
store-only rows are not finalized by this owner-only path.
Ordinary children mark actual cleanup entry separately from public result state;
their sandbox/task-stop cleanup is also shielded and joined across the entry
race. No cancelled Future or outer awaiter substitutes for actual completion.

Pre-start expiry is `error` with `stop_reason=prestart_wait_timeout`. Execution
expiry is `timeout` with `stop_reason=execution_timeout`. Both emit the existing
`run.error` contract and one stream END after cleanup. The active durable row
and local finalizing barrier remain held while owned work drains. Internal
timeout cancellation claims cannot be retired by lease recovery or a newer
interrupt/rollback admission; unknown cleanup remains held for operator repair.
An independently detected cleanup failure uses private `cleanup_hold`, active
status and `cleanup_unconfirmed`; it is not mislabeled as an early timeout.
These internal causes are never additional public HTTP cancellation actions.
A captured active RUN retains durable admission after any persisted stop
request, including user interrupt and rollback, until actual cleanup finishes.
Attached workers keep local and stored status active during that drain. Either
expired captured phase deadline (pre-start or execution) independently fences
orphan takeover and replacement if the timeout claim could not be persisted.
An expired pending capture with no confirmed owner therefore remains held for
operator repair; a peer cannot assume that metadata work has stopped. Only the
original worker's confirmed terminal drain releases the row. Non-run operations,
terminal or uncaptured legacy rows, and disabled captures without a stop request
retain their previous recovery behavior.
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
