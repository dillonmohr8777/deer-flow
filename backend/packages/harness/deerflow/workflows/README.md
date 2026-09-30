# Durable MomoBot workflows

The catalog contains 100 explicit Momentum marketing/operations/development tasks
plus 20 personal writing/music/research/coding/admin tasks. Every task has distinct
required input fields, bounded output fields, task instructions and three independent
acceptance criteria. Preview examples are fictional and marked `SYNTHETIC`.
Twenty tasks require public read-only browser evidence; personal tasks use supplied
inputs only. Nothing in this package scans local files, sends messages, publishes,
submits forms, changes advertising settings or purchases services.

## Interfaces

```python
from deerflow.workflows.catalog import get_workflow, list_workflows, validate_inputs
from deerflow.workflows.engine import WorkflowEngine

definition = get_workflow("novel-chapter-continuity")
inputs = validate_inputs(definition, supplied_inputs)
result = await WorkflowEngine(checkpointer).execute(
    definition, inputs, run_id=server_run_id, scope=server_owner_org_namespace,
    framework="langgraph", model_call=budgeted_model_callback,
    browser_call=authorized_browser_callback, event=durable_event_callback,
    resume=False,
)
```

`model_call` receives keyword arguments `worker_id`, `role`, `prompt`,
`output_schema`, `effort`, `model`, `continuation` and `call_id`. The result must
contain a schema-valid `output`, actual selected `model`/`effort`, and nonnegative
integer `usage.input_tokens`/`output_tokens`; unavailable `usage.cost` is null.
Only `gpt-6.1-sol` with low/medium/high effort is sanctioned by this kernel.
The planner chooses the category specialist or general specialist and producer
effort. A separate verifier worker always reviews the resulting draft.

Adapter names are `langgraph`, `crewai`, `mastra`, `deepagents`, `agno`, `agentkit`.
Those names choose the injected executor; they do not prove an adapter is installed
or available. The Gateway owns capability checks, isolated adapters, authorization,
durable admissions, actual provider use and billing.

`browser_call(urls)` returns nonempty bounded `pages` with original requested `url`,
`title` and `text`, plus durable `evidence` references. Required browser work fails
before any model call if retrieval or evidence is unavailable. Sources must be
public HTTPS with no credentials or private literal addresses. DNS/rebinding,
redirect, subresource and action enforcement belong in the browser adapter;
hostname validation in this kernel is not a network security boundary.

Optional `pages[].stagehand_extract.data` is a closed title/summary/claims object.
It enters planner/draft context as bounded untrusted evidence; transport metadata
is stripped. Exact nonblank quotes must occur within the actual rendered
24,000-UTF-16-unit source prefix. Invalid shape/quotes stop before model drafting.
Canonical extraction, rendered source-prefix and full source hashes remain
separate; a quotation match does not establish that its claim is true.

`event(name, status, **details)` records concise step events with worker/model/effort
or a bounded detail code. It receives no private prompts or source body. Final
`result` is `{output, evidence, accepted}`. `WorkflowError.code` is a sanitized
failure code; exceptions may carry LangGraph task notes, so APIs expose the code
rather than raw exception traces.

## Durability and recovery

The native graph is validate → research → plan → draft → verify → accept, with
one revise/reverify cycle allowed. This is three normal model calls, five maximum.
Revision reuses the same producer identity and its previous conversation; the
verifier also retains its prior review. Stable identities derive from the opaque
scope, server run ID and role. Graph checkpoints retain admitted input hashes,
recipe/schema hashes, provider-independent worker conversations and output hashes.
Large prior briefs are summarized for continuation with their full-brief digest;
the current admitted context is supplied again. Context truncation is explicit.

Use an actual persistent checkpointer such as `AsyncSqliteSaver`. A process-local
memory saver is useful only in tests. Restart with `resume=True` reads the saved
next graph node and rejects altered owner scope, inputs, recipe/schema, framework
or a missing checkpoint. A completed run can be read back without provider calls.
Different owner/run pairs cannot load each other's conversation or worker IDs.

Calls to the same namespace serialize across engine instances on the event loop.
This is not a distributed lease: the Gateway must prevent simultaneous execution
in different processes and fence stale ownership. Different runs remain independent.

Before every provider call the Gateway must durably reserve the deterministic
`call_id` and original budget. A crash after provider dispatch but before a graph
checkpoint cannot establish that no charge occurred. Resume must replay a known
validated receipt or reject an uncertain paid admission, never issue an automatic
duplicate. The same rule applies to Browserbase creation under its run-specific
idempotency key. Cancellation propagates promptly; source/browser cleanup is the
callback owner's responsibility. Resume retains the original Gateway budget.

## Acceptance and bounds

Inputs are closed-schema objects and at most 48,000 UTF-8 bytes. Outputs are closed
objects capped at 48,000 bytes; common fields identify the workflow, draft status,
assumptions and admitted evidence references. Per-task deliverable fields have
count/length limits; ad headlines/descriptions and SEO descriptions have explicit
character bounds. Browser text passed to models is bounded and marked when truncated.
Prompt/context and continuation limits match the isolated adapter contract.

Acceptance fails on missing or additional output fields, invented provenance,
missing/duplicate review criteria, a changed candidate hash, failed checks or
unresolved blockers. The output artifact hashes exact canonical JSON: UTF8,
sorted keys, compact separators and no NaN. Input and browser source evidence
include content hashes. A valid hash proves identity/readback, not factual truth.
Independent model review is useful evidence but can still be wrong; `accepted`
means this draft passed the specified structural and independent-review gates.
It does not mean the owner approved, published or adopted the work.

Actual token, call, dollar, browser concurrency and deadline ceilings remain
Gateway admission responsibilities. The kernel never overrides them or infers
cost from list pricing. A paid-budget callback rejection stops execution before
the next provider dispatch. All output remains reviewable draft material.

## Offline evidence

`test_workflow_catalog.py` validates all 120 input/output schemas, distinct
definitions, synthetic previews, bounds and public URL rejection. The engine tests
execute every recipe through a real graph with explicit model/browser doubles,
then check hash-bound artifacts, schema/provenance/receipt failures, bounded
rejection, SQLite restart/resume, saved producer reuse, identity fences and
concurrent replay. These tests prove execution contracts; they are not 120 paid
provider runs or proof that 120 useful real-world outputs have been accepted.

Gateway integration tests use real session and CSRF middleware, real SQLite
organization membership resolution, the workflow service and native run/event
stores. They reject stale actor or workspace scopes, foreign artifacts, PATs,
missing permissions and invalid inputs before provider admission. Membership is
checked again when a queued job executes. The entitlement bridge is exercised
with an injected modern policy; absence of the policy on the historical base
preserves the existing permission and ownership gates.

Native lifecycle tests use persistent SQLite graph checkpoints to resume saved
steps and known receipts without new paid attempts. They verify native journal
recovery, per-native usage deltas, cumulative job totals, cancellation cleanup,
queue admission and private artifact visibility. Startup tests drive the actual
Gateway lifespan with an isolated native runtime context and verify that it
passes shared components to the workflow service and closes that service before
runtime teardown. Credential resolution and model outputs are synthetic in all
these tests; they do not establish a live provider result or installed runtime.
