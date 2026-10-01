# MomoBot workflows

The authenticated `/workspace/workflows` room and Mac workbench client use the
existing Gateway runtime. The catalog contains 100 concrete Momentum marketing,
operations and development recipes, plus 20 personal writing, music, research,
coding and administration recipes. All 120 have distinct task instructions,
required input fields, bounded deliverables and three acceptance criteria.
Preview examples are fictional and marked `SYNTHETIC`; they supply no canonical
client facts. Personal recipes use supplied inputs and do not scan private files.

The native LangGraph controller runs validate → research → plan → draft → verify
→ accept, with one revise/reverify cycle. The planner chooses an admitted
specialist role and low/medium/high reasoning effort. A separate verifier checks
the producer's candidate against every criterion and its exact content hash.
The six adapter IDs are `langgraph`, `crewai`, `mastra`, `deepagents`, `agno` and
`agentkit` (Inngest AgentKit). Optional workers execute actual framework APIs
through a finite handoff; they receive no model key and cannot create a queue,
choose another provider model, raise a budget or retry an uncertain attempt.
They share the Gateway's `gpt-6.1-sol` Responses broker. Installed/configured
capability is reported separately from accepted output.

## Native state and ownership

Gateway passes its existing RunManager, thread store, run-event store and shared
checkpointer to `WorkflowService`. Workflow graph checkpoints use their own
owner/run namespace within that checkpointer. Stable worker identities and
bounded conversation history survive node continuation and restart; isolated
worker processes are finite and need not stay running between calls.

`workflows.sqlite` is a private admission, attempt and artifact-receipt ledger
under the configured application data directory. The dedicated private launcher
requires an explicit `run_events` section; `prepare-config` appends the missing
`backend: db` default with a private raw-config backup and existing SQLite path.
Explicit owner settings are preserved. Historical memory events are not backfilled.
The ledger is not a client registry or
replacement for a canonical operational queue. It stores the actor, organization
and workspace storage principal separately, hashing all three into an opaque
owner scope. Every lookup/action requires that scope; a different actor in the
same shared workspace still cannot read or act on another actor's workflow.
Background execution rechecks membership, storage identity and `runs:create`
before provider/browser work and before acceptance.

Native workflow thread/run/event rows use a separate storage principal derived
from the full owner scope, bounded to the native stores' 64-character column.
Ordinary shared-workspace thread search, history, message, run and cancel routes
cannot authorize that principal, including when given the exact IDs. Authorized
workflow reads/actions use the Workflow room. Original actor, organization and
workspace identities remain available for actual authority and entitlement checks.
Native repository start, completion and journal operations temporarily select
that private principal with a `NULL` organization, the existing native quarantine
marker. They do not create an organization or authentication user. This context
is restored before provider callbacks or actual workspace authority checks; SQL
repositories reject normal organization-scoped access to the quarantined rows.

Startup fails with `workflow_native_namespace_migration_required` when an
existing workflow ledger has native journal identities without the matching
private-native ownership receipt. It does not rewrite legacy thread/run/event
rows or serve them through a shared namespace. Those records need an explicit,
bounded migration before that state can be served. Historical standalone
admissions without a native journal still load; production installation must
preserve the existing private application state rather than copy QA journals.

The process holds an exclusive ledger lease before restart recovery. Queued jobs
are claimed atomically. Previously running jobs become `interrupted`; only those
jobs can be explicitly resumed, at most three times. Recipe/input/framework
identity and original budgets remain pinned. Each deterministic model call ID is
reserved before dispatch. A known validated receipt replays without another paid
call; an uncertain reserved attempt rejects resume. Resumed native run records
report their own usage delta, while the workflow retains cumulative usage.
Missing AI events replay against the original native run, deduplicated by call ID.

## HTTP contract

Browser sessions require normal authentication, active organization membership
and CSRF protection for mutations. PATs remain denied on this entire surface,
even if their scopes include every run permission. Create and resume additionally
use the existing paid-run entitlement bridge when the integration lane supplies
it; the historical base without that subsystem retains permission/scope checks.

First request `GET /api/workflows/status` with `X-Expected-User-Id` matching the
session actor. Use its returned `owner_scope` as `X-Expected-Workflow-Scope` on
subsequent calls. An account/workspace change returns `409 workspace_scope_changed`;
refreshing the scope does not grant access to an earlier owner's job (`404`).

