# c1 upstream-sync: stopped — conflicts touch auth/isolation

Per `docs/momo-week/QUEUE.md` c1: "If conflicts touch auth/isolation, stop and
write this file instead of guessing." This run attempted the merge, found
conflicts squarely in that territory, and stopped without resolving them.

## What was tried

```
git checkout -b momo-week/upstream-sync lane/momo-week
git remote add upstream https://github.com/bytedance/deer-flow.git
git fetch upstream main    # 74f6dce4890bb19dde5c8fe8bb5d24475616b35c
git merge upstream/main --no-edit
```

`lane/momo-week` is 403 commits ahead / 101 commits behind
`upstream/main` (merge base `c9043c25`). The merge produced 21 conflicted
files before it was aborted (`git merge --abort`); the branch
`momo-week/upstream-sync` currently sits at the same commit as
`lane/momo-week` (`b102d931`), no merge attempted in its history.

A second attempt to redo the merge for further inspection was blocked by
this session's own tool-permission policy ("Untrusted Code Integration"),
which independently confirms this is not a merge to push through
automatically.

## Conflicted files

```
backend/app/gateway/AGENTS.md
backend/app/gateway/auth/repositories/sqlite.py            (2 hunks)
backend/app/gateway/routers/agents.py                      (6 hunks)
backend/app/gateway/routers/user_preferences.py
backend/app/gateway/services.py                            (2 hunks)
backend/packages/harness/deerflow/config/AGENTS.md
backend/packages/harness/deerflow/config/paths.py           (2 hunks)
backend/packages/harness/deerflow/persistence/mcp_tasks/sql.py (3 hunks)
backend/tests/test_custom_agent.py
backend/tests/test_mcp_task_repository.py                   (2 hunks)
backend/tests/test_scheduled_task_dispatch_race.py
backend/tests/test_threads_router.py                        (2 hunks)
frontend/src/AGENTS.md
frontend/src/components/workspace/input-box.tsx             (2 hunks)
frontend/src/components/workspace/messages/message-list.tsx (2 hunks)
frontend/src/components/workspace/sidecar/sidecar-panel.tsx
frontend/src/core/i18n/locales/en-US.ts
frontend/src/core/i18n/locales/types.ts
frontend/src/core/i18n/locales/zh-CN.ts
frontend/src/core/settings/local.ts
frontend/src/core/settings/preferences-sync.ts
frontend/tests/e2e/sidecar-chat.spec.ts
```

## Why this is an auth/isolation conflict, not a mechanical one

Two of the backend conflicts were read in full before aborting, and both are
squarely inside this fork's multi-tenant isolation model — the thing gate-7.2
(section A) exists to protect:

- **`backend/app/gateway/auth/repositories/sqlite.py`** (`_insert_user`,
  `create_first_admin`): this fork's `HEAD` creates a private `Organization`
  row and an `OrganizationMemberRow` (`role="owner"`) atomically alongside
  every new `User` row — `private_organization_id`/`private_organization_slug`
  seed the org/membership model every other isolation check depends on.
  Upstream's version has no organizations at all; it just inserts the user
  row. A naive "take ours" resolution is *probably* correct here, but
  upstream also touched the surrounding transaction shape (moved from
  `session.flush()` inside a pre-opened `async with self._sf()` to a fresh
  `async with self._sf() as session:` per call, restructured
  `create_first_admin`'s locking), so this needs a careful reconciliation,
  not a blind pick of one side.

- **`backend/app/gateway/routers/agents.py`** (`create_agent` and 5 more
  hunks): `HEAD` threads `user_id=get_effective_user_id()` through
  `store.create(...)` and `load_agent_config(...)` — per-user agent
  scoping — and carries a fork-only `memory_enabled` config field. Upstream
  renamed the request parameter (`request` → `body`) in the same region.
  Resolving this means re-applying the user-scoping and `memory_enabled`
  logic on top of upstream's renamed variable across all 6 hunks, in a
  router that already has 3 active review findings open in section F
  (`f1`–`f4`, `f8`) on the sibling board router — this is not a good moment
  to also be hand-splicing its neighbor.

- **`backend/app/gateway/routers/user_preferences.py`**,
  **`backend/app/gateway/services.py`**, and
  **`backend/packages/harness/deerflow/config/paths.py`** conflict in the
  same layer (gateway auth-adjacent routers/services, and the path-resolution
  module `PATH_EXAMPLES.md` documents as user/thread-scoped). Not read in
  full this run, but they sit in the same isolation-sensitive code paths as
  the two above, and follow the same pattern (this fork adding per-user/org
  scoping that upstream's history doesn't have).
- **`backend/packages/harness/deerflow/persistence/mcp_tasks/sql.py`**
  (3 hunks) is the durable MCP task store `backend/packages/harness/deerflow/mcp/AGENTS.md`
  documents as lease/ownership-based — persistence-layer conflicts here carry
  the same risk of silently dropping an ownership check.

The remaining conflicts (`AGENTS.md` doc merges, i18n locale tables,
`frontend/src/core/settings/local.ts` + `preferences-sync.ts`, the
`input-box.tsx`/`message-list.tsx`/`sidecar-panel.tsx` UI hunks, and the
mirrored test files) look more mechanical — mostly this fork's
Momentum-specific additions sitting next to upstream's unrelated edits in the
same functions — but were not individually triaged since the backend
auth-layer conflicts already meet the "stop" bar on their own, and getting
those right first is a prerequisite for trusting the rest.

## Recommendation for Dillon

This is a product/architecture call, not something to guess through:

1. **Smallest safe slice**: take only the non-conflicting 101 upstream
   commits worth taking (many of the 101 landed clean — see `Auto-merging`
   lines in the aborted attempt), and defer the 21 conflicted files to a
   follow-up once someone can review the auth/isolation hunks line by line.
2. **Full sync**: work through the 5 backend auth-layer files by hand,
   re-running gate-7.2-style isolation tests after each, before touching the
   frontend/test conflicts. This is realistically a multi-run slice, not a
   single scheduled-task pass.
3. **Skip for now**: leave `c1` blocked and let the fork diverge further;
   revisit when there's a specific upstream fix or feature worth cherry-picking
   instead of a full `main` merge.

No code was changed on `momo-week/upstream-sync`; the branch is at the same
commit as `lane/momo-week` (`b102d931`). No PR was opened for this — there is
nothing to review yet, only this analysis.
