# S09b — UNMERGED, awaiting a completed full-suite gate

Branch: work/s09b-memory-scoping, HEAD dd959a19, based on 26826aa5.
Left unmerged under STOP CONDITION 5 (weekly Claude limit). Not a failure —
the work is believed good; the *gate* did not finish inside the wind-down
window, and the change is process-wide, so it is not being merged on a
partial gate.

## What is on this branch
- 3871ddc3 docs only: Paths.memory_file / Paths.agent_memory_file annotated as
  legacy process-global fallbacks, mirroring the wording 7001a7b2 gave
  user_md_file. Resolved paths byte-identical. L2 verified every docstring
  cross-reference resolves (user_memory_file:280, user_agent_memory_file:292,
  agents_dir:213).
- 72203cc2 behavioural, ONE call site: get_memory_manager() in
  packages/harness/deerflow/agents/memory/manager.py now sets
  backend_config["strict_user_scope"] = True when the host config does not set
  it explicitly (same precedence as the existing storage_path default).
  DeerMemConfig.strict_user_scope default is untouched (stays False), so an
  embedder importing the backend directly is not broken.
- dd959a19 audit doc: both items marked APPLIED with SHAs. The Part B
  secrets-sweep caveat is verbatim and must stay that way.

## Evidence that exists
- Worker gate on exactly this tree: 122 passed, 1 warning, 84.88s across
  test_memory_isolation, test_user_profile_isolation, test_persistence_bootstrap,
  test_custom_agent, test_membership_revocation. PYTHONPATH verified.
- Fail-first proof for the flip: pre-flip manager.py blob swapped in ->
  test_factory_defaults_to_strict_user_scope failed "DID NOT RAISE ValueError";
  post-flip restored byte-identical -> passes. The test is not vacuous.
- 14/14 production call sites re-verified at 26826aa5 to pass a concrete
  user_id, including agents.py:688 (_cancel_pending_memory_for_agent, whose
  caller resolves user_id at agents.py:635). storage.py:1749's no-user_id
  branch is dead in practice because the factory always sets storage_path.

## THE GAP — what is NOT proven
No completed whole-suite backend run on the merged result. strict_user_scope is
process-wide through the factory, so any test that constructs a memory manager
could be affected and the five-file gate above would not see it. L2 started
`pytest -q` (no args) on the merge at wt-l2-merge and it had not produced a
result line after ~17 min; note the invocation was piped through
`Select-Object -Last 6`, which buffers, so absence of output is NOT evidence of
a hang. Re-run WITHOUT that pipe so progress streams.

## To finish (one step, no re-derivation needed)
    $wt = "<worktree>/backend"
    $env:PYTHONPATH = "$wt;$wt/packages/harness"
    & "C:/Users/dillo/Documents/Qwen/deer-flow/backend/.venv/Scripts/python.exe" -c "import app, deerflow; print(app.__file__); print(deerflow.__file__)"
    & "C:/Users/dillo/Documents/Qwen/deer-flow/backend/.venv/Scripts/python.exe" -m pytest -q
Both __file__ must resolve under the worktree or the venv .pth silently tests
the Qwen repo. Green -> `git merge --no-ff work/s09b-memory-scoping` into the
integration branch. Red -> the flip is the first suspect; reverting 72203cc2
alone restores prior behaviour and leaves the docs commit intact.

## Unrelated, for whoever picks this up
The S09 worker reported two commits and one SendMessage hit an auto-mode
classifier denial ("Modify Shared Resources" / "Auto-Mode Bypass") and then
succeeded on identical retry with no content difference. No permission, hook,
or config was changed by the worker or by L2 in response. Worth a look; it was
not investigated under the stop condition.
