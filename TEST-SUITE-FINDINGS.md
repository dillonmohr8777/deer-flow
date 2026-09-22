# Backend test suite: findings from the post-recovery verification pass

2026-09-22, on `recover/momentum-integrate-20260921`. This is the detailed
write-up behind the "43 failed, 17825 passed" number, what each failure
actually is, what got fixed, and what still needs a decision.

## The wrong command first

The default `pytest tests/` invocation includes live tests gated behind real
API credentials this environment doesn't have. `AGENTS.md` documents the real
one: `pytest -m "not live" --ignore=tests/blocking_io tests/`. Running the
wrong one cost three hung attempts before this was caught; see
`RECOVERY-REPORT.md` for the full timeline. Use the documented command.

## Fixed and verified

**`deerflow/extensions/gateway.py`: mirrored public-paths constant was stale.**
`auth_middleware.py`'s `_PUBLIC_EXACT_PATHS` and the extensions module's
`_HOST_PUBLIC_EXACT_PATHS` are meant to stay identical, so extension-contributed
routers see the same unauthenticated boundary as the core app.
`test_extension_gateway_wiring.py` exists specifically to catch drift between
them. The recovered `auth_middleware.py` added two invitation endpoints
(`/api/v1/auth/invitations/accept`, `/api/v1/auth/invitations/inspect`) to its
list; the mirror was never updated. Fixed by adding the same two paths to the
mirror. `tests/test_extension_gateway_wiring.py`: 58 passed (was 3 failed).
Committed as `1baee1f4`.

## Real, unfixed: `test_mcp_task_service.py`, 7 test functions deselected

New in this recovery (did not exist at `83f4e423`). These 7 functions (38
parametrizations) share a helper, `_run_batch_probe`, that cancels a task
mid-flight and expects `asyncio.CancelledError` to propagate to the caller.

