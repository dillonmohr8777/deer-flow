# MomoBot managed OpenAI agent app

This opt-in Gateway surface uses the current released Python `openai==3.22.1`
SDK and its `client.beta.agents` namespace. It adds a durable session/ownership
adapter for the mobile web app and desktop wrapper. Existing client registries,
work orders, LangGraph queues and canonical client documents stay authoritative.
It is a new execution choice, not a replacement business database.

## Runtime and access

`OPENAI_API_KEY` remains server-side. `MOMOBOT_OPENAI_AGENTS_ENABLED=true` is
required before paid requests are admitted. Status reads disclose only key
presence, SDK version and configuration readiness. `available=true` does not
claim account access or a successfully completed live task. New API credentials
are never created by the service. This change has been tested offline; live
project/model access and useful output remain to be verified separately.

The server pins `gpt-6.1-sol`, low reasoning and the default service tier. Each
session uses a small OpenAI-hosted sandbox, three concurrent subagents, no
application/MCP/browser tools and **disabled outbound sandbox networking**.
The model can work with user input and create isolated workspace artifacts.
It cannot reach local MomoBot files, client systems or caller credentials.

Hosted browser, website approvals and authentication are explicitly unavailable.
The browser-approval route checks ownership then returns 409. OpenAI's origin
consent does not enforce consent before each consequential browser action, so
browser access must stay disabled until resource restrictions/action policy are
implemented and independently reviewed. A prompt is not the enforcement boundary.

## Authentication and ownership

The router runs under the existing fail-closed `AuthMiddleware`, organization
membership resolution, permission decorators and CSRF middleware. Reads require
`runs:read`, create/input requires `runs:create`, cancel requires `runs:cancel`.
PATs remain subject to the existing default-deny route allowlist; this module
does not expand it. Anonymous/inactive-member requests do not bypass middleware.

Provider session IDs are never accepted from the caller. Each API-visible local
UUID is durably mapped to a provider session. Its owner scope hashes the server
verified actor, active organization and storage principal. Another user in the
same shared workspace cannot read or control it. Every read, artifact download,
input and cancel checks this mapping before making a provider call; another
scope gets 404. Requests forbid extra fields, preventing model/tool/owner and
environment injection.

SQLite is a private 0600 file under the configured `get_paths().base_dir`:
`openai-agents.sqlite`. Disk operations run off the event loop. The database
stores ownership, provider mappings, hashes and finite admission receipts; it
does not store submitted prompts, credentials or a duplicate conversation.
Append-only events retain admission/outcome history. Mutable rows are projections.

## API contract

`GET /api/openai-agents/status` returns `configured`, `sdk_version`, `available`,
`model`, `max_concurrent_subagents`, `browser_available`, `reason`,
`turn_timeout_seconds`, `max_active_sessions`, `max_owner_admissions_24h` and
`cost_usd: null`. `reason` is configuration status,
not the outcome of a live access test.

`GET /sessions` returns `{data: SessionSummary[]}`. Summary fields are local
`id`, `title`, `status`, ISO UTC `created_at`/`updated_at`, and a fixed safe
`last_error` code or null. No raw provider exception/body/headers are returned.

`POST /sessions` takes `{input: string, title?: string}` and requires an
`Idempotency-Key` header. Messages are nonempty, at most 16000 characters and
65536 UTF-8 bytes; titles are at most 120 characters. The result is a detail view.

`GET /sessions/{id}` returns the summary plus:

- `turn: {id, status, output_verified} | null`: latest **root** turn;
- `items: {id,type,turn_id,subagent_id,agent_id,sender_agent_id,recipient_agent_id,phase,role,text,status}[]`;
- `artifacts: {id,path,turn_id,content_url}[]`;
- `required_actions: {type,available:false}[]` for unsupported input requests;
- `usage: {input_tokens,output_tokens} | null` from actual provider records;
- `operation_pending` and `history_truncated` booleans.

`output_verified` is a compatibility field name: it means a completed root turn
has a nonempty persisted final-answer message. It is **output presence**, not
independent semantic validation or proof every tool succeeded. The UI should say
“Final output retrieved”. Idle, transport 200/202, closed streams or child turn
completion must not be displayed as task success. Missing usage/cost is unknown.
The final root message must have `phase=final_answer`; commentary does not count.
Delegation requests (`create_subagent_call`) identify the requesting `agent_id`;
`agent_message` records preserve actual sender/recipient IDs and text. These are
delegation exchanges rather than final user-facing answers. A derived `subagent_id`
uses an explicit child ID or a non-root sender/recipient; root creation requests
never invent a child identity.

`POST /sessions/{id}/messages` takes `{input}` with `Idempotency-Key` and returns
detail. `POST /sessions/{id}/cancel` returns detail; 202 acceptance is not a
cancelled turn. An unobserved pending admission returns 409 rather than claiming
it stopped. `POST /sessions/{id}/browser-approval` is unavailable.

`GET /sessions/{id}/artifacts/{artifact_id}/content` checks ownership and provider
artifact metadata, enforces 20 MiB before reading, then enforces the same limit
during SDK streaming even if metadata is inaccurate. The body is an attachment
with `application/octet-stream`, `nosniff`, and private/no-store cache headers.
Generated HTML must never execute under the app origin.

## Admission, recovery and lifecycle