| Method and path | Result or admission |
| --- | --- |
| `GET /api/workflows/status` | Enabled state, installed/configured capabilities, limits, scoped counts and owner scope |
| `GET /api/workflows/catalog` | All 120 schema definitions and synthetic examples |
| `GET /api/workflows/runs` | Latest 100 runs in the caller's scope |
| `POST /api/workflows/runs` | `{workflow_id, inputs, framework}` plus required `Idempotency-Key` |
| `GET /api/workflows/runs/{id}` | Status, steps, accepted draft, evidence, usage and artifact receipt |
| `POST /api/workflows/runs/{id}/cancel` | Atomic cancellation and drained worker cleanup |
| `POST /api/workflows/runs/{id}/resume` | Explicit interrupted-run continuation under the original bounds |
| `GET /api/workflows/runs/{id}/artifact` | Private download only after completion and acceptance |

Read routes require `runs:read`, create/resume `runs:create`, and cancel
`runs:cancel`. Extra request controls, unknown frameworks/recipes and invalid
closed-schema inputs fail before admission. The same idempotency key and exact
inputs return the existing job; a changed payload returns `409`. The offline
catalog remains readable when the feature service is disabled; status and paid
admission return `503 not_enabled` when it is absent.

## Finite limits and receipts

The default capacity is three executing jobs and 100 waiting slots, enforced as
103 total queued/running admissions. Per logical job, the ledger permits at most
six model attempts, 8,192 output tokens and 60,000 input tokens. A rolling
24-hour global ceiling admits 240 model attempts across owners. All native,
framework and Stagehand model requests use these counters. Attempts include
preflight failures and uncertain provider outcomes; they are not inferred billed
calls. `unknown_model_calls` and `usage.complete` distinguish unresolved receipts.
Known input/output usage comes from the provider; unreturned billed cost is `null`.
No cost winner is inferred from list prices.

Before dispatch, the broker reserves remaining input headroom and a bounded
output allocation (at most 2,048 tokens for low/medium effort, 4,096 for high,
clipped by the unchanged 8,192-token run ceiling). It validates the actual
framework-expanded messages and schema against a conservative encoded-byte
bound. Provider retries are disabled. The workflow deadline is 600 seconds;
individual framework/model operations have finite adapter deadlines.

The kernel caps admitted inputs and final output at 48,000 UTF-8 bytes, with
closed output fields and per-field bounds. Public-source context is bounded and
explicitly marked when truncated. The normal plan/draft/verify path uses three
model calls, or five with a revision. Browser AI consumes the same allowance:
the default Stagehand extraction uses two calls, so a later revision may stop at
the six-attempt ceiling instead of accepting an incomplete review.

Select **Review plan before drafting** in the Workflow room to opt into the
supervisor loop (`supervisor: true` on `POST /api/workflows/runs`). A separate
plan reviewer must approve every criterion against admitted context before the
producer starts. Failed checks, blockers, missing criteria or a mismatched plan
hash stop the run. Final draft review can still request one revision from the
same producer. The mode is optional and defaults off: four normal model calls,
six with a revision, within the unchanged shared ceiling. Browser extraction can
leave insufficient budget for a revision; that fails closed. The mode remains
fixed across retries/resume, and `review_plan` events appear in the existing run
timeline. Accepted output remains a draft requiring owner review before use.

Acceptance rejects invalid schemas, invented evidence references, missing or
duplicated criteria, a changed candidate hash, failed checks or unresolved
blockers. It is a specified draft gate, not proof of factual truth, human approval
or publication. Input/source hashes and final output hashes prove identity and
readback. The immutable downloaded JSON wrapper has its own SHA-256/byte receipt,
distinct from the final-output hash inside its evidence. Downloads are bounded,
hash-checked, `private, no-store`, and attachment-only. Cancellation before
completion cannot expose an artifact as accepted.

## Public browser evidence and Stagehand

Twenty agency recipes require one to three supplied public HTTPS URLs.
Browserbase validates and pins public addresses and redirects, captures sanitized
source text, and renders inert snapshots with browser network access blocked.
The shared service permits one session per owner scope, at most three pages and
a 180-second session timeout. Quota must be verified before creation. Session
release is independently read back; an unknown creation/release retains the
owner reservation through its possible TTL. Restart recovers/releases known
sessions, and live browser connections are not checkpoint-resumable.