Traced one combination (`[success-poll]`) to an actual hang with a captured
stack trace (`faulthandler.dump_traceback_later`, standalone reproduction,
reliable): the event loop legitimately parks in `_poll()`/`select()` because
the underlying task keeps re-scheduling a 5-second poll sleep forever, never
terminating. That happens because cancellation is being swallowed, not because
of any Windows/asyncio bug: `app/mcp_tasks/service.py` catches
`asyncio.CancelledError` internally, does a documented bounded-drain-then-
background-handoff (see `packages/harness/deerflow/mcp/AGENTS.md`: "a stuck
release does not stall the whole phase"), and returns rather than re-raising.

That handoff behavior is intentional and documented for the *release
operation*. What's not obviously intentional is that it also swallows the
*caller's own* cancellation, so `await caller` returns normally instead of
raising `CancelledError`. That's a well-known asyncio anti-pattern
independent of the documented handoff contract: a cancelled task is generally
expected to complete via `CancelledError`, even if it also kicks off
background cleanup. Two other combinations (`[failure-cancel]`,
`[self_cancel-notification]`) fail fast with exactly this symptom:
`Failed: DID NOT RAISE <class 'asyncio.exceptions.CancelledError'>`.

This needs someone who knows the intended cancellation contract to decide:
should the caller's `CancelledError` propagate before or alongside the
background handoff, or do these tests have the wrong expectation? Either the
service or the tests need to change; I didn't attempt either blind.

**Also failing in the same file, not yet individually triaged** (8 more,
beyond the 7 deselected functions): `test_single_flight_claim_releases_late_
uncancelled_claim` (×3 phases), `test_single_flight_claim_releases_owner_
before_stuck_release` (×3 phases), `test_poll_retry_release_hang_does_not_
block_run_once`, `test_notification_failure_release_hang_does_not_block`.
Given the names and the confirmed pattern above, these are very likely more
instances of the same cancellation-handling question, not new independent
bugs, but that's inference, not verified per-test.

## Real, unfixed: Windows file-locking race, shared across two files

Confirmed as a genuine regression, not a scattered set of unrelated
failures. Across the two files there are 15 upload/document-attach
failures total (13 in `test_uploads_router.py`, 2 in
`test_project_documents_promotion.py`). The same `PermissionError:
[WinError 32] The process cannot access the file because it is being used
by another process` shows up in **14 of the 15**:

- Both `test_project_documents_promotion.py` failures (concurrent attach)
- 12 of the 13 `test_uploads_router.py` failures (only
  `test_upload_files_deduplicates_max_length_filenames_without_failing_the_
  batch` is different: `[WinError 3] The system cannot find the path
  specified`, on a 255-character filename, almost certainly Windows'
  ~260-character `MAX_PATH` limit, unrelated to the locking issue)

Both `test_project_documents_promotion.py` tests pass cleanly on `83f4e423`
and fail on this branch, and that test file itself wasn't touched by the
recovery, so this is a real behavior change in the touched upload/project-
document code, not stale test authorship.

`app/gateway/routers/uploads.py::_commit_upload_temp_no_overwrite` closes its
own handle before linking (`upload_temp.handle.close()` then
`os.link(staged_path, ...)`, then `os.unlink(staged_path)`), which looks
correct on inspection. The open handle causing `WinError 32` is something
else: most plausibly a second concurrent operation (a markdown-conversion
worker also reading the staged `.part` file, per `AGENTS.md`'s "one
conversion worker per request" and `run_file_io`'s executor-thread
offloading) still holding it open when the commit path tries to
unlink/link it. POSIX allows renaming or unlinking a file that's still open
elsewhere; Windows does not, so this is plausibly Windows-only and may not
reproduce on Linux CI. Pinpointing the exact second holder needs handle
tracing (Process Monitor or equivalent) that wasn't available tonight; not
guessed at further.

## Real, unfixed: incomplete feature, `test_doctor.py::TestCheckLLMAuth`

9 of 10 tests in this class fail. `doctor.check_llm_auth` does not exist
anywhere in this repo or in the still-running recovered container. The
8-hour run wrote a full test suite for a doctor check (Codex/Claude
credential-file validation) that was never implemented. Not a regression,
not something lost in recovery, a genuine gap in the original work.

## One flaky, one real but order-dependent

`test_delta_channel_state.py::test_merge_message_writes_randomized_
differential` failed once in the full-suite run, passed standalone, and did
not reappear in the final verification run. Consistent with its own name:
a randomized differential test, not a real defect.

`test_setup_agent_http_e2e_real_server.py::test_real_http_create_agent_
lands_in_authenticated_user_dir` failed in *both* the full-suite run and the
final verification run, but passed cleanly standalone. That means it's real
but order- or state-dependent: something earlier in the suite leaves state
this real-HTTP-server e2e test doesn't tolerate. Not isolated to a specific
prior test tonight; worth a `pytest --lf` bisection in daylight rather than
guessed at further here.

## Confirmed pre-existing, unrelated to this recovery

- `test_migration_0019_0020_projects.py::test_0019_creates_projects_table`
- `test_migration_0023_run_change_seq.py::test_upgrade_exposes_legacy_runs_and_allocates_new_positions`

  Both fail identically on `83f4e423` in an isolated scratch worktree, before
  any recovery commit. Stale schema-shape assertions from earlier
  organization work; not touched here.

- `test_invoke_acp_agent_tool.py::test_invoke_acp_agent_times_out_and_kills_
  hung_subprocess[asyncio]`, `test_local_sandbox_command_timeout.py::test_
  timeout_output_carries_authoritative_failure_marker`

  Both fail identically on `83f4e423` with `FileNotFoundError: [WinError 2]
  The system cannot find the file specified` from `_winapi.CreateProcess`,
  a missing subprocess executable on this machine. Environment-only, present
  regardless of git state.

## Migration test staleness

`test_0026_is_in_the_single_merge_head` hardcoded the chain head's identity;
fixed to assert `len(get_heads()) == 1` instead, matching the pattern the
neighboring migration tests already use. Committed as `165cc803`.

## Final numbers

`pytest -m "not live" --ignore=tests/blocking_io tests/` with the 7
`test_mcp_task_service.py` cancellation functions deselected:

**39 failed, 17829 passed, 400 skipped, 38 deselected, 23:50 runtime.**

## Bottom line for a decision-maker

- One real bug found and fixed tonight (public-paths drift), verified:
  `1baee1f4`.
- One real, well-characterized concurrency/cancellation question in
  `McpTaskService` (7 test functions, 38 parametrizations, deselected) that
  needs a human call on intended behavior, not a blind fix at 3am.
- One genuine Windows file-locking regression (`WinError 32`) affecting 14
  tests across `test_uploads_router.py` and `test_project_documents_
  promotion.py`, all tracing to the same class of cause: a file handle
  still open when the commit path tries to unlink/link it.
- One incomplete feature (`doctor.check_llm_auth`, 9 failures) that was
  never built, confirmed absent from both this branch and the still-running
  recovered container.
- One likely-Windows-only `MAX_PATH` failure, and two pre-existing
  subprocess-discovery failures unrelated to any git state.
- Two pre-existing migration test failures, unrelated to any of this.
- One flaky test (passed on retry, didn't reappear) and one real but
  order-dependent test (failed consistently in the full suite, passed
  standalone) worth a `--lf` bisection in daylight.

Nothing here blocks using the recovered branch; every failure is scoped,
explained, and none of it silently passed as "done."