SQLite `BEGIN IMMEDIATE` serializes admission across Gateway processes. There
are at most three active sessions per owner and sixteen new initial/follow-up
admissions per owner in a rolling 24-hour window. Idle/terminal history does not
consume an active slot; uncertain creation, pending operations and required actions
do. The owner includes actor, organization and storage identity. Unknown paid
admissions count; known-key retries are reads and cancellation is exempt from the
admission budget. A session also permits at most sixteen follow-up admissions.
These finite counts are not a provider dollar ceiling. Identical create keys reuse a mapping; different payloads
with the same key conflict. One outstanding input/control operation blocks another.
The SDK has `max_retries=0`; uncertain dispatched work is never automatically sent
again. Repeating a known input key is a read even while its turn is active.

Creation persists admission before remote work. If a known remote session cannot
be bound locally, the service attempts remote deletion before reporting failure.
If creation loses its response, the record stays unknown. Recovery searches a
bounded provider session listing for the exact server-generated local ID and
owner-scope metadata; a non-unique/truncated search never binds by assumption.
No match does not prove the task did not run.

Detail retrieval loads persisted root items, turns and artifact metadata, with
SDK pagination capped at ten pages per collection. It reports truncation. New
root turn identity reconciles a pending message; a root terminal outcome reconciles
cancel. Provider retrieval failure returns a safe error instead of inventing a
completed result. Remote execution continues while phone/desktop observers
disconnect; GET reconciles actual saved state without resending input.

The service owns one cached async SDK client. Gateway lifecycle calls
`await service.start()` and `await service.aclose()`. Creation also starts the
watchdog when runtime configuration is available. A persisted 120-second deadline
is reset at initial/follow-up admission. The five-second watcher first reconciles
expired unknown creations using exact owner/session metadata, then atomically claims
expired deadlines with a 60-second lease. After crash, cancellation uncertainty or
lease expiry it replays the same deterministic provider idempotency key, never a
new paid input. Claimed/cancel-requested deadlines fence new messages until actual
terminal root read-back; an HTTP receipt cannot release that fence. Existing
three-column deadline databases gain a nullable lease column transactionally, and
legacy claims without a lease are reclaimable. Its state survives service restart.
See [lifecycle evidence](../../docs/MOMOBOT_OPENAI_LIFECYCLE.md).
It is a **best-effort cancellation deadline**, not a guaranteed
provider token or dollar ceiling: uncertain cancellation, unknown session creation,
network outage or stopped Gateway can delay enforcement. Do not claim a fixed
spend cap from concurrency, requested output or this watcher. The public Agents
session contract has no per-turn `max_output_tokens`/budget field. A provider-side
project spend limit must be independently verified for production activation.

Closing the SDK client does not delete remote sessions or stop remote turns.
No user artifacts or sessions are silently deleted during normal shutdown.
Deletion/archival and per-project budgeting are separate reviewed additions.

## Validation

Offline tests exercise real production code: durable owner isolation/restart,
idempotent admission, changed-payload conflicts, atomic competing submissions,
unknown outcomes, request cancellation, root-vs-child completion, missing output,
error redaction, cleanup after bind failure, deadline persistence, route permissions,
actor/workspace separation, rejected extra fields, and bounded streamed downloads.
The SDK contract test uses released 3.22.1 classes with an HTTP transport double;
it checks actual beta-header/request serialization and streamed artifact bytes.
It performs no DNS/provider requests and uses no real credential.

Run from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_openai_agents_service.py tests/test_openai_agents_routes.py tests/test_openai_agents_sdk.py tests/blocking_io/test_openai_agent_storage.py -q
.venv/bin/ruff check app/gateway/openai_agent_service.py app/gateway/routers/openai_agents.py tests/test_openai_agents_service.py tests/test_openai_agents_routes.py tests/test_openai_agents_sdk.py
```

## Official contracts

- [Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview)
- [Quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart)
- [Events and persisted history](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)
- [Hosted sandboxes and network restrictions](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted)
- [Hosted browser consent limitations](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use)
- [Released Python SDK](https://github.com/openai/openai-python/tree/v3.22.1)
- [SDK sessions resource](https://github.com/openai/openai-python/blob/v3.22.1/src/openai/resources/beta/agents/sessions/sessions.py)
- [SDK create parameters](https://github.com/openai/openai-python/blob/v3.22.1/src/openai/types/beta/agents/session_create_params.py)
# Expected workspace handshake

The authenticated UI sends `X-Expected-User-Id` with `GET /api/openai-agents/status`.
The gateway verifies the current actor before returning `owner_scope`, a SHA-256
digest of actor, organization, and storage principal. Every session list, read,
admission, cancel, browser-policy read, and artifact request then carries
`X-Expected-Agent-Scope`. A changed cookie or workspace returns HTTP 409
`workspace_scope_changed` before session storage or provider access. A correctly
scoped request for another actor's local session still returns 404.

UI query keys include actor and returned scope. Scope changes clear draft and
selection; stale mutation callbacks cannot publish results or hand off downloads.
Artifact requests are authenticated, bounded binary downloads through the configured
gateway origin with the same scope header, rather than unscoped provider links.
Unknown and action-required sessions keep submission paused. Automatic recovery
polling is capped at 48 reads per query; the user can refresh for another check.
