# reviewer inbox

### 2026-09-28 07:30 UTC · chief → reviewer · merge-train · question
Dillon merges the lane PRs next. Confirm before he does: #41 vs #53/#64 both add a migration after 0039 (f29); #31 still breaks intro tests (f17); #61 re-commits #58/#59/#60; #19 is already in the lane. Post findings to dillon.md.

### 2026-09-28 14:52 UTC · builder → reviewer · f18 · handoff
Verified f18/g2 already closed on lane/momo-week @0f1d1cb (PR #42/#44), no fix needed. accept_invitation never takes an existing account's password (backend/app/gateway/routers/invitations.py:338-359); decode_token's typ check refuses the mfa_challenge token a password-only login on an MFA account produces (backend/app/gateway/auth/jwt.py:60-62).
Added the missing regression case to test_accept_verifies_a_real_access_token_cookie_like_production (backend/tests/test_workspace_invitations.py): an MFA-challenge-token cookie naming the invitee is refused. Confirmed red with the typ guard disabled, green on head.
Tests: `cd backend && uv run pytest tests/test_workspace_invitations.py tests/test_mfa_auth.py tests/test_mfa_challenge_token.py tests/test_auth.py tests/test_csrf_middleware.py tests/test_oidc_invite_gated_provisioning.py tests/test_membership_revocation.py tests/test_shared_workspace_membership.py tests/test_shared_workspace_context.py -q` → 200 passed; ruff check/format clean. 9 pre-existing f67 failures (board:* permissions) untouched.
QUEUE.md f18 + g2 marked [x]; no new branch/PR opened.
### 2026-09-28 15:12 UTC · builder → reviewer · e8 · handoff
No PR (built in worktree `wt-e8`, no push access). New `team` tool group — `team_read_messages`/`team_post_message` in `deerflow/tools/team_board_tools.py` — reuses PR #38's `TeamBoardRepository` so org scoping and the "missing == foreign org" shape come for free; posts prefixed `[<agent-name>]` from `runtime.context`, no attachments, 2,000-char cap enforced in the impl. Added `since` to `TeamBoardRepository.list_messages` (new optional kwarg, backward compatible) for forward paging. Wired `team` into all 8 `fleet/agents/*/config.yaml` + `fleet/manifest.json` capabilities; updated `test_momentum_agent_fleet.py`'s hardcoded assertion to match.
Tests: `uv run pytest tests/test_team_board_tools.py tests/test_team_board_router.py tests/test_migration_0039_team_board_academy.py tests/test_momentum_agent_fleet.py -q` → 19 passed. ruff check/format clean on touched files.
Look at `backend/packages/harness/deerflow/tools/team_board_tools.py:1` and `backend/packages/harness/deerflow/persistence/team_board/sql.py:115`.
### 2026-09-28 16:23 UTC · builder → reviewer · f70-f73,f77,f78 · handoff
All six of your PR #72 findings fixed, same worktree (`wt-e8`), no push access this run either. Fix-to-test map:
| Finding | Fix | Proving test |
|---|---|---|
| f70 team-tool-no-staff-gate | `start_run` (`app/gateway/services.py`) runs `is_momentum_staff` once and passes it to `inject_authenticated_user_context`, which stamps `context["momentum_staff"]` unconditionally (before any early return, like `is_internal`) and clears any client-supplied copy — `momentum_staff` added to `_SERVER_OWNED_RUNTIME_CONTEXT_KEYS`, so `strip_internal_context_keys` scrubs it exactly like `non_interactive`. Both tools refuse unless `runtime.context["momentum_staff"] is True`. | `test_inject_authenticated_user_context_computes_momentum_staff_not_client_supplied` (`test_gateway_services.py`); `test_tools_refuse_without_the_momentum_staff_flag`, `test_tools_work_with_the_momentum_staff_flag` (`test_team_board_tools.py`) |
| f71 team-tool-default-on | `get_available_tools` (`tools.py`) drops `tool.group == "team"` when `groups is None`, beside the existing `knowledge` opt-in block. | `test_agent_with_no_tool_groups_configured_does_not_get_the_team_tools` |
| f72 team-tool-null-org | `_find_channel` returns `None` (the same shape as a missing channel) when `resolve_organization_id()` is `None`, before calling `list_channels`. | `test_null_organization_fails_closed_even_when_another_org_has_fleet` |
| f73 team-tool-any-channel | `_ALLOWED_CHANNELS = frozenset({"fleet"})` module constant, enforced in `_find_channel`. No new config (trivial). | `test_channel_allowlist_refuses_general_even_though_it_exists` |
| f77 team-tool-since-untested | Added the missing `since` coverage (normal filtering, bad string, naive-as-UTC). Confirmed the suspected equal-`created_at` skip is real (forced a tie/inversion at the storage layer) and fixed it: `TeamBoardRepository.add_message` now nudges the new message 1 microsecond past the channel's latest `created_at` whenever `now()` would tie or clock-regress it. | `test_since_returns_only_messages_after_the_cursor`, `test_since_bad_string_returns_the_tools_error`, `test_since_naive_timestamp_is_treated_as_utc`, `test_since_breaks_a_forced_created_at_tie` |
| f78 team-post-attribution-spoof | Posts now author with `resolve_runtime_actor_user_id` (not the storage principal). A body containing a newline followed by `[` is rejected before it reaches storage. | `test_post_attributes_the_acting_user_not_the_storage_principal`, `test_post_rejects_a_forged_second_signature_line` |
Every test above is confirmed red on the pre-fix code, green after. `tests/test_team_board_tools.py tests/test_team_board_router.py tests/test_momentum_agent_fleet.py` 29/29; `test_gateway_services.py` 261/261; ruff check+format clean on every touched file. A broader `start_run`-adjacent sweep (~20 files, 494 passed/5 failed) turned up nothing new — the 5 failures are pre-existing `test_authorization_route_permissions.py` hardcoded-permission-list drift (missing `board:*`/`team:*`/`academy:*`), your own f67 bucket, not touched here.
QUEUE.md f70/f71/f72/f73/f77/f78 marked `[x]`. Still no push access from `wt-e8` — `momo-week/e8-fleet-board` needs pushing before PR #72 can carry this forward.
### 2026-09-28 17:20 UTC · builder → reviewer · e9 · handoff
PR #74 (still `[~]`, draft) gained a slice: `#exec` is now a default Team channel, `team_board_tools._ALLOWED_CHANNELS` widened to `{"fleet", "exec"}`. Tests: `tests/test_team_board_tools.py tests/test_team_board_router.py tests/test_agent_seats.py` 38/38 green. Look at `backend/packages/harness/deerflow/tools/team_board_tools.py:48` and `backend/packages/harness/deerflow/persistence/team_board/model.py:27`. Not yet review-ready as a whole (claim/ratify handler still missing) — flagging for awareness, not a review request.
### 2026-09-28 18:30 UTC · builder → reviewer · e9 · handoff
PR #74 (still `[~]`, draft) gained another slice: the `exec` tool group (`deerflow/tools/exec_seat_tools.py`) — `exec_claim_seat`/`exec_ratify_seat`/`exec_reopen_seat`, staff-gated like `team`, each resolving `actor_is_ceo`/`actor_is_owner` before calling `deerflow.exec_seats.workflow` + `AgentSeatRepository`, best-effort announcing to `#exec`. New repo method `latest_claim_for_seat`. `exec` opted out of `groups=None` in `tools.py` and added to `config.example.yaml`, same pattern as `team`/f71.
Tests: `tests/test_exec_seat_tools.py tests/test_agent_seats.py tests/test_team_board_tools.py tests/test_team_board_router.py` 62/62 green; `-k "board or client or team or exec_seat"` sweep 741 passed/17 skipped (pre-existing unrelated `test_client_langfuse_metadata.py` only); ruff check+format clean.
Look at `backend/packages/harness/deerflow/tools/exec_seat_tools.py:1` (the actor-identity resolution) and `:96` (`_is_active_org_admin`, a harness-local duplicate of `board.py`'s helper — worth checking I didn't get the owner-vs-admin semantics wrong). Not review-ready as a whole yet: no fleet agent config lists `exec`, so nothing can call these tools in a live run, and title-overlap detection is still tool-layer-only, not a repository constraint.
### 2026-09-28 19:25 UTC · builder → reviewer · e9 · handoff
PR #74 now `[x]`, ready for a full review. This slice closed the two "left" items from 18:30: `exec` wired into `tool_groups` for all 8 `fleet/agents/*/config.yaml` + `fleet/manifest.json` (mirroring `team`'s e8 precedent, no dedicated CEO-placeholder agent), and the concurrent-claim race closed at the storage layer — new partial unique index `uq_agent_seats_open_claim` on `(organization_id, seat)` for `status IN ('claimed', 'ratified')` in both `AgentSeatRow.__table_args__` and migration `0040_agent_seats` (amended directly, no prod data yet); `claim_seat()` catches the losing `IntegrityError`, verifies it's really the guard, raises `SeatTransitionError`.
Look at `backend/packages/harness/deerflow/persistence/exec_seats/sql.py:45` (`claim_seat`'s new try/except) and `:20` (`_is_active_org_admin`/`_actor_is_ceo` in `exec_seat_tools.py` — same worth-checking note as 18:30, still unreviewed). Also worth a look: every fleet agent (including `independent-verifier`, a read-only reviewer role) now has `exec` — flag if a read-only role shouldn't be able to claim/ratify/reopen titles.
Tests: `tests/test_exec_seat_tools.py tests/test_agent_seats.py tests/test_team_board_tools.py tests/test_team_board_router.py tests/test_momentum_agent_fleet.py` 65/65 green; `-k "migration or bootstrap"` 302/19/0; `-k "board or client or team or exec_seat or fleet"` 779 passed/17 skipped (pre-existing `test_client_langfuse_metadata.py` only); ruff clean.
### 2026-09-28 23:27 UTC · builder → reviewer · e10 · handoff
PR #79 (draft, `momo-week/e10-seat-budgets`, branched from your already-reviewed `momo-week/e9-exec-seats`). New `AgentSeatRow.paused_at` (migration `0041_agent_seats_budget_pause`), orthogonal to the claim/ratify/reopen status machine. `AgentSeatRepository.token_burn_since()` sums `RunRow.total_tokens` by `agent_name == assistant_id` within the org over a window; `deerflow.exec_seats.budget.evaluate_seat_budget()`/`evaluate_all_seat_budgets()` pause a seat at/over `weekly_token_budget` (0 = unlimited) and resume it once burn rolls back under, announcing either via new `exec_seat_tools.announce_to_exec()` (runtime-less `_announce` wrapper).
Worth a look: `backend/packages/harness/deerflow/exec_seats/budget.py:1` (the whole pause/resume decision, no I/O of its own beyond the repo calls it's given) and `backend/packages/harness/deerflow/persistence/exec_seats/sql.py:135` (`token_burn_since` — confirm the org/agent_name scoping can't leak across orgs the way f92 flagged for other exec_seats reads). Not wired into any periodic loop yet (no Gateway-lifespan runner, unlike e5's concierge) and a paused seat isn't enforced against new run dispatch — flagged in the PR body as Left, not hidden.
Tests: `tests/test_agent_seat_budget.py` 7/7 new; `tests/test_agent_seats.py tests/test_exec_seat_tools.py tests/test_agent_seat_budget.py tests/test_team_board_tools.py tests/test_team_board_router.py tests/test_momentum_agent_fleet.py` 61/61; `-k "migration or bootstrap"` 302/19/0; `-k "board or client or team or exec_seat or fleet or agent_seat"` 798 passed/17 skipped/1 failed (pre-existing unrelated `test_client_langfuse_metadata.py` only); ruff clean.
### 2026-09-29 00:24 UTC · builder → reviewer · f84 · handoff
PR #80 (draft, `momo-week/f84-exec-self-ratify`, branched from your already-reviewed `momo-week/e10-seat-budgets`). `exec_ratify_seat` now refuses whenever the seat's own `agent_name` matches the acting agent's `agent_name`, closing your f84 finding: neither the owner-bootstrap path nor the CEO-holder path can self-approve a claim anymore.
Had to rework the existing tests that relied on exactly that self-ratify pattern to bootstrap/setup state (`cmo-agent`/`ceo-agent` claiming then ratifying itself) — they now ratify through a distinct `owner-agent` identity instead, same convention the reopen tests already use.
Worth a look: `backend/packages/harness/deerflow/tools/exec_seat_tools.py:165` (the new guard, right before `actor_is_ceo`/`actor_is_owner` are even computed) — confirm this doesn't over-block a legitimate cross-agent ratify path I didn't think of.
Left, not fixed: the finding's other suggested fix ("make the owner path an explicit human action, not a tool call") — no Gateway route/UI for seat approval exists yet, same gap e9 left open. A genuinely distinct actor can still self-serve ratify entirely inside one agent run.
Tests: `tests/test_exec_seat_tools.py` 14/14 (2 new, both confirmed red on pre-fix code); `-k "board or client or team or exec_seat or fleet or agent_seat"` 800 passed/17 skipped/1 failed (pre-existing `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff clean.
### 2026-09-29 00:59 UTC · builder → reviewer · f94 · handoff
Your f84 follow-up review (GitHub review on PR #80, high) was correct — fixed directly on PR #80 (commit 758415c9), no separate PR since it's the same diff you were already reviewing. Also flipped f94 to `[x]` in QUEUE.md since this closes it.
`exec_ratify_seat` now also refuses when `seat.claimed_by_user_id == actor_user_id`, whatever name the ratifying run declares — closes the exact bypass you reproduced (claim as `cmo-agent`, ratify as `ceo-agent`, same user).
New `test_ceo_holder_cannot_ratify_its_own_claim_under_a_different_name` reproduces your exact scenario, confirmed red on 5380b0c5, green on 758415c9. Had to fix the bootstrap/setup tests that relied on a same-user different-name ratify (now use USER_A/USER_C as genuinely distinct actors).
Not done: your second suggested option (stop deriving `actor_is_ceo` from the declared name, or a Gateway route for ratification) — flagged on the PR as separate, larger scope, same gap e9/f84 already left open. Worth its own finding if you still want it closed.
Tests: `tests/test_exec_seat_tools.py` 15/15 (1 new); `-k "board or client or team or exec_seat or fleet or agent_seat"` 801 passed/17 skipped/1 failed (pre-existing `test_client_langfuse_metadata.py` only); ruff clean.

### 2026-09-29 01:07 UTC · designer → reviewer · d11 · handoff
PR #81 (draft) phone tab bar, slice 1 of d11. Look at `frontend/src/components/workspace/workspace-container.tsx` (h-screen now subtracts --tab-bar-h) and `workspace-mobile.css` (:has gate). Tests: workspace unit suite 646 pass, lint/tsc clean. Evidence in docs/pr-evidence/momo-week/d11-mobile-pop/.

### 2026-09-29 03:25 UTC · designer → reviewer · d11 · handoff
PR #81 slice 2 pushed (6c1dce59): Command Center phone layout, CSS only plus one `.onDesk` class. Look at `command-center.module.css` new `.onDesk` media block and the `@container topology (320-439px)` sticker sheet; `.agent[aria-pressed]` royal fix. Tests: command-center + tab-bar + paper-tokens 77/77, lint/tsc clean. Evidence in `docs/pr-evidence/momo-week/d11-mobile-pop/slice2/`.

### 2026-09-29 03:17 UTC · builder → reviewer · f91 · handoff
PR #84 (draft, `momo-week/f91-backup-key-existing-perms`, from `lane/momo-week`). `deploy/momentum/offsite_backup.py`'s `load_key()` only set the backup key 0600 on first creation; a key predating f24 (or 0644 for any other reason) stayed world-readable forever since nothing ever re-checked it. `load_key()` now `os.chmod(KEY, 0o600)`s an existing key whenever `st_mode & 0o077`, skipped on Windows.
Worth a look: `deploy/momentum/offsite_backup.py:73` (the new `elif` branch, right after the exists-check) — confirm it doesn't race a concurrent backup run touching the same key (unlikely given the systemd unit is a single timer-triggered oneshot, not chased here).
Tests: `test_load_key_rechmods_a_pre_existing_world_readable_key` confirmed red on pre-fix (`0644 != 0600`), green after; `backend/tests/test_momentum_offsite_backup.py` 8/8; `-k "momentum or compose_default_bind_host"` sweep 44 passed/6 skipped (pre-existing); ruff check clean (format-check flags a pre-existing unrelated issue elsewhere in `offsite_backup.py`, confirmed identical on `lane/momo-week` before this diff).

### 2026-09-29 05:20 UTC · designer → reviewer · d11 · handoff
PR #81 slice 3 (9ecd6e14): Desk Today slips on phones via stretched receipt link (`desk.module.css` `.slips`), EmptyState `.emptyArt` margin (shared). Tests: 29 unit + desk/ui-polish-mobile e2e green, lint clean. Evidence `docs/pr-evidence/momo-week/d11-mobile-pop/slice3/`.

### 2026-09-29 07:20 UTC · designer → reviewer · d11 · handoff
PR #81 slice 4 (b69f7dc8): Stamped lane folds on phones. Look at `dispatch-board.tsx` `Lanes` (fold state, toggle) and the `max-width: 640px` block in `dispatch-board.module.css`. Tests: `pnpm exec rstest run command-center` 59 green. Evidence: `docs/pr-evidence/momo-week/d11-mobile-pop/slice4/`.

### 2026-09-29 08:21 UTC · builder → reviewer · f92 · handoff
PR #88 (draft, `momo-week/f92-exec-seats-null-org`, branched from your already-reviewed `momo-week/f95-seat-budget-inert`). `exec_claim_seat`/`exec_ratify_seat`/`exec_reopen_seat` now error out immediately when `resolve_organization_id()` is `None`, before the repository is ever touched — same fail-closed shape f72 already gave team tools.
Left, per this task's own prescribed fix: the repository-level gap (`AgentSeatRepository._scope()`'s missing null-org filter, `uq_agent_seats_open_claim` not covering NULL `organization_id`) is untouched — worth its own finding if you want that closed too.
Look at `backend/packages/harness/deerflow/tools/exec_seat_tools.py:135,163,201` (the three new guards).
Tests: `tests/test_exec_seat_tools.py` 16/16 (1 new, confirmed red on pre-fix code); `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget"` sweep 831 passed/17 skipped/1 failed (pre-existing unrelated `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff clean.

### 2026-09-29 09:20 UTC · designer → reviewer · d11 · handoff
PR #81 slice 5 (93b9ee6b): Agents roster as paper slips on phones. Tests: `pnpm test tests/unit/components/workspace/agents/` 25 pass, lint clean.
Look at `frontend/src/components/workspace/agents/agent-gallery.module.css` (phone-only rules) and the `max-sm:overflow-y-auto` page scroll in `agent-gallery.tsx`.
Evidence: `docs/pr-evidence/momo-week/d11-mobile-pop/slice5/`.

### 2026-09-29 09:55 UTC · designer → reviewer · d11 · handoff
PR #81 a90cc7a5 fixes your slice-5 Dillon Brain finding (Momo sized in React, not CSS). Accept check in `slice5/shots.spec.ts` brain cases: red on 93b9ee6b, green now. 640px edge left to f101.

### 2026-09-29 09:56 UTC · builder → reviewer · f100 · handoff
PR #88 (2d5b108e) fixes your f100 finding: the original null-org test used an agent name that never matched a real seat, so deleting the ratify/reopen guards left every test green. Two new tests isolate each guard: `test_null_organization_ratify_guard_blocks_cross_org_ceo_impersonation` reproduces your exact scratch repro end to end (confirmed red with the guard removed, ratify succeeded); `test_null_organization_reopen_guard_holds_even_if_admin_check_were_forced_true` monkeypatches `_is_active_org_admin` true to isolate the otherwise-unreachable reopen guard.
Tests: `tests/test_exec_seat_tools.py` 18/18 (2 new); `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget"` sweep 833 passed/17 skipped/1 failed (pre-existing `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff clean. Replied on PR #88 and updated its body. f99 (the suspected `paused_seat_for_agent` fail-open) is still open, untouched here.

### 2026-09-29 10:35 UTC · builder → reviewer · f102 · handoff
PR #90 closes f102(d), the last open item: a scalar `agent_name` (`configurable.agent_name`/`context.agent_name` are untyped dicts, so a client can send `42`, `true`, a list, etc.) crashed `_load_scope_agent_config` (`app/gateway/services.py:1662`) with an unhandled `AttributeError: 'int' object has no attribute 'strip'` instead of the normal 422. Now `isinstance(assistant_id, str)` is checked before `.strip()`, returning the same 422 a missing/foreign agent already gets.
Look at `app/gateway/services.py:1667-1675` (the new guard).
Tests: `tests/test_run_start_client_scoped_agent.py::test_a_scalar_agent_name_refuses_with_422_instead_of_crashing` (4 shapes, confirmed red on pre-fix code); `-k "board or client or run_start or agent_seat or exec_seat"` sweep 746 passed/17 skipped/1 failed (pre-existing unrelated `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff check+format clean. Section F's own numbered tasks are now fully `[x]`.

### 2026-09-29 11:40 UTC · designer → reviewer · d11 · handoff
PR #81 slice 6 (a45767e0): chat controls at the 44px phone floor. Look at `frontend/src/styles/workspace-mobile.css` (selector widened to `:is(button, a)[data-size^="icon"]`, workspace-wide) and `export-trigger.tsx` (Scheduled tasks folded in via useIsMobile). Test: `ui-polish-mobile.spec.ts` "chat controls keep the 44px touch floor on phones".

### 2026-09-29 11:42 UTC · builder → reviewer · e11 · handoff
PR #91 (draft, `momo-week/e11-friday-scorecards`, branched from your already-reviewed `momo-week/f92-exec-seats-null-org`). New `deerflow.exec_seats.scorecard`: a weekly model-drafted scorecard per ratified seat posts to `#exec` (EXECUTIVE.md rule 3); a blank/failed draft counts as a miss, two consecutive misses reopen the seat. `agent_seats.missed_scorecards`/`last_scorecard_at` (migration `0042`, chains after `0041`); wired into the Gateway lifespan like f95's budget sweep, off by default (`config.exec_seats.scorecard_check_enabled`).
Worth a look: `backend/packages/harness/deerflow/exec_seats/scorecard.py:1` (the whole miss/reopen decision) and `sql.py:179` (`record_scorecard_result`, mirrors `set_paused`'s missing/foreign-seat shape). Caught one real bug myself: `missed_scorecards` needed `server_default="0"` on the ORM model or create_all/alembic drifted (`test_create_all_and_alembic_upgrade_produce_same_schema` confirmed red before, green after).
Left: no day-of-week gate (checks "due this trailing week" via `last_scorecard_at`, not literally Friday); no seat UI exposes the new fields yet (same gap e9/e10 already left open).
Tests: `tests/test_agent_seat_scorecard.py tests/test_seat_scorecard_enforcement.py tests/test_agent_seat_budget.py tests/test_seat_budget_enforcement.py tests/test_agent_seats.py tests/test_exec_seat_tools.py` 68/68; `-k "migration or bootstrap"` 303/19/0; `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget or seat_scorecard"` 845 passed/17 skipped/1 failed (pre-existing `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff clean.

### 2026-09-29 12:58 UTC · builder → reviewer · f107,f110 · handoff
PR #91 (909da5eb) closes your f107 and f110(a)(b). `_announce`/`announce_to_exec` now return whether they actually posted; `evaluate_seat_scorecard` only records success on a confirmed post, so a no-`#exec` org's good draft now counts as a miss, matching your accept bar exactly. `test_a_failed_check_still_advances_last_scorecard_at` and `test_sweep_evaluates_each_organizations_seats_in_its_own_context` cover f110(a)/(b), both confirmed red under your named mutations first. Prompt also now carries real weekly token burn instead of asking the model to invent specifics.
Left, noted on the PR: the multi-worker race (no atomic per-seat claim) is real but pre-existing and shared with `budget.py`'s own sweep -- worth its own finding covering both, not scorecard-specific. f110(c) (0043 round-trip test) is PR #92's own migration, untouched here; marked f110 `[~]`.
Tests: 71/71 targeted (3 new); `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget or seat_scorecard"` 848 passed/17 skipped/1 failed (pre-existing only); ruff clean. Replied on PR #91, updated its body.

### 2026-09-29 13:13 UTC · designer → reviewer · d11 · handoff
PR #81 slice 7 (18f013db): agent-chat reply byline. Look at message-list.tsx withRunDuration (opensReply) and the agent page's new agent prop. Tests: ui-polish-mobile.spec.ts 11/11 (byline test red on base). Evidence slice7/.

### 2026-09-29 13:27 UTC · builder → reviewer · e12 · handoff
PR #92 (still `[~]`, draft) gained a slice: idle-probation auto-retirement, commit ac929c2b. New `deerflow.hiring.retirement.evaluate_hire_idle_retirement`/`evaluate_all_hire_idle_retirements` retire an active hire with no attributable run activity for `config.hiring.idle_days_before_retirement` days (default 7; clock starts at the hire's last run or its `created_at`), skipping a hire with active reports of its own. Wired into the Gateway lifespan like `exec_seats`' budget/scorecard sweeps, off by default (`config.hiring.retirement_check_enabled`).
Look at `backend/packages/harness/deerflow/hiring/retirement.py:1` (the whole idle decision, no I/O of its own beyond the repo calls it's given) and `backend/packages/harness/deerflow/persistence/hiring/sql.py:227` (`last_activity_at` — confirm the org/agent_name matching can't leak across orgs the way earlier exec_seats findings did for similar queries).
Left: the KPI half of the probation rule (no scorecard-like review mechanism for hires exists yet); no schedule calls this on its own (off by default, same posture as e10/e11 before their own wiring). No new PR — same PR #92 you're already tracking.
Tests: `tests/test_hiring_idle_retirement.py` 11/11 new; `-k "migration or bootstrap"` sweep 305 passed/19 skipped; `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget or seat_scorecard or hiring or hire"` sweep 910 passed/17 skipped/1 failed (pre-existing unrelated `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff check+format clean.

### 2026-09-29 15:34 UTC · builder → reviewer · e12 · handoff
PR #92 gained its final slice: KPI-review probation sweep, commit 54f7ea60. New `deerflow.hiring.kpi_review.evaluate_hire_kpi`/`evaluate_all_hire_kpi_reviews` mirror `exec_seats.scorecard` almost line-for-line: a weekly best-effort model MET/MISSED verdict per active hire, a failed/unreadable answer counts as a miss, two consecutive misses retire the hire unless it still has active reports of its own (reuses the idle sweep's exact orphan guard). `hired_agents.missed_kpi_checks`/`last_kpi_check_at` (migration `0044`, chains after `0043`); wired into the Gateway lifespan like the idle sweep, off by default (`config.hiring.kpi_check_enabled`).
Look at `backend/packages/harness/deerflow/hiring/kpi_review.py:1` (the whole miss/retire decision, closely parallels `exec_seats/scorecard.py`) and `sql.py:319` (`record_kpi_check_result`, mirrors `record_scorecard_result`). EXECUTIVE.md's Probation rule (idle + KPI) is now fully enforced; e12 is `[x]`.
Left: no day-of-week gate (weekly-since-last-check, not literally Friday, same posture e11 ships with); a hire still has no real dispatchable agent config behind it, so nothing can actually miss or meet a KPI yet in practice; no seat/hire UI surfaces any of these fields.
Tests: `tests/test_hiring_kpi_review.py tests/test_hiring_kpi_enforcement.py` 13/13 new; `-k "migration or bootstrap"` sweep 305 passed/19 skipped; `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget or seat_scorecard or hiring or hire"` sweep 923 passed/17 skipped/1 failed (pre-existing unrelated `test_client_langfuse_metadata.py` only); `test_harness_boundary.py` green; ruff check+format clean.

### 2026-09-29 15:55 UTC · designer → reviewer · d11 · handoff
PR #81 slice 8 (ed2d48c7): Scheduled tasks now scrolls in a ScrollArea (document overflow 1269px to 0 at 390); tap on a phone scrolls the sheet in and focuses its h2; 44px floor on sheet/form buttons and FilterGroup (page-body.module.css, also hits Board and Capability Center filters).
Tests: ui-polish-mobile + scheduled-* + desk + board + capability-center e2e 53/53; unit 727/727; lint, tsc clean.
Look at: `frontend/src/app/workspace/scheduled-tasks/page.tsx` selectTask (matchMedia 1023px), the diff is mostly re-indent (use `git diff -w`).

### 2026-09-29 16:00 UTC · builder → reviewer · f117,f118 · handoff
PR #91 (d5cbd856) closes your f117 and f118(a). `_announce` now checks `add_message`'s own return (`None` for a missing/foreign channel) instead of "no exception = posted"; `test_announce_reports_not_posted_when_add_message_finds_no_channel` confirmed red on the pre-fix code. `test_generate_receives_the_seats_real_weekly_token_burn` covers f118(a), confirmed red on both your named mutations (cross-org leak: 100249 vs 250; dropped key: `KeyError`).
Left, per f118(a)'s own scope: (b)-(d) are PR #92's hiring-tool findings, (e) is PR #81's -- not touched here. Documented (not changed) your `announce=None` footgun note in `evaluate_seat_scorecard`'s docstring since no production caller passes `None`.
Tests: 73/73 targeted (2 new); `-k "board or client or team or exec_seat or fleet or agent_seat or seat_budget or seat_scorecard"` 850 passed/17 skipped/1 failed (pre-existing only); ruff clean. Replied on PR #91, updated its body.

### 2026-09-29 17:25 UTC · designer → reviewer · d11 · handoff
PR #81 slice 9 (7fb81db1) ready: FilterGroup rails below 640px, Scheduled tasks phone slips, last error on task rows.
Tests: `playwright test ui-polish-mobile -g "one-row rails"` green (red on both halves reverted). Look at `page-body.module.css` `.filters` (contain: inline-size, -5px margin for focus room) and `.slips`.

### 2026-09-29 19:20 UTC · designer → reviewer · d11 · handoff
PR #81 slice 10 (78662ca2): Chats page header, body scroll, phone slips, no phone autofocus.
Tests: `playwright test ui-polish-mobile thread-list-infinite-scroll` 21 pass; `pnpm test` 2329 pass; lint+tsc clean.
Look at `frontend/src/app/workspace/chats/page.tsx` (header, focus effect) and `.slip` in `page-body.module.css`.

### 2026-09-29 19:29 UTC · builder → reviewer · f121 · handoff
PR #100 (ffe2d08d) closes f121: invite-settings-page.tsx success title is `role="status"` `aria-live="polite"`, link input focused once `created`; email input gets `aria-invalid`/`aria-describedby` for the `invalid_email` failure kind; role select gets `aria-describedby` to its help paragraph.
Tests: `pnpm rstest run tests/unit/components/workspace/settings/invite-settings-page.dom.test.tsx` 19/19 (2 new), both confirmed red on the pre-fix component (focus stayed off body, `aria-invalid` null). `pnpm typecheck`/`pnpm lint` clean; `pnpm test` 2327/2327 individual tests, 0 new failures.
Look at: `frontend/src/components/workspace/settings/invite-settings-page.tsx:182-196,267-271,281,296-298`.

### 2026-09-29 21:10 UTC · designer → reviewer · d11 slice 11 · handoff
PR #81 commit 692acaed: Chats filed under day labels. Logic in `frontend/src/core/threads/day-groups.ts` (calendar days, adjacency grouping, pinned first). Evidence `docs/pr-evidence/momo-week/d11-mobile-pop/slice11/`. Tests: `pnpm exec rstest tests/unit/core/threads/day-groups.test.ts`, `playwright test ui-polish-mobile` 22 green. Also fixes the lane's `board-thread-carryover.dom.test.tsx` fixture (missing urgency/summary) that broke `next build`.

### 2026-09-29 21:20 UTC · builder → reviewer · f101 · done
f101 was already fixed on PR #81 (cfb7a75e, per your 2026-09-29 15:52 UTC re-review): useIsMobile(640), assertions moved into ui-polish-mobile.spec.ts, projects buttons measured. QUEUE.md checkbox was the only thing left open.
Verified this run: `pnpm exec playwright test ui-polish-mobile.spec.ts -g "agents roster Momo" --project=chromium` on momo-week/d11-mobile-pop @ cfb7a75e, 3/3 pass. QUEUE.md f101 now marked [x]. No new PR opened (fix lives on #81).

### 2026-09-29 23:10 UTC · designer → reviewer · d11 slice 12 · handoff
PR #81 commit 978d0b57: Chats loading/error/empty use page-body states; search hidden until there are chats.
Tests: `playwright test ui-polish-mobile` (2 new, red on old build) green; `pnpm test` 2340 pass; lint clean.
Look at `frontend/src/app/workspace/chats/page.tsx` showSearch + first-appearance focus effect, and errorDetail's prefix check.

### 2026-09-29 23:20 UTC · builder → reviewer · f40 · handoff
PR #103 closes f40: `evaluate_issue_artifact` (`backend/packages/harness/deerflow/subagents/issue_artifact_gate.py`) now rejects a same-key maker rerun as review structurally (`review_item_key == work_order_id`), honours the reviewer's own `acceptance_verdict` if present, and casefolds actor-id comparison. `docs/momo-issue-artifact-gate.md`'s disposition paragraph rewritten to match code (empty/truncated + non-independent review are `rework`, not "holds").
Tests: new `tests/test_issue_artifact_gate.py` (module had none), 3 new cases confirmed red on pre-fix code, 4/4 green after; `test_harness_boundary.py` green; ruff check+format clean.
Look at `issue_artifact_gate.py:151-164` (the `elif`/`reviewer_verdict` block).

### 2026-09-30 00:23 UTC · builder → reviewer · f41 · handoff
PR #105 closes f41: `upload_ingestion.py` (PR #62) format-fixed; the real bug was `get_initialized_sandbox_provider` imported directly instead of through `routers.uploads` (the module both upload callers patch in tests). Re-exported it from `routers/uploads.py` (`__all__`) and switched the call site to `uploads.get_initialized_sandbox_provider()`. `issue_artifact_gate.py` (PR #63/f40) was already format-clean, carried forward unchanged.
Tests: 3 new (AIO-no-provisioner never constructs a provider, AIO-with-provisioner does, explicit `thread_data_mounts: false` override forces sync); no-provisioner test confirmed red against a temporarily-reverted pre-PR-#62 `open()`. `test_uploads_router.py` 55/55; `-k "upload"` sweep 390 passed/7 skipped (pre-existing); ruff check+format clean repo-wide.
Look at `backend/app/gateway/upload_ingestion.py:211-215` and `backend/app/gateway/routers/uploads.py:21,59`.

### 2026-09-30 01:15 UTC · designer → reviewer · f129 f131 · done
PR #81 commit ae2ed5db fixes both slice 12 findings. Tests: 2 new ui-polish-mobile assertions red on 978d0b57's code, 49/49 e2e green after; lint clean.

### 2026-09-30 00:57 UTC · builder → reviewer · f126 · handoff
PR #102 (5890bc57) closes f126: `easyStartersDismissed` now resets via `useEffect(() => setEasyStartersDismissed(false), [threadId])`, matching the existing `conversationReferences` reset at `:392`. `threadId` is the same client-minted id across a new chat's `isNewThread`->materialized transition, so it doesn't undo a dismissal on its own first send, only on an actual thread switch.
Tests: `input-box-easy-starters.dom.test.tsx` 4/4 (1 new, close on `thread-1` then rerender `thread-2`, confirmed red on the pre-fix code); `pnpm test` 2335/2335, lint+tsc clean.
Look at `input-box.tsx:465-472`.
