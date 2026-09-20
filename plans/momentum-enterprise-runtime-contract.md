# Momentum enterprise runtime contract

Status: staged architecture; not deployed, sold, billed, or permission-granting
Scope: tenant identity, authorization, entitlements, billing truth, and control ownership for Momentum Command Center

## 1. Current verified boundary

- The authenticated `user_id` is the current data boundary for projects, threads, runs, schedules, artifacts, agents, and console queries.
- Gateway route permissions and resource-owner checks are enforcement. Frontend permission checks are advisory only.
- `workspace_id` identifies an external IM workspace/channel connection. It is not a SaaS tenant identifier and must not be reused as one.
- Model pricing in `config.yaml` estimates provider cost. It is not a customer invoice, subscription, balance, revenue, or margin record.
- Command Center is an account-scoped read/observe surface. Its only direct mutation is the existing permission-gated run cancellation path.

## 2. Launch decision

The first staged Momentum account remains a single-user account using the existing `user_id` boundary. Do not add a fake tenant selector or infer shared access from projects, Slack workspaces, client names, email domains, or agent definitions.

Shared team access requires the organization layer below. Until that layer and its isolation tests ship, “Client Spaces” means user-owned project organization, not tenant isolation.

## 3. Organization identity contract

When team access is approved, add these server-owned records:

| Record | Required fields | Invariant |
| --- | --- | --- |
| `organizations` | `id`, `slug`, `name`, `status`, timestamps | Stable tenant identity; slug is display/routing only. |
| `organization_members` | `organization_id`, `user_id`, `role`, `status`, timestamps | Unique active membership per organization/user. |
| `organization_delegations` | `organization_id`, subject type/id, owner user id, scopes, status, expiry, timestamps | Server-created authority for an internal subject to act for one member; raw owner headers are insufficient. |
| `billing_accounts` | `organization_id`, provider, provider customer reference, currency, status | One active billing owner per organization; provider references never come from the browser. |
| `billing_subscriptions` | `organization_id`, plan id, provider subscription reference, status, period end, timestamps | Webhook-backed state; idempotent by provider event id. |
| `billing_events` | provider, event id, subscription reference, event type, received/effective timestamps, processing status, payload SHA-256 | Unique `(provider, event_id)` ledger; immutable receipt for replay and ordering decisions. |
| `organization_entitlements` | `organization_id`, key, limit, source, status, timestamps | Server-evaluated capability/limit; UI may display but never enforce alone. |

Every user-owned resource that can be shared must gain a server-owned `organization_id`: projects, project documents, threads, runs, scheduled tasks/runs, user-owned custom agents, subagent batches, channel connections, durable MCP tasks, feedback, channel conversations, and pending channel OAuth states. Personal users receive a private organization during migration; existing rows backfill to that organization without changing their `user_id` audit owner.

MCP tasks and feedback are stamped from their owned thread/run organization and must match that parent on every write. Channel conversations inherit and retain the organization of their owning channel connection. Pending OAuth state is created with the authenticated organization and may complete only into a connection for that same organization. Backfill derives each child from its verified parent; orphaned or conflicting rows are quarantined rather than guessed. Cross-organization parent/child attachment is rejected.

The deployment-global managed-subagent catalog remains global and system-admin-only in the first organization implementation; it is not customer-owned and receives no `organization_id`. Organization-visible agent counts and controls cover user-owned custom agents only. Making managed subagents organization-owned is a separate architecture change with its own authorization and migration review.

Migration order is mandatory: add nullable columns and tables; dual-write `user_id` plus server-resolved `organization_id`; verify complete backfill; enable organization-scoped reads and writes; add parent/child organization-consistency constraints; enforce non-null organization ownership where the resource is never shared/legacy; only then enable team mode. A partial migration continues using the existing `user_id` boundary and cannot expose shared access.

The active organization is resolved from an authenticated membership and a server-issued session/token claim. A raw header, route parameter, email domain, project id, channel workspace id, or client-supplied metadata must never establish membership.

## 4. Authorization rule

Access requires all applicable checks:

1. authenticated principal;
2. effective route permission;
3. active organization membership;
4. matching resource `organization_id`;
5. resource-specific ownership/role rule; and
6. entitlement or limit when the action consumes a paid capability.

Failure defaults closed. Cross-organization resource probes return not-found semantics. Trusted internal callers may act for an explicitly resolved owner, but their internal token or owner header must not bypass organization membership.

Direct internal callers do not become organization members. Before organization-scoped reads are enabled, each channel, scheduler, or other internal subject must resolve through a durable active `organization_delegation` tied to its authenticated subject/credential and real owner user. The owner must still have active membership, the delegation must cover the requested scope and organization, and revoking either invalidates access. An internal token plus an `X-DeerFlow-Owner-User-Id` value is never sufficient by itself.

Existing personal access remains compatible during migration: the user’s private organization and audit `user_id` both match. Do not remove existing `user_id` filters until organization filters and dual-boundary tests are live.

