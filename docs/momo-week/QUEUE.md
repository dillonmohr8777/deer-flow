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
8. Two routines share this file. **Build routine** (`momo-week`): sections A, B, C only. **Design routine** (`momo-week-design`): section D only. Never take a task from the other routine's sections. When your sections have no `[ ]` or `[~]` left, log `queue empty` in PROGRESS and stop.

## Tasks

### A. M3 isolation gate (prerequisite for anything multi-client)
- [x] **a1 m3-audit**: https://github.com/dillonmohr8777/deer-flow/pull/17 — all 7 gate-7.2 gaps from the plan are already closed on this branch (see `docs/momo-week/m3-status.md`); one unrelated pre-existing suite failure noted (`test_client_langfuse_metadata.py`), not caused by this change.
- [x] **a2 m3-gaps**: dropped by the Claude chief 2026-09-24 23:50 UTC. a1 found no gate-7.2 gaps. The pre-existing `test_client_langfuse_metadata.py` failure is not isolation work; leave it alone.

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

### D. Design (design routine only)
Source of truth: `DESIGN.md` ("MomoBot Paper": its tokens, type and rules win over any other taste). Findings to fix: `plans/momentum-design-round4-backlog.md` (Astra's review of the live release, 7/10 cohesion). Reference surfaces built 2026-09-24: the Desk (`frontend/src/app/workspace/desk/`, PR #15) and the signed-in polish pass (PR #13, before/after images in `docs/pr-evidence/`).

**How every design run works:**
- Screenshot the target route before the change with Playwright against the mocked API. Use the existing `frontend/tests/e2e` setup (`pnpm exec playwright install chromium` if needed), at 1440×900 and 390×844.
- Make the change, screenshot again, and commit both to `docs/pr-evidence/momo-week/<slug>/`.
- Critique the "after" shots against DESIGN.md and the backlog item, as a strict reviewer. Fix what fails, then put a 1–10 score with its reasons in the PR body.
- Accept: `pnpm test` for touched components and `pnpm lint` pass, before/after images committed, and every text/background pair touched meets WCAG AA.

- [ ] **d1 metadata-legibility** (backlog 4): consequential metadata (model names, token counts, tool badges) toward 14px with stronger weight; icon controls get ≥40px hit areas.
- [ ] **d2 work-titles** (backlog 2): two-line titles plus a compact date/project identifier on assignments and recent chats; full title on hover and focus.
- [ ] **d3 telemetry-labels** (backlog 3): label the scope and period on token figures, explain the percentage, and show "Unavailable" when data is missing.
- [ ] **d4 agent-identity** (backlog 8): one persistent avatar per agent across the dashboard and Agents views; gold only on Momo's antenna.
- [ ] **d5 pins-mean-running** (backlog 7): pins only on actively executing work; static cards use folds, slots or overlaps.
- [ ] **d6 catalog-priority** (backlog 6): connected tools first; separate Connect, Configure and Details actions.
- [ ] **d7 landing-composition** (backlog 5): fill the empty blue paper with a purposeful composition built from existing assets, and tighten vertical spacing.
- [ ] **d8 board-visual** (after b5 merges into lane/momo-week; skip until then): bring `/workspace/board` fully into the Desk's paper language: thread slips, status stamps, the draft on its own sheet.
- [ ] **d9 dispatch-board** (backlog bold idea): Mission Control as a paper dispatch board. One slip per mission from brief to receipt, pins only while running, a dated ink stamp on completion linked to evidence. Scope it to one slice per run.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done (PR link) · `[!]` blocked (reason)