Without the fixed Stagehand extension, Browserbase uses its ordinary snapshot
renderer. With it, the actual Stagehand observe/extract APIs attach to that same
owned session and use a Gateway-admitted model callback. The default runner
extracts the first snapshot and retains validated text/screenshots for all pages.
The UUID is included as top-level Browserbase session-create `extensionId` and
cannot be selected or uploaded by a request. Provider extension metadata readback
and the pinned local archive hash are separate evidence. Neither mode exposes
live target-origin interactions, scripts, forms, logins, arbitrary code or
autonomous external actions. Browser usage/cost remains unknown when the provider
has not returned it.

Stagehand extraction is retained in planner/draft context as untrusted data, with
only a title (200 characters), summary (2,000), and at most eight claim/quote pairs
(500/1,000). Additional fields or malformed shapes fail before model drafting.
Each nonblank quotation must occur exactly within the source-text prefix that
the JavaScript renderer exposes (24,000 UTF-16 units); text fetched beyond that
prefix cannot substantiate it. SDK transport metadata is excluded. Evidence hashes
the canonical extracted JSON and rendered source-text prefix separately from the
full fetched source. The prefix digest does not claim to hash the HTML or PNG,
and a matching quotation does not itself prove the associated claim is correct.

## Gateway-only setup

The feature is opt-in. Configure server access in a gitignored regular `0600`
environment file, using values supplied privately by the operator:

```dotenv
MOMOBOT_WORKFLOWS_ENABLED=true
OPENAI_API_KEY=${OPENAI_API_KEY}
MOMOBOT_BROWSERBASE_ENABLED=true
BROWSERBASE_API_KEY=${BROWSERBASE_API_KEY}
MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT=${VERIFIED_MONTHLY_MINUTE_LIMIT}
MOMOBOT_STAGEHAND_EXTENSION_ID=${VERIFIED_STAGEHAND_EXTENSION_ID}
```

The browser settings are optional for recipes without public browser research.
The Stagehand setting is optional for ordinary snapshot capture. Install the
fixed workers from their isolated lockfiles before selecting those adapters;
see [worker setup](../../workers/browser-teams/README.md) and
[adapter boundary](WORKFLOW_ADAPTERS.md). A capability flag does not verify a
provider execution or a production installation.

The private launcher passes provider keys, feature flags and extension UUID only
to Gateway. It selects this checkout's harness source explicitly. Frontend and
Electron receive no provider credentials. Run an authenticated private state
directory through the existing launcher; the default ports remain Gateway 8040
and frontend 3040:

```sh
backend/.venv/bin/python scripts/run_momobot_openai_app.py gateway \
  --state-dir "${PRIVATE_STATE_DIR}" --env-file "${PRIVATE_ENV_FILE}"
backend/.venv/bin/python scripts/run_momobot_openai_app.py frontend \
  --state-dir "${PRIVATE_STATE_DIR}"
```

Persist the existing authenticated state and shared persistent checkpointer.
Preparing or testing a checkout does not upgrade an installed application or
move accounts. See [private app release setup](../../docs/MOMOBOT_APP_RELEASE.md)
and [Mac workbench](../../scripts/MOMO_WORKBENCH.md) for that separate lifecycle.

## Verification and bounded challengers

Offline tests execute every recipe with explicit synthetic model/browser
responses. Native integration tests cover real run/thread/event stores,
SQLite restart, usage/journal replay, abort fences and artifact visibility.
Route tests exercise actual session/CSRF middleware, RBAC and SQLite membership;
startup tests verify shared native components and shutdown ordering. Isolated
worker tests use actual framework APIs and a disposable headless Stagehand
extension. These checks establish contracts, not 120 live accepted outputs.

Run the normal offline and strict I/O targets with the virtualenv executables on
PATH so shell-based sandbox tests can find `python`:

```sh
cd backend
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH=.:packages/harness
.venv/bin/python -m pytest tests -m "not live" --ignore=tests/blocking_io -q
.venv/bin/python -m pytest tests/blocking_io -q --tb=short
```

The separate [Agno AgentOS probe](../../docs/AGNO_AGENTOS_PROBE.md) exercises real
native ASGI endpoints, private SQLite persistence/restart and JWT isolation under
one existing admitted model handoff. It is distinct from the normal individual
Agno adapter. It activates no production Control Plane, new serving platform,
distributed queue or cloud scheduler; those capabilities remain unverified.
Compare adapters on the same held-out input and verify artifacts and actual
usage, keeping unknown cost unavailable and live output/install evidence separate.
