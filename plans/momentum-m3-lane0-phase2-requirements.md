# Lane 0 phase 2 requirements (collected from M3 lanes)

## From lane G (memory)
- auth_middleware.py:185-269 stamps X-DeerFlow-Owner-User-Id as storage_user_id for any valid internal token with no delegation or membership check (F1). Test: backend/tests/test_org_isolation_g_memory.py xfail(strict). Remove the marker when header-only calls require a delegation.
- Note: outsider or revoked member selecting shared workspace S gets 403 from AuthMiddleware (membership gate). Contract prefers not-found semantics for cross-org probes; decide whether the membership gate should answer 404.

## From lane D (agents)
- None for services.py. DEPLOY CHECK: GitHub dispatch now fails closed without a delegation (scope runs:create). Before deploying M3, confirm GitHub dispatch is unused on live, or add a grant flow.

## From lane E (channels)
1. internal_auth.create_internal_auth_headers gains a delegation_id kwarg emitted as X-DeerFlow-Delegation-Id; OrganizationDelegationRepository gains lookup by delegation id. Then wire channels attach_connection_identity and _owner_headers.
2. Define the channel worker delegation scopes and grant on connect; otherwise channels are refused once header-only calls are rejected.
3. Optional (Dillon): add /api/channels to _WORKSPACE_AUTH_EXEMPT_PREFIXES so channels are manageable from shared workspace S (would flip lane E's S test cases). Default: no (channels stay personal).
4. Latent: channel tasks spawned during a request inherit that request's ContextVar identity. Make background channel tasks run with an explicit identity, not the inherited one.

## From lane C (schedules)
1. services.py launch_scheduled_thread_run accepts `delegation`, sets state.organization_id, storage_user_id and actor_user_id from it, sends no owner header; app/scheduler/service.py's single launch_run call passes it. Remove xfail on test_scheduled_launcher_acts_through_its_delegation_not_a_raw_owner_header.
2. SECURITY: start_run's shared-workspace sandbox check (services.py ~1764-1768) is skipped for every owner-header call, and S tasks now launch as S's storage principal. Apply the check when the storage principal differs from the delegation owner.
3. 0032 must backfill delegations for org-stamped scheduled tasks in the same deploy, or they fail closed.
4. Org-less tasks skip the delegation check until header-only rejection lands.

## From lane F (MCP tasks, feedback)
1. services.py launch_mcp_task_notification_run (~2196-2269) calls resolve_active_delegation(subject_type="mcp_task", subject_id=<task id>, organization_id=<task org>, scope="runs:create") before start_run and denies when absent, revoked or expired. Test: test_mcp_notification_launcher_denies_without_active_delegation (xfail strict). 0032 backfills mcp_task delegations too.

## From lane B (threads, runs, artifacts)
1. start_run (~1749-1792): caller has no row but a checkpoint exists: 404 before seeding (test_stateless_run_cannot_claim_an_orphan_checkpoint).
2. ensure_checkpoint_history_seeded (~1486-1540): seed only when the caller owns the row (test_checkpoint_history_is_not_seeded_from_an_unowned_checkpoint).
3. sse_consumer: each heartbeat calls is_membership_active(actor, org); False ends the stream (test_open_stream_closes_when_membership_is_revoked).
4. artifacts.py (~379-431) and authz header fallback: owner header honored only through a delegation (test_internal_owner_header_alone_cannot_read_another_bucket).
5. Update gateway AGENTS.md (budget 49,152 bytes) and docs/AUTH_DESIGN.md (it recommends the header-only pattern).
Notes: browser WebSocket has no org membership check (reaches own threads only). /goal status or clear on an unsent chat now 404s: verify the frontend handles it. Flaky, pre-existing: test_browser_navigate_redacts_failure_url_from_logs_and_response fails when run after the channel tests.