Initial organization mode permits one active `owner` membership only. Additional members or roles stay disabled until an approved role-permission matrix covers route permissions, billing administration, membership changes, resource transfer, and emergency suspension, with deny-by-default tests for every role.

## 5. Entitlement contract

Entitlements describe capabilities, not marketing copy. Minimum keys:

| Key | Meaning |
| --- | --- |
| `console.read` | View organization-scoped operational records. |
| `runs.create` / `runs.cancel` | Create or stop runs, still subject to route permissions. |
| `agents.manage` | Change managed agent definitions. |
| `schedules.manage` | Create, edit, pause, or run schedules. |
| `projects.max` | Maximum active client/project spaces. |
| `workflows.max` | Maximum monitored workflows. |
| `brands.max` | Maximum separately isolated brand scopes. |
| `repair_minutes.monthly` | Human-approved simple-fix allowance; never authorizes autonomous external writes. |

The other session’s `$49 / $99 / $199` Watch, Protect, and Assist offers remain `proposed_not_sent_or_billed`. They are existing-client service add-ons, not validated SaaS SKUs. If adopted, map them to entitlement rows only after plan scope, overage behavior, tax/currency, cancellation, and support obligations are approved.

Billing status never grants permissions by itself. It selects an entitlement set; the authorization layer still evaluates the caller and resource. Provider outages preserve the last verified entitlement snapshot for a bounded operator-defined grace period, then fail closed for paid mutations while leaving export/account access available.

One billing service/repository is the sole writer for billing subscriptions and derived entitlements. Signed provider webhooks and audited operator commands are inputs to that service, never independent writers. Provider-signed subscription events own subscription truth; an operator may suspend service or create a separate time-bounded manual entitlement, but cannot rewrite provider history. A restrictive suspension wins over an allowance.

Each provider event is inserted into `billing_events` before processing. A duplicate `(provider, event_id)` is compared atomically: a matching payload hash is an idempotent no-op; a mismatched hash is quarantined and flagged, and cannot mutate subscription or entitlement state. For one subscription, a newer provider `effective_at` supersedes an older event; an older late arrival is retained and marked superseded without changing current state. Equal effective times use the provider's monotonic sequence when available, otherwise the existing applied event remains authoritative and the conflict is flagged for review. Payload hashes prove replay identity without treating receipt time as business order.

## 6. One mutation owner

| Domain | Authoritative mutation path | Command Center role |
| --- | --- | --- |
| Runs | Existing thread/run Gateway routes | Observe; cancel only through the existing guarded route. |
| User-owned custom agents | Existing Agent workspace routes | Inspect and link. |
| Deployment-global managed subagents | Existing system-admin managed-subagent routes | Label as platform catalog; never present as organization-owned. |
| Schedules | Existing Scheduled Tasks routes | Inspect and link. |
| Projects/artifacts | Existing project, thread, and document routes | Inspect and link. |
| Skills/MCP/integrations | Existing Capability Center routes | Inspect and link. |
| Billing/entitlements | One future billing service/repository; webhooks and operator commands are inputs | Display verified state only; no inferred revenue or balance. |

Do not add duplicate create/edit toggles to Command Center. It remains the unified observability shell over those owners.

## 7. Required delivery gates

1. **Schema gate:** nullable organization/member/resource fields, dual-write, verified private-organization backfill, organization-scoped reads/writes, parent/child consistency constraints, then non-null enforcement and team enablement; every step has a rollback path.
2. **Isolation gate:** repository and API tests prove organization A cannot list, read, attach, mutate, cancel, stream, or download organization B resources; membership/delegation revocation and organization switching invalidate stale access.
3. **Entitlement gate:** one shared server evaluator protects every paid mutation; frontend uses the same returned effective-entitlement snapshot for display.
4. **Billing gate:** one writer service/repository plus a selected provider adapter; webhook signature verification, durable event ledger, matching-hash idempotency, mismatched-hash quarantine, out-of-order precedence, replay tests, and subscription readback pass. No checkout or charge before explicit approval.
5. **Control gate:** every Command Center action resolves to one authoritative mutation route; duplicate paths are removed or remain read-only links.
6. **Docker gate:** migration backup/restore rehearsal, Gateway readiness, authenticated browser flow, one read-only job, and one permitted mutation receipt pass before rollout.

Minimum isolation checks include personal-account compatibility, PAT scope narrowing, internal delegation plus owner membership, missing/null legacy owner rows, cross-organization attachment refusal, project/thread/run/artifact coverage, durable MCP tasks, feedback, channel conversations/OAuth state, schedules, user-owned custom agents, global managed-subagent admin isolation, subagent batches, membership/delegation revocation, organization switching, matching- and mismatched-hash billing replays, event reordering, and degraded-provider behavior.

## 8. Explicit non-goals for this stage

- No billing provider installation, checkout, charge, invoice, or customer communication.
- No organization database migration until the shared-account decision and migration window are approved.
- No replacement of existing owner checks, permissions, projects, or control surfaces.
- No claim that the five `$595/month` pilots are booked revenue or that provider cost equals margin.
