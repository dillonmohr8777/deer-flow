# Sol Responses transport and native multi-agent preflight

This opt-in adapter does not change the configured models, scheduler, subagent
executor, queues, rooms, application database or running services. It contains
request builders, protocol parsers, a private per-cycle spending receipt journal,
and an HTTP seam. It uses existing `httpx` and Python standard libraries.

## Two independently verified capabilities

- Ordinary Sol Responses can request a developer-defined function. The synthetic
  probe forces exactly one `get_source_packet` call with a single enumerated
  `packet_id`. Its parser requires the real call and exact arguments, Sol's resolved
  model, completion, usage and cost. No function is executed or continued by the
  probe. This supports future ordinary worker integration, not hosted agents.
- Native Responses multi-agent uses the beta header and `multi_agent.enabled`.
  The parser requires a hosted successful `spawn_agent` call/output pair and a
  matching child-attributed item. Only explicit `/root` `final_answer` messages
  become `root_final`. Worker finals and root commentary remain distinct events.
  Hosted actions are never executed by the application. Encrypted agent messages
  retain author/recipient identity; the adapter cannot read their contents.

Reference contracts: [OpenAI Responses multi-agent](https://developers.openai.com/api/docs/guides/responses-multi-agent)
and [OpenRouter Responses create](https://openrouter.ai/docs/api/api-reference/responses/create-responses).
On September 29, 2026 the tested OpenRouter native route returned an upstream
beta-header rejection despite the caller sending that header. Ordinary function
serialization succeeded separately. Neither finding establishes every route or
future provider behavior. No native compatibility is assumed.

## Request and tool boundary

`build_request(prompt, instructions=..., receipt_id=..., cycle_id=...)` pins
`openai/gpt-6.1-sol`, the OpenRouter HTTPS Responses endpoint, OpenAI-only routing,
`data_collection: deny`, `allow_fallbacks: false`, and `require_parameters: true`.
Native `tools` is always empty. It sends `store: false`, no streaming, low reasoning,
at most 65,536 UTF-8 input bytes, 2,048 requested output tokens and two concurrently
active subagents. Native `max_tool_calls` is deliberately omitted because that
beta does not support it. Tool-call or unexpected output types are rejected.

`build_ordinary_tool_probe(packet_id, receipt_id=..., cycle_id=...)` omits all native
beta fields and limits requested output to 256 tokens. Its only function schema
reads the one synthetic packet. This builder is preflight only; native `Pilot`
and its spending journal do not admit ordinary probe requests. No arbitrary
function, shell, browser, network, write or client tool is admitted by either path.
Private packets require the existing coordinator's approved privacy/routing
policy; this module does not infer authorization from a prompt.

## Spending admission and limits

The provider imposes no total descendant count or tree-depth bound. The byte,
output and concurrency settings above do **not** prove a native aggregate USD cap.
`CycleJournal` refuses construction before any file write unless all are supplied:

1. Explicit approval for this one cycle, a finite positive pilot budget and a
   point-in-time account balance that preserves the operator's account reserve.
2. An independently checked native capability response ID.
3. Trusted operator evidence of an externally enforced aggregate provider ceiling
   covering every descendant turn and every continuation in the same cycle.
4. A finite request-count limit, no more than 16 explicit HTTP calls.

`BudgetProof` is an operator attestation, not an automatic verification service.
Do not populate it from agent text or public request fields. No such aggregate
OpenRouter native guarantee was verified for this work, so activation stays blocked.
A shared account balance is a snapshot; unrelated calls can change it. Local
reservations are not an account-level provider cap.

The operator chooses a private journal file (0600) in an existing private directory.
There is exactly one immutable policy per journal. SQLite `BEGIN IMMEDIATE` and
full synchronous commits serialize reservation across connections/processes.
One top-level HTTP request may be inflight at a time; provider child concurrency
is independent. A positive reservation must fit the remaining cycle/external
ceiling after prior actual cost. Continuations must name a verified response in
that same cycle and retain cumulative request/cost/usage accounting. Aggregate
provider usage is counted once per HTTP response, not again per child event;
this assumes the attested provider aggregate accounting contract.

Append-only events preserve reservation, unknown outcome, original response and
later accounting corrections. Receipt rows are a mutable state projection. The
full response items remain available for trace/replay, including hosted actions.
No provider exception text, API key, credential discovery or logging is added.

## Dispatch and recovery

Construct `CycleJournal` and `OpenRouterTransport` off the event loop. The async
`Pilot.submit` builds internally, commits admission with `asyncio.to_thread`, then
performs exactly one HTTP attempt. The transport has zero retries and does not
follow redirects. It accepts a caller-supplied credential; it does not load, persist
or create one. A response must prove protocol capability and explicit usage/cost.
`ParsedResponse.accepted` denotes protocol/accounting acceptance only, not semantic
artifact acceptance or permission to publish.

Timeouts, cancellation, non-2xx/malformed outcomes or crashes retain a reserved
inflight/unknown receipt and block further calls. Recover by retrieving the actual
response through an independently authorized read path and calling
`journal.recover(receipt_id, response)`; recovery never calls the provider. Do not
retry, switch models, reset the journal or release unknown reservations by assumption.
Previously unknown accounting can be filled without changing the result/identity.
Settled payloads and response-ID ownership cannot be reassigned. Known reservation
overruns and protocol failures stop the cycle. Unknown cost/usage stays `None`;
`known_cost_usd` is only the known subtotal, never a fabricated complete total.

## Existing coordinator integration acceptance

The existing scheduler/batches/coordinator retain ordering and artifact ownership.
The adapter starts no workers and creates no competing task or client queue.
Before enabling a route, the operator/reviewer must verify:

- Exact provider/model transport and real typed capability receipt; successful
  ordinary tool calling does not satisfy native hosted capability.
- Independently verified spend/usage semantics and explicit approved cycle budget.
- Real agent/item/call IDs and phases map to room events through an attributed
  coordinator relay; do not claim workers posted directly.
- Coordinator persistence and read-back bind actual artifact/source hashes and
  runtime IDs to the existing work order, followed by independent semantic review.
- Privacy/tool policies remain authoritative; no function execution, client writes,
  hiring/provisioning, deployment or recurring sweeps are implied by this adapter.

Offline tests cover protocol negatives, exact function schemas, request tampering,
atomic admission, crash/cancellation/unknown recovery, immutable accounting,
cumulative continuations, external ceilings and the async blocking-I/O boundary.
Live provider calls remain separately authorized and are not part of the suite.
