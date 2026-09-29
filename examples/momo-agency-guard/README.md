# Bounded private agency guard

This is an opt-in, standard-library OpenRouter Chat Completions proxy and read-only
artifact hash broker for one private MomoBot cycle. Importing or testing it changes
no running service. It is separate from a Responses/native multi-agent adapter.

The fixed private route is `openai/gpt-6-luna`; the guard refuses Sol, Muse,
fallback model lists, paid plugins, hosted tools, image/file/audio payloads and
unknown request fields. Only whitelisted client-executed function tools are
accepted. Text input admission includes UTF-8 bytes plus conservative framing;
that estimate is **not** the monetary guarantee.

Before each dispatched request the guard reads fresh actual `/credits` and model
catalog data, enforces provider price ceilings, and reserves the **entire
documented model context** at the highest catalog prompt/cache-write and
long-context rates, plus the capped 2,000 output tokens. The current Luna catalog
therefore reserves $0.264 per in-flight call. Only verified explicit `usage.cost`
from the exact resolved model releases unused reservation. There is no assumption
of free cache or zero cost when usage is missing.

The append-only, fsynced, locked receipt ledger enforces $1 total settled plus
uncertain plus in-flight reservation, at most two in-flight requests and sixteen
total dispatches. The guard preserves at least $8 fresh account credit after its
own outstanding reservations. Shared account spending outside this guard remains
outside its control: existing calls can consume credit after a balance read.
Restarted in-flight reservations, corrupt ledgers, transport errors, missing
usage or unverified model stop future calls without blind retry. A provider charge
above its catalog reservation also stops and remains visible; the guard cannot
undo an upstream billing violation.

Streaming responses are buffered within a 4 MB limit until final usage and
`[DONE]` are verified, then returned as SSE. This adds end-of-completion latency;
the 300-second upstream timeout is shorter than current private worker 600-second
timeouts. Cancellation/timeout outcomes remain uncertain rather than being
retried. A stopped guard returns a payload-free reason and `retry:false`.

## Routing and key boundary

Bind only loopback in the **same network namespace as the new private workers**.
The default is `127.0.0.1:2042`; do not expose it publicly. Add a new model alias
whose `base_url` is `http://127.0.0.1:2042/v1`; copy private drafting/review roles
onto that alias without changing preexisting routes. Their tools remain empty.
The coordinator has file read/write only, no MCP integrations, and allows only
these guarded children. Actual model-factory/child route readback and a bounded
tool canary are required before calling the loop integrated.

`OPENROUTER_API_KEY` is the existing client token. Optionally
`MOMO_GUARD_UPSTREAM_API_KEY` supplies an already authorized existing full-access
key solely to this process for upstream calls and balance read permission. No
new provider key is created. Keys are never saved to receipts or logs. If these
variables are absent or the credits API refuses access, activation stops.

**Only calls configured through this guard are protected.** This example does
not remove gateway credentials, constrain all sandbox network egress or protect
preexisting models/schedules. Do not claim whole-gateway/account containment.
New private workers have no tools/MCP/children to issue a direct HTTP request;
verify their runtime policy and fixed guarded model resolution after load.

## Artifact readback

`hash_artifact(root, cycle_id, work_order_id, filename, source_sha256)` reads only
the fixed cycle/order relative path. It opens each component with directory file
descriptors and `O_NOFOLLOW`, refuses nonregular/oversized/changed files, and
returns exact artifact SHA-256 plus the operator's approved source binding.
It exports no body, writes nothing and evaluates no acceptance. The coordinator
must persist immutable producer bytes first, obtain this receipt, provide those
bytes/hash to the independent reviewer, then obtain another readback before
acceptance. A reviewer must match the exact artifact hash and criterion IDs.

## Offline verification and opt-in launch

```sh
python3 examples/momo-agency-guard/test_guard.py
ruff check examples/momo-agency-guard
ruff format --check examples/momo-agency-guard
```

Tests cover whole-context/cache pricing, unsupported modality and paid fields,
token/output limits, concurrency/replay, restart/unknown cost, sixteen-call cap,
actual cost, corrupt model/NaN/missing usage, SSE completion and hash/symlink
binding. They invoke no provider and use temporary local receipts only.

An authorized one-cycle installation can explicitly launch:

```sh
python3 examples/momo-agency-guard/guard.py --serve \
  --cycle-id APPROVED-CYCLE-ID --ledger /PRIVATE/receipts.jsonl
```

There is no recurring daemon installer, no schedule creation and no automatic
activation. Keep original mounted config bytes/digest for rollback; remove only
the new alias/roles after its native cycle settles, leaving receipts and output
artifacts intact. Any uncertain dispatch must remain held for reconciliation.

Primary API contracts: [usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting),
[actual account credits](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits),
and [provider price/parameter restrictions](https://openrouter.ai/docs/guides/routing/provider-selection).

The allowlist also recognizes the opt-in `approved_agency_phase` schema. This
only permits its compact function metadata through the guard; that tool remains
operator-disabled without its pinned manifest and checks actual native parent
ownership, private roles and guarded alias. Input/output/budget ceilings and
routed-call-only limitations remain unchanged.
