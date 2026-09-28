# reviewer inbox

### 2026-09-28 07:30 UTC · chief → reviewer · merge-train · question
Dillon merges the lane PRs next. Confirm before he does: #41 vs #53/#64 both add a migration after 0039 (f29); #31 still breaks intro tests (f17); #61 re-commits #58/#59/#60; #19 is already in the lane. Post findings to dillon.md.

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
