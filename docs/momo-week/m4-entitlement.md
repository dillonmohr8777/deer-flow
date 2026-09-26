# M4 entitlement gate — design

Design only, per task `c2` in `docs/momo-week/QUEUE.md`. No code in this change.
Source of truth: `plans/momentum-backend-goal.md` (M4 row) and
`plans/momentum-enterprise-runtime-contract.md` §3 (org schema), §5 (entitlement
contract), §7.3 (entitlement gate acceptance). Written against the code as it
stands on `lane/momo-week` 2026-09-25 (M3 isolation work, board feature) — file
paths below are read from that tree, not assumed.

## 1. Scope

In scope for M4 (`e6 m4-entitlements`, implementing this doc):

- One server-side evaluator that every paid mutation route calls.
- An effective-entitlement snapshot endpoint the frontend reads instead of
  inferring capability from ad-hoc flags.
- The `organization_entitlements` table (contract §3), additive and nullable
  like every prior organization-schema step.

Out of scope (later milestones, contract §8 non-goals):

- M5 (ledger complete) — recording model-dollar spend. No `usage_ledger`
  table exists yet; `GET /api/console/usage-ledger` in
  `app/gateway/routers/console.py` synthesizes a view from `RunEventRow` +
  `RunRow` metadata. M4 does not depend on it and must not invent one.
- Milestone B (billing gate, contract §7.4) — no billing provider, webhook,
  checkout, or charge. `organization_entitlements` rows are populated by an
  operator/admin path in M4, not by a billing webhook.
- Any UI enforcement. Contract §5: "Billing status never grants permissions
  by itself... the authorization layer still evaluates the caller and
  resource." The frontend may hide a control using the snapshot, but the
  backend route is the only place capability is decided.

## 2. Data model

Add the table from contract §3, following the same additive-migration
discipline as `organizations` / `organization_members`
(`packages/harness/deerflow/persistence/organizations/model.py`) and the
board tables (`0038_board_threads`): new table, nullable/optional everywhere,
single Alembic head chained after whatever is current on `lane/momo-week`
when `e6` lands.

```python
class OrganizationEntitlementRow(Base):
    __tablename__ = "organization_entitlements"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Present only for numeric-limit keys (projects.max, workflows.max,
    # brands.max, repair_minutes.monthly). Null for boolean/gate keys
    # (console.read, runs.create, runs.cancel, agents.manage,
    # schedules.manage) where the row's existence plus `status` is the grant.
    limit_value: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(32))  # "manual" | "billing" (billing unused until milestone B)
    status: Mapped[str] = mapped_column(String(32))  # "active" | "suspended"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
```

Keys are exactly contract §5's minimum set: `console.read`, `runs.create`,
`runs.cancel`, `agents.manage`, `schedules.manage`, `projects.max`,
`workflows.max`, `brands.max`, `repair_minutes.monthly`. No `board.*` key yet
— the board is Momentum-internal-only today (gated on
`private_workspace.enabled`), not a paid customer capability; add one only
if/when the board ships to paying orgs.

**No row for a key = no grant** for gate keys, and **no configured limit** for
limit keys (evaluator treats a missing limit row as `0`, fail closed, not
"unlimited"). This makes the single-owner org's current implicit access an
explicit migration step (§4) rather than a silent default, matching how
`organizations`/`organization_members` backfill worked.

## 3. Evaluator

One function, one place, per contract §7.3 ("one shared server evaluator").
Lives beside the existing route-authorization code it composes with:
`packages/harness/deerflow/authz/` (where `AuthorizationProvider` /
`AuthzDecision` already live) plus a thin Gateway-side wrapper in
`app/gateway/authz.py` next to `Permissions` and `require_permission`, since
that is the only place route decorators are defined today (this codebase
uses decorator-stacking, not FastAPI `Depends`, for auth — see
`require_auth` / `require_permission` in `app/gateway/authz.py`).

