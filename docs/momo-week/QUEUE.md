# Momo Week queue (2026-09-24 → 2026-10-01)

Worked by a scheduled Claude Code cloud routine, one task (or one resumable slice) per run.
Integration branch: `lane/momo-week` (cut from `integrate/m1-20260922`).
Receipts: `docs/momo-week/PROGRESS.md`. Owner: Claude chief for Dillon Mohr.

## Rules for every run

1. Take the first task marked `[~]` (in progress) or else the first `[ ]`. Never skip ahead past a `[!]` unless the blocker note says it is independent.
2. Branch `momo-week/<slug>` from the latest `lane/momo-week`. Open or update a **draft PR into `lane/momo-week`**. Never target `main`, `production` or `integrate/*`. Never merge anything.
3. Done means the task's acceptance check passes in this run's Linux sandbox (backend: `cd backend && uv run pytest <paths> -q`; frontend: `cd frontend && pnpm test <paths>`). No green check, no `[x]`.
4. If a task is too big for one run, leave it `[~]`, push what works behind passing tests, and write the next step in PROGRESS.
5. Mark `[!]` with a one-line reason when blocked on something only Dillon can give: credentials, a product decision, spend, a deploy, a live instance. Then move to the next independent task in the same run if time allows.
6. No secrets, no deploys, no `.env` edits, no touching `deploy/momentum/*.yaml` image pins, no external sends.
7. Finish by committing the updated QUEUE.md and a PROGRESS.md line **to `lane/momo-week` directly** (these two files only).

## Tasks

### A. M3 isolation gate (prerequisite for anything multi-client)
- [x] **a1 m3-audit**: https://github.com/dillonmohr8777/deer-flow/pull/17 — all 7 gate-7.2 gaps from the plan are already closed on this branch (see `docs/momo-week/m3-status.md`); one unrelated pre-existing suite failure noted (`test_client_langfuse_metadata.py`), not caused by this change.
- [ ] **a2 m3-gaps**: Implement the missing items from a1 one lane at a time, each with a cross-org probe test that returns 404. Accept: new tests pass, full backend suite no worse than a1's baseline. Note from a1's audit: no gaps remain against the plan as scoped — `docs/momo-week/m3-status.md` recommends dropping this task rather than carrying it forward; Dillon's call.

### B. Momo Board (Workspace Phase 4): client posts, tickets, concerns, DMs, Momo drafts, owner approves
Reuse: `backend/app/gateway/routers/clients.py`, the org/membership model, the Desk page (`frontend/src/app/workspace/desk/`), run receipts, and the momo-concierge prompt text (triage, draft only, label claims observed/inferred/unknown). Gate everything behind `config.private_workspace.enabled`, the same way the Desk does.
- [ ] **b1 board-model**: `board_threads` + `board_messages` tables (kind: post|ticket|concern|dm; status: new|triaged|drafted|approved|replied|closed; client_id + organization_id server-owned), one Alembic migration, single head. Accept: migration up/down test.
- [ ] **b2 board-api**: CRUD router with per-client isolation; a client member sees only their own threads, the owner sees all. Accept: API tests, including a cross-client 404 probe.
- [ ] **b3 board-triage**: a service that classifies a new thread (kind, urgency, summary) through the existing model/agent plumbing, with a fake-model test. Accept: unit test with a stubbed LLM.
- [ ] **b4 board-draft-approve**: Momo drafts a reply into `drafted`. Only the owner can move it to `approved`; `replied` needs an explicit owner action. Every transition writes an audit row. Accept: state-machine tests, including a non-owner approval being rejected.
- [ ] **b5 board-ui**: `/workspace/board` page: thread list by status, thread view, draft editor, approve button, in the Desk's visual language. Accept: unit tests plus a Playwright spec against the mocked API.
- [ ] **b6 board-seed**: a script that seeds 3 fake clients with 2 threads each (no real client names). Accept: runs against a temp SQLite database in tests.
- [ ] **b7 board-e2e**: seeded thread → triage → draft → approve → reply, with audit rows and no cross-client leakage. Accept: a single e2e or integration test.

### C. Upkeep
- [ ] **c1 upstream-sync**: merge `bytedance/deer-flow` main into branch `momo-week/upstream-sync`, resolve conflicts, keep one Alembic head, run the suite. If conflicts touch auth/isolation, stop and write `docs/momo-week/upstream-conflicts.md` instead of guessing. Accept: suite result recorded.
- [ ] **c2 m4-entitlement-design**: design only: `docs/momo-week/m4-entitlement.md` per `plans/momentum-backend-goal.md` M4 (one evaluator, a snapshot endpoint). No code. Accept: the file exists.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done (PR link) · `[!]` blocked (reason)
