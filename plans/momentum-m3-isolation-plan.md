# M3 isolation gate: implementation plan

Planned 2026-09-22 against `integrate/m1-20260922` (suite green). Contract:
`plans/momentum-enterprise-runtime-contract.md` sections 3, 4, 7.1, 7.2. Paths:
`B` = `backend`, `H` = `B/packages/harness/deerflow`, `G` = `B/app/gateway`.

## Key finding

Every organization, private or shared, has `id = private_organization_id(storage_user_id)`
(`G/routers/workspaces.py:139-140`, `H/persistence/organizations/resolution.py:73-79`),
and every repository filters by the storage principal. For browser and PAT traffic,
org isolation already equals storage-user isolation. M3 closes the edges (internal
callers, ownerless threads, shared-workspace identity bugs), adds the explicit org
filter the contract requires next to every user filter, and proves it with tests.
No new columns.

## 1. State matrix

| Resource | ORM column | Dual-write | Backfilled | Reads org-filtered | Parent/child |
|---|---|---|---|---|---|
| projects | yes | yes | yes (0027) | no | n/a |
| project documents | yes | yes | yes | no | partial: restore moves doc without re-deriving org (sql.py:655) |
| threads | yes | yes | yes | no | partial: ownerless threads open to all (thread_meta/sql.py:219-220) |
| runs | yes | partial: NULL org when no thread row (stateless runs) | yes | no | yes when thread exists |
| scheduled tasks | yes | yes | yes | no | partial: router uses login user, not workspace storage user (`G/routers/scheduled_tasks.py:201,235,259`) |
| scheduled task runs | yes | yes | yes | no | yes |
| custom agents | yes | yes | yes | no; `list_all` global | n/a |
| subagent batches | yes | yes | yes | no | yes |
| channel connections | yes | yes | yes | no | n/a (always private org) |
| pending OAuth states | yes | yes | yes | n/a | partial: consume returns no org |
| channel conversations | yes | yes | yes | no | partial: thread not checked |
| MCP tasks | yes | yes | yes | no | partial: accepts ownerless threads |
| feedback | yes | yes | yes | no | broken in shared workspaces: login user passed, repo raises, 500 |
| artifacts/uploads/doc files | none by design | n/a | n/a | paths keyed by storage user | internal callers use raw header (`G/routers/artifacts.py:379-380`) |

## 2. Security findings (verified in code 2026-09-22)

- **F1 High (contract 4): a raw header establishes org context.** Internal token plus
  `X-DeerFlow-Owner-User-Id` acts as any user with no membership check
  (`G/internal_auth.py:42-67`, `G/authz.py:738-753`; scheduler and MCP notifications build
  the same in-process, `G/services.py:2098-2105,2176-2180`). Mitigated today: secret token,
  sandbox strips `*TOKEN*` env, and on live the scheduler and MCP tasks are off and no
  channels exist. `organization_delegations` table exists, unused.
- **F2 Medium: ownerless threads are open to every org** (`check_access` returns True when
  `user_id is None`, thread_meta/sql.py:219-220); no-row threads pass reads; checkpoints are
  keyed only by thread id.
- **F3 Low: workspace cookie is an unsigned selector**, not a token claim. It cannot grant
  membership (re-checked every request).
- **F4 Contract: team mode is live.** Invitees become `admin`
  (`G/routers/invitations.py:208,365`), beyond the contract's single-owner rule.

## 3. Gaps to gate 7.2

1. `organization_id == active org` beside every user filter (13 tables, console SQL).
2. Delegation for internal callers: status, expiry, scope, owner's active membership;
   grant/revoke; permissions narrowed like PATs; then reject header-only calls.
3. Ownerless/no-row threads fail closed (except upload-before-create and PUT goal).
4. Writes: server-resolved org wins, parent must match (fixes stateless runs, feedback,
   shared-workspace schedules).
5. OAuth completion bound to the state's org; conversation attach checks the thread;
   document restore re-derives org.
6. Re-backfill NULL rows since 0027; backfill delegations.
7. Test matrix (today only `B/tests/test_owner_isolation.py` covers 4 resources).