```python
async def evaluate_entitlement(
    organization_id: str,
    key: str,
    *,
    requested_amount: int = 1,
) -> EntitlementDecision:
    """Look up organization_entitlements for (organization_id, key).

    Gate key (no limit_value): allow iff a row exists with status="active".
    Limit key (has limit_value): allow iff current_usage + requested_amount
    <= limit_value, where current_usage is read live from the owning table
    (COUNT of active client/project rows for projects.max, active workflow
    rows for workflows.max, etc.) -- never from a cached counter, mirroring
    how ClientRepository/BoardRepository always query live, org-scoped rows
    rather than trusting a denormalized count.

    Degraded provider (DB read fails after retry, or config marks the
    provider unavailable): serve the last snapshot successfully read for this
    `organization_id`, from a process-level cache keyed by `organization_id`
    (not a per-request cache -- an outage spans many requests, and a cache
    that only lived for one request could never make the grace period mean
    anything). Once `entitlements.grace_period_seconds` has elapsed since
    that cached read, fail closed for every key except the ones already
    excluded by contract §5 ("leaving export/account access available") --
    console.read stays allowed, everything else denies.
    """
```

New decorator, same shape as `require_permission`, composed the same way
`require_permission` itself is used (RBAC first, entitlement second —
contract §4's ordered checklist: authenticated → route permission → org
membership → resource org match → resource rule → entitlement). It must
run *after* `require_permission` has already populated `request.state.auth`,
not after a fresh `require_auth` -- no router in this codebase uses
`@require_auth` today, and stacking it back in would be actively wrong:
`require_auth`'s wrapper unconditionally replaces `request.state.auth` with
a bare `AuthContext(user=..., permissions=...)` built by `_authenticate()`,
which carries no `organization_id`/`organization_role` (only
`AuthMiddleware`, and `require_permission`'s own reuse-if-already-set
`_authenticate()` call, populate those fields). Putting `require_auth` above
`require_permission` in the decorator stack would wipe the org context right
before the entitlement check needed it:

```python
@router.post("/runs")
@require_permission("runs", "create")
@require_entitlement("runs.create")
async def create_run(request: Request): ...
```

`require_entitlement` reads `request.state.auth.organization_id` (already
populated by `AuthContext` — see `app/gateway/authz.py`'s
`organization_id`/`organization_role` fields) — no new context plumbing
needed. A request with no resolved organization is **denied** (403) while
entitlements are enabled, the same fail-closed default contract §4 already
requires for every other check in its list ("Failure defaults closed") --
it must not be treated as an exemption. The legacy personal boundary
(contract §2) stays unaffected only because `entitlements.enabled` stays
`false` until every personal org has been backfilled (§4).

A limit key (`projects.max`, `workflows.max`, `brands.max`) cannot be a bare
decorator, since it needs the attempted count from the request body. Those
routes call `evaluate_entitlement(...)` directly in the handler body before
the mutation, the same way `board.py` calls `_require_client_access(...)`
inline rather than through a decorator — this codebase already has that
"decorator for the common case, inline call for the parametrized case"
split.

## 4. Rollout for the single-owner org (no billing yet)

Contract §2: today's only real org is single-owner. M4 must not lock Dillon
out. Migration step order, mirroring §3's mandatory schema-gate sequence:

1. Add the table (nullable, empty). No route calls the evaluator yet —
   dead code path, same as `authorization.enabled=false` today.
2. Backfill: insert one `active` row per existing organization for every
   gate key in §5's minimum set, and a limit row for each `*.max` key set to
   whatever the current single-owner ceiling should be (Dillon's call — flag
   as a config default, e.g. `entitlements.default_limits.projects_max`, so
   it is not a magic number baked into the migration).
3. Flip `entitlements.enabled: true` in `config.yaml` (new
   `EntitlementConfig`, same shape as `AuthorizationConfig` in
   `packages/harness/deerflow/config/authorization_config.py`: `enabled`,
   `fail_closed`, `grace_period_seconds`) once the backfill is verified, the
   same two-step "add nullable, backfill, then enable" pattern used for
   `authorization.enabled` and `private_workspace.enabled`.
