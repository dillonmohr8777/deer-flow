# M3 isolation gate: status (a1 audit)

Audited 2026-09-24 against `lane/momo-week` (branch `momo-week/a1-m3-audit`), reading
`plans/momentum-m3-isolation-plan.md` §3 (gaps to gate 7.2) and §4 (lanes). Method: for
each gap item, grep the code path the plan names and match it to a passing test. No code
changed in this run — this is the audit the queue's a1 task asks for.

## Headline finding

The plan's own "Gaps to gate 7.2" list (§3, items 1-7) is **already closed** on this
branch. The isolation work the plan scoped as 33-56h across lanes 0/A-F landed before
`lane/momo-week` was cut (earliest at commit `67a49e09` "feat(auth): internal callers act
only through an organization delegation", well back in this branch's history) and has
since grown two lanes beyond the plan's own scope (`G` memory/disk, `H` clients) plus
dedicated PAT, MCP-config and channel-integration isolation suites. `docs/momo-week/QUEUE.md`
predates this discovery; a2 (implement the gaps) has no remaining gap-7.2 work to do as
scoped — see "What's left" below for what a2 should become instead.

## Gap-by-gap (plan §3)

| # | Gap (plan wording) | Status | Evidence |
|---|---|---|---|
| 1 | `organization_id == active org` beside every user filter (13 tables, console SQL) | **Closed** | 14 persistence modules filter by `resolve_organization_id()`/`organization_id ==`: `agents`, `audit_events`, `channel_connections`, `clients`, `feedback`, `fleet`, `mcp_tasks`, `personal_access_tokens`, `projects`, `run`, `scheduled_task_runs`, `scheduled_tasks`, `subagent_batches`, `thread_meta` (`packages/harness/deerflow/persistence/*/sql.py`). Console SQL: `app/gateway/routers/console.py:169-170`. Test: `test_org_isolation_c_schedules.py::test_repository_adds_the_organization_filter_beside_the_user_filter` and the cross-org 404 probes in every lane file below. |
| 2 | Delegation for internal callers (status/expiry/scope/owner active membership; grant/revoke; scopes narrowed like PATs); reject header-only calls | **Closed** | `app/gateway/internal_auth.py` — owner header alone is documented and enforced as insufficient (`get_trusted_internal_owner_user_id`, lines 30-90: only a request whose delegation was verified carries `state.delegation_id`). `deerflow.persistence.organizations.delegation.OrganizationDelegationRepository` implements grant/revoke/scope narrowing. Tests: `test_organization_delegations.py` (11 tests: missing/revoked/expired/out-of-scope denial, membership/org death cascades, one-active-delegation-per-subject, SSE re-check), `test_org_isolation_phase2.py::test_internal_calls_are_admitted_only_through_a_matching_active_delegation` and `::test_resolve_delegation_by_id_applies_every_check`. |
| 3 | Ownerless/no-row threads fail closed (except upload-before-create and PUT goal) | **Closed** | `test_org_isolation_b_threads.py::test_ownerless_and_orphan_threads_fail_closed_for_everyone`, parametrized across 40+ thread/run/artifact/upload routes including the goal and checkpoint-mutating ones the plan's review amendments called out (F2 raised to High). `test_org_isolation_phase2.py::test_admin_lists_ownerless_and_orphan_thread_ids_read_only` covers the admin claim-listing carve-out. |
| 4 | Writes: server-resolved org wins, parent must match (stateless runs, feedback, shared-workspace schedules) | **Closed** | `test_organization_isolation_core.py::test_organization_for_write_returns_the_server_resolved_organization` and `::test_organization_for_write_refuses_any_mismatch_as_not_found` (parametrized on parent/context/actor combos). `test_stateless_runs_owner_isolation.py` (8 tests) and `test_org_isolation_f_mcp_feedback.py` cover the named write paths. |
| 5 | OAuth completion bound to state's org; conversation attach checks thread; document restore re-derives org | **Closed** | `test_org_isolation_e_channels.py::test_connect_code_completes_only_into_the_organization_it_was_created_in`, `::test_channel_conversation_cannot_point_at_another_owners_or_organizations_thread`; `test_org_isolation_integrations.py::test_lark_oauth_completion_denies_cross_organization_generation`; `test_org_isolation_a_projects.py::test_restore_rederives_and_stamps_the_target_projects_organization`. |
| 6 | Re-backfill NULL rows since 0027; backfill delegations | **Closed** | Migrations `0031_org_rebackfill` and `0032_org_delegation_backfill` exist and are tested: `test_migration_0031_org_rebackfill.py` (chains to single head; stamps verified rows without creating identities; round-trips), `test_migration_0032_org_delegation_backfill.py` (same, for delegation grants). |
| 7 | Test matrix (plan noted only `test_owner_isolation.py` covered 4 resources at write time) | **Closed, and then some** | 254 org-isolation-relevant tests collected across `test_org_isolation_{a,b,c,d,e,f,g,h}.py`, `test_org_isolation_phase2.py`, `test_org_isolation_{pats,mcp_config,integrations}.py`, `test_organization_{delegations,dual_write,isolation_core}.py`, `test_owner_isolation.py`, `test_stateless_runs_owner_isolation.py`, `test_shared_workspace_{context,membership}.py`, `test_migration_003{1,2}_*.py`. Lanes `G` (memory/disk) and `H` (clients) go beyond the plan's original A-F scope. |

## Review amendments (plan §7, Astra) — spot check

- **Deploy order / merge deploys 2+3**: moot for this audit — header-only rejection is
  already the only code path (no feature flag gating it separately), so there is no
  "filtering ships before rejection" ordering risk left to police.
- **F2 raised to High (destructive ops on ownerless threads)**: closed — see gap 3 above;
  the parametrized route list includes PATCH/DELETE/PUT, not just GET.
- **F4 narrowed (invitees get workspace admin, not global admin)** and **invitation freeze
  covers acceptance**: closed — `test_org_isolation_phase2.py::test_invitations_are_frozen_by_default_for_creation_and_acceptance`.
- **Orphan-claiming paths (PUT goal, caller-chosen thread IDs, checkpoint seeding)**: PUT
  goal is in the ownerless-fail-closed parametrization (gap 3). Caller-chosen thread IDs:
  `app/gateway/routers/threads.py:900-906` raises `ThreadOwnershipConflictError` → 404
  without revealing the id belongs to another owner (code-verified this run; no dedicated
  regression test found under this name — worth a follow-up test, not a gap in behavior).
- **Memory and disk (lane G)**: closed — `test_org_isolation_g_memory.py` (10 tests)
  covers shared-fallback unreachability under strict scope and internal-header
  impersonation denial.
- **SSE revocation (open streams re-check membership)**: closed —
  `test_organization_delegations.py::test_membership_recheck_for_open_streams`.

## Suite run

Command: `cd backend && make test` (`pytest -m "not live" --ignore=tests/blocking_io tests/`).
Result: **1 failed, 19046 passed, 182 skipped, 20 deselected** in 886s.

```
FAILED tests/test_client_langfuse_metadata.py::test_stream_abandoned_generator_cleanup_stays_inside_trace_binding
1 failed, 19046 passed, 182 skipped, 20 deselected, 58 warnings in 886.24s (0:14:46)
```

The one failure is unrelated to M3/org-isolation: this run made zero code changes (docs
only), and re-running that single test in isolation reproduces the same
`AssertionError: assert None == '<trace_id>'` in `test_client_langfuse_metadata.py`
(Langfuse trace-binding cleanup on an abandoned generator) — a pre-existing issue on
`lane/momo-week`'s baseline, not something this audit touched. Every isolation-relevant
test named in the gap table above passed.

## What's left (for whoever picks up `a2` next)

Gate 7.2 as scoped in the plan is closed. Two smaller items surfaced during this audit,
neither of which is a gap-7.2 item:

1. Add a direct regression test for the caller-chosen-thread-id 404 path
   (`app/gateway/routers/threads.py:900-906`) — behavior is correct but undertested by name.
2. `backend/AGENTS.md` has no mention of the organization-delegation model or the M3 lanes
   despite the code and ~250 tests existing; a short section pointing at
   `plans/momentum-m3-isolation-plan.md` and `tests/org_isolation_fixtures.py` would save
   the next reader from re-deriving this audit.

Recommend `docs/momo-week/QUEUE.md` mark `a1` done and drop `a2` (nothing left to
implement against this plan) rather than carry it forward as-is.
