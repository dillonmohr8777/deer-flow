# Momentum backend goal

Set 2026-09-22 from a full read of the repo, the running stack, the Codex ops folders and
the vault. Owner: Dillon. Detail lives here; chat stays short.

## Goal

**The Command Center backend is team-safe and rebuildable.** Organization isolation is
proven end to end, paid capabilities are gated server-side, every model dollar is on the
ledger, and the live stack rebuilds from the fork on the Mac mini with the same data.

Size: roughly 65 to 150 hours, matching Dillon's estimate. Billing provider work stays
design-only until approved (runtime contract section 8).

## Evidence this rests on (2026-09-22)

- `plans/momentum-enterprise-runtime-contract.md` defines six delivery gates. Schema gate
  is partly built (migrations 0026 to 0030: org foundation, backfill, shared workspace,
  branding). Entitlements and billing have zero code. Delegation is referenced in 2 files.
- `Codex/2026-09-19/AI-ENTERPRISE-SCALING/ACCEPTANCE-STATUS.md`: tenant authz, control
  plane, usage ledger, operations all Partial; phone receipt Not passing; 16-run role eval
  Staged.
- `TEST-SUITE-FINDINGS.md`: 39 failed, 38 deselected (McpTaskService cancellation contract,
  Windows upload lock, missing `doctor.check_llm_auth`, one order-dependent e2e).
- `work/s09b-memory-scoping` (8 commits, ~1,057 lines, `strict_user_scope=True` default
  plus auth and memory audits) exists only in the local repo
  `Codex/2026-09-21/pi/work/momentum-demo-polish`, which has no remote. Unmerged because the
  full suite hung at ~46%.
- Live gateway reads `config.yaml` from a Codex scratch folder; ops scripts live there too.
  All volume backups are on the same Docker disk.
- Branch is 40 commits past `main`, 70 behind upstream. No PR has ever been opened.
- OpenRouter: $16.88 available, read live 2026-09-22 21:49Z ($42 total, $25.12 used).
- Real users: Dillon plus Melissa (workspace admin).

## Milestones

Hours are rough ranges. Each milestone ends with a commit, a receipt, and the checkpoint
line; nothing lives only in an agent's context.

| # | Milestone | Done when | Hours |
|---|---|---|---|
| M0 | **Rescue and record** (PR #2: done except the off-machine copy) | polish repo pushed to fork as an archive; s09b branch on fork; live config shape in repo as a template with secrets as env refs; ops scripts in `deploy/momentum/`; encrypted off-machine backup of `gateway-data` restored into a scratch compose project | 3-6 |
| M1 | **Green gate** | hanging test named (pytest-timeout); s09b merged; McpTaskService cancellation contract decided and fixed; upload WinError 32 root-caused; `check_llm_auth` built or its tests removed with a reason; full suite green in a Linux container, Windows-only failures listed; PR opened to `fork/main` | 10-20 |
| M2 | **Upstream sync** | 70 upstream commits merged; one alembic head; suite green | 6-15 |
| M3 | **Isolation gate** (contract 3, 4, 7.1, 7.2) | every shareable resource carries server-owned `organization_id`, dual-written and backfilled; parent/child consistency enforced; internal callers go through `organization_delegation`; org A cannot list, read, attach, mutate, cancel, stream or download org B; revocation and org switching invalidate access; cross-org probes 404 | 20-45 |
| M4 | **Entitlement gate** (contract 5, 7.3) | one server evaluator guards every paid mutation; effective-entitlement snapshot endpoint the UI reads | 8-16 |
| M5 | **Ledger complete** | subagent attempts, title, summarization, one-shot and failed calls all recorded; atomic reserve/settle before a paid call; provider hard-cap key | 8-20 |
| M6 | **Control plane and fleet eval** | scoped PAT bound to Relay (`deerFlow=ready`); 8 roles installed via API; 16-run matrix run under an approved USD cap; phone message-ID receipt captured | 6-15 |
| M7 | **Mac mini cutover** | fresh clone plus env file plus backup rebuilds the stack; health, both logins, and the 47 document hashes match | 4-10 |
| B | **Billing gate** (contract 7.4) | design and tests against a fake provider only; no install, checkout or charge without approval | 0-8 |

Order: M0 first (it only adds copies). M1 before M3 so isolation work lands on a trusted
gate. M2 can run beside M1. M4 and M5 follow M3. M7 last.

## How it runs

- One worktree per milestone lane, branched from the current integration tip; lanes own
  disjoint files. M3 splits by resource domain (projects/docs, threads/runs/artifacts,
  schedules, agents/batches, channels/OAuth, MCP tasks/feedback).
- Tests run in a Linux container as the source of truth; Windows runs are advisory.
- Every schema change gets a round-trip on a copy of the live DB before deploy, and a
  fresh volume backup (post-0030 rollback is not image-only).
- Security findings stop the lane and go to Dillon; they are not fixed at speed.

## Needs Dillon

1. Rotate the OpenRouter key and the DeerFlow password (both pasted in chat).
2. Docker AutoStart on.
3. USD cap for the M6 eval (balance is $16.88).
4. Where the key for the off-machine encrypted backup lives (M0). The McpTaskService
   cancellation question is moot: `service.py` already re-raises (lines 654, 1044,
   1212, per an Astra review 2026-09-22), so those test failures have another cause.
5. Approval before any org-mode enablement for a second member beyond the current
   single-owner rule (contract section 4).