4. Decorate/inline-check the paid mutation routes.

An operator (Dillon) sets or edits `organization_entitlements` rows directly
(admin script or a follow-up `/api/console` admin route — not scoped here)
until milestone B's billing service becomes the writer. `source="manual"`
marks these rows so a future billing writer can tell which rows it owns.

## 5. Snapshot endpoint

`GET /api/organizations/{organization_id}/entitlements` (or
`/api/console/entitlements` alongside the existing `console.py` router,
whichever the `e6` implementer finds less disruptive to the router layout —
not a design-blocking choice). Requires `console.read` entitlement plus
active membership in that organization (contract §4's ordinary authorization
rule applies to reading entitlements too). Returns the same shape the
evaluator itself would derive, so display and enforcement can never read
different data (contract §7.3: "frontend uses the same returned effective-
entitlement snapshot for display"):

```json
{
  "organization_id": "...",
  "entitlements": {
    "console.read": {"allowed": true},
    "runs.create": {"allowed": true},
    "runs.cancel": {"allowed": true},
    "agents.manage": {"allowed": false},
    "schedules.manage": {"allowed": true},
    "projects.max": {"limit": 25, "used": 4},
    "workflows.max": {"limit": 10, "used": 1},
    "brands.max": {"limit": 3, "used": 3},
    "repair_minutes.monthly": {"limit": 60, "used": 0}
  },
  "degraded": false
}
```

`degraded: true` marks a response served from the grace-period fallback
(§3), so the UI can show a stale-data notice rather than presenting it as
current truth.

## 6. Tests (`e6`'s acceptance bar)

Per QUEUE.md e6: "tests for allowed, denied and missing entitlement on at
least 3 paid mutations." Concretely:

- `runs:create` (gate key) — active row → 2xx; `status="suspended"` row →
  403; no row at all → 403 (missing = denied, not allow-by-default); with
  entitlements enabled, a request whose `organization_id` never resolved
  (no active membership) → 403, not a silent skip.
- `agents:manage` (gate key) — same four cases.
- `projects.max` (limit key) — under limit → 2xx; at limit → 403 with a
  distinguishable error body (`entitlement_exceeded`, not a generic 403) so
  the frontend can show "upgrade" copy instead of a bare permission error;
  missing limit row → treated as limit `0` → 403.
- Degraded-provider path: force the DB lookup to raise across *multiple*
  requests (not just one call within a single request) to prove the
  process-level cache (§3), not a per-request one, is what serves the grace
  window; assert the cached snapshot is served for
  `entitlements.grace_period_seconds` after the last successful read and a
  hard 403 (except `console.read`) once that window elapses — mirrors
  contract §5's "provider outages preserve the last verified entitlement
  snapshot for a bounded... grace period, then fail closed."
- Snapshot endpoint returns the same `allowed`/`limit`/`used` values the
  route-level evaluator used in the same test run (no drift between display
  and enforcement).

Isolation regression: an org A caller must never see or move org B's
`organization_entitlements` rows — add this table to whatever isolation
sweep already covers `organizations`/`organization_members`
(`test_org_isolation_phase2.py` per the earlier survey) rather than writing
a parallel isolation suite.

## 7. Open questions for Dillon

1. Default limits for the single-owner org's `*.max` keys (step 4.2) — no
   number is proposed here; needs a product decision, not a guess baked into
   a migration.
2. Whether `console.read` should ever be deniable pre-billing, or whether
   M4 should hardcode it allowed for every active member until milestone B
   exists (contract §5 already says export/account access stays available
   during a degraded provider window, which suggests always-allow is the
   intended steady state, not just the grace-period fallback).
3. Where the admin write path for `organization_entitlements` lives before
   billing exists — a one-off script, or a minimal `/api/console` mutation
   route gated to system-admin only. Left to `e6`'s implementer once 7.1 is
   answered.