## 4. Lanes

Shared rules: add the org filter when `resolve_organization_id()` is non-null; stamp with
`organization_for_write(active_org, parent, storage_user)`, mismatch = 404. Fixtures: orgs
A, B, shared workspace S with storage user, users a/b/c (reuse
`B/tests/test_shared_workspace_membership.py:18-37`).

| Lane | Owns | Migrations | Tests first | Hours |
|---|---|---|---|---|
| 0 Core (first) | `H/runtime/user_context.py`, `resolution.py`, new `organizations/delegation.py`, `G/auth_middleware.py`, `internal_auth.py`, `authz.py`, `services.py`, AGENTS.md, new `tests/org_isolation_fixtures.py` | `0031_org_rebackfill` (data only; must skip workspace storage users; downgrade no-op), `0032_org_delegation_backfill` (downgrade deletes `dlg0032-*`) | header-only denied; revoked/expired/wrong-scope delegation denied; revoked owner denied; scopes narrow; migration round-trips | 8-12 |
| A Projects, documents | projects/sql, routers projects, project_documents, project_thread_files, trash | none | every project/document route 404 across orgs; restore stamps target org | 3-5 |
| B Threads, runs, artifacts, streams | thread_meta, run/sql, routers threads, thread_runs, runs, artifacts, uploads, browser, console | none | full thread/run/artifact/upload/console surface 404 across orgs; ownerless and orphan checkpoints 404; stateless runs stamped; org switch flips visibility | 7-12 |
| C Schedules | scheduled_tasks, scheduled_task_runs, router, scheduler service | none | 404 across orgs; B-thread attach 404; co-member sees S tasks; create grants and delete revokes delegation; revoked owner fails occurrence | 3-6 |
| D Agents, batches | agents, subagent_batches, routers, `G/github/*` | none | CRUD and batch reads 404 across orgs; managed subagents global admin-only; GitHub match without delegation skipped | 3-5 |
| E Channels, OAuth | channel_connections, router, `B/app/channels/*` | none | 404 across orgs; A state cannot complete into B; cross-org thread attach rejected; disconnect revokes | 4-7 |
| F MCP tasks, feedback | mcp_tasks/sql, feedback/sql, routers | none | 404 across orgs; no attach to ownerless threads; feedback in S stored with person's user_id and S's org | 3-5 |

Order: lane 0 interfaces first (~3h), then A-F in parallel, then lane 0 phase 2
(reject header-only) after C, E, F grant code lands; full Linux matrix; rehearsal on a
copy of the live DB (2-4h). Total 33-56h. D and E can ship fail-closed without grant
flows (no internal caller is live) to save ~5h.

## 5. Migration strategy (live SQLite at 0030)

Every deploy: `deploy/momentum/backup_volume.py` snapshot and rehearsal first. Bootstrap
refuses unknown revisions, so rollback after a new revision = restore backup plus previous
image. No DDL until step 4.

0. Pre-flight on the copy: owned rows without org, ownerless threads, orphan checkpoints,
   internal callers needing delegations, memberships by role/status.
1. Deploy 1: write fixes plus 0031. NULL org is the quarantine marker.
2. Deploy 2: org filter, fail-closed threads, delegation grants (code only).
3. Deploy 3: 0032 plus reject header-only calls.
4. Optional 0033: DB guards (`user_id IS NULL OR organization_id IS NOT NULL`).

Each step checks health, both logins, 94 documents, run count, empty audit query.

## 6. Decisions (Dillon)

Defaults proposed in chat 2026-09-22; record answers here.

1. F4: freeze new invitations until M3 lands; keep Melissa's seat.
2. F1: reject header-only internal calls at deploy 3; rotate the internal token then.
3. Ownerless/orphan threads: hide (fail closed) and list them for claiming.
4. Channels stay personal (private org) during M3.
5. Parent/child consistency via repository checks plus audit query; DB guards (0033)
   deferred until team mode.
6. Revocation applies to new requests; an open SSE stream finishes.
