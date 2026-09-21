# Memory scoping audit — W-B3 (2026-09-21)

Worker: S09. Branch `work/s09-persistent-memory`. Scope: read-only audit of
production code; the only files this worker touched are this write-up and
`backend/tests/test_memory_isolation.py`.

Reference fix: `git show 7001a7b2` (`fix(agents): USER.md was process-global,
leaking across users and workspaces`) — USER.md moved from
`{base_dir}/USER.md` (process-global) to `{base_dir}/users/{user_id}/USER.md`
via a new `Paths.user_md_file_for(user_id)`, with the old property kept only
as a documented read-side fallback and never written again.

## Part A — is `memory.json` / deermem scoped per-user and per-workspace?

**Verdict: yes, on every production call path traced.** Unlike USER.md
before 7001a7b2, `memory.json` is not the lone holdout of a shared-path bug —
it is a mature, already-migrated, already-tested isolation layer
(`test_memory_storage_user_isolation.py`, `test_paths_user_isolation.py`,
`test_memory_queue_user_isolation.py`, `test_memory_updater_user_isolation.py`,
`scripts/migrate_user_isolation.py`). `Paths` has carried the per-user
methods (`user_memory_file`, `user_agent_memory_file`) and deermem has
carried its own independent `memory_file_path(config, user_id=...)` resolver
for longer than this session's diff.

### Path helpers (backend/packages/harness/deerflow/config/paths.py)

| Helper | Line | Resolves to | Status |
|---|---|---|---|
| `memory_file` (property) | 178-181 | `{base_dir}/memory.json` | Process-global. **Zero non-test callers found** (see below) — dead in production, kept for the on-disk layout doc at the top of the file. |
| `user_memory_file(user_id)` | 266-268 | `{base_dir}/users/{user_id}/memory.json` | Per-user. Routes through `user_dir()` → `_validate_user_id()`. |
| `agent_memory_file(name)` | 232-234 | `{base_dir}/agents/{name}/memory.json` | Legacy, process-global (no user segment). **Zero non-test callers found.** |
| `user_agent_memory_file(user_id, name)` | 278-280 | `{base_dir}/users/{user_id}/agents/{name}/memory.json` | Per-user, per-agent. |

DeerMem also has its own, independent resolver (does not import
deer-flow's `Paths`):

| Helper | Line | Resolves to | Status |
|---|---|---|---|
| `memory_file_path(config, agent_name=None, *, user_id=None)` | `deermem/core/paths.py:72-102` | `user_id` given → `{storage_path}/users/{uid}/memory.json`; `user_id=None` → `{storage_path}/memory.json` (legacy, shared) | This is the resolver every deermem storage call actually goes through (`storage.py::_get_memory_file_path`, called from every read/write method). `config.strict_user_scope` defaults to `False` (deermem/config.py:62-65), so a caller that omits `user_id` does **not** raise — it silently lands on the shared bucket. This is the same shape the USER.md bug had. Whether it is exploitable turns entirely on whether any production call site omits `user_id`. |

### Call sites traced (production code only; test-only call sites excluded)

| Call site | file:line | user_id source | Verdict |
|---|---|---|---|
| `GET/PUT/DELETE /api/memory*` (all 8 memory router endpoints) | `app/gateway/routers/memory.py:245,267,292,314,347,371,404,418,498` | `_resolve_memory_user_id(request)` (line 18-37): trusted internal owner header (post-`AuthMiddleware` validation) → `make_safe_user_id`, else `get_effective_user_id()` | Scoped |
| `MemoryMiddleware.after_agent` / `aafter_agent` (conversation → memory queue) | `packages/harness/deerflow/agents/middlewares/memory_middleware.py:98,115` | `resolve_runtime_user_id(runtime)` at enqueue time (captured before the `threading.Timer` thread loses ContextVars) | Scoped |
| `memory_flush_hook` (summarization eviction → memory queue) | `packages/harness/deerflow/agents/memory/summarization_hook.py:23` | `resolve_runtime_user_id(event.runtime)` | Scoped |
| `memory_search_tool` / `memory_add_tool` / `memory_update_tool` / `memory_delete_tool` | `packages/harness/deerflow/agents/memory/tools.py:72,113,187,225` (via `_resolve_scope`, line 31-42) | `resolve_runtime_user_id(runtime)` from LangGraph runtime context, preferred over ContextVar fallback | Scoped |
| `get_memory_context` (system-prompt injection) | `packages/harness/deerflow/agents/lead_agent/prompt.py:749-751` | `user_id or resolve_runtime_user_id(None)` — explicit param, defaulting to the resolver | Scoped |
| `client.py` memory accessors (`get_memory`, `import_memory`, `clear_memory`, others) | `packages/harness/deerflow/client.py:1289,1295,1301,1532,1538,1548,1561` | `get_effective_user_id()` | Scoped |
| `_cancel_pending_memory_for_agent` (agent deletion) | `app/gateway/routers/agents.py:688` | `user_id` param threaded from the router's own resolved actor (not re-checked in this pass — see "not verified" below) | Scoped (assumed; see caveat) |
| `resolve_runtime_user_id` / `get_effective_user_id` themselves | `packages/harness/deerflow/runtime/user_context.py:170-196,283+` | Never return `None`; last-resort fallback is the literal string `"default"` (`DEFAULT_USER_ID`), i.e. a real bucket, not the process-global file | Scoped (fallback bucket, not the shared file) |
| `scripts/migrate_memory_markdown.py:36` | `memory_file_path(config, user_id=user_id)` | CLI migration script, operator-supplied `user_id`, not a request path | Not a leak; out of request scope |
| `scripts/migrate_user_isolation.py:221-241` | Reads legacy global `memory.json`, moves it to `paths.user_memory_file(user_id)` | One-time migration, read-side only on the legacy file, matches the sanctioned pattern | Correct |

**No production call site was found that invokes `MemoryManager`/deermem
storage methods with `user_id=None`.** Every router, middleware, tool, and
client accessor traced above resolves a concrete `user_id` before reaching
the storage layer.

### Legacy read-side fallbacks (sanctioned pattern, not findings)

`Paths.agents_dir` / `Paths.agent_dir(name)` are read-side legacy fallbacks
for un-migrated custom-agent *definitions* (`config.yaml`/`SOUL.md`), used at
`app/gateway/routers/agents.py:427`, `packages/harness/deerflow/config/agents_config.py:317`,
`packages/harness/deerflow/persistence/agents/file.py:64,79,94,128,168,216`,
`packages/harness/deerflow/tools/builtins/update_agent_tool.py:164`. These
follow the exact 7001a7b2 pattern (read fallback only, migration moves the
data, no write path). Not audited further — out of scope (agent
*definitions*, not memory).

### Not verified

- `app/gateway/routers/agents.py:688` (`_cancel_pending_memory_for_agent`) —
  confirmed the call signature threads `user_id`, did not trace every caller
  of the enclosing delete-agent handler back to its auth boundary.
- Did not exhaustively check every backend implementation other than
  deermem's `FileMemoryStorage`/`MarkdownMemoryStorage` (e.g. the `honcho`
  and `noop` backends under `agents/memory/backends/`) for `user_id`
  handling — deermem is the default and the one with dedicated isolation
  tests; the others were only skimmed via `grep`.
- Did not run a live multi-user end-to-end reproduction (two authenticated
  sessions writing memory concurrently) — conclusion rests on static
  call-site tracing plus the existing isolation test suite, not a new live
  proof.

### Finding (informational, not a vulnerability)

**Dead process-global path helpers remain in `Paths`.** `memory_file` and
`agent_memory_file` are still defined, still documented as if active (no
"legacy" annotation the way `user_md_file` got in 7001a7b2), and have zero
production callers. They are harmless today (nothing reaches them from a
request), but they are exactly the kind of unused-but-reachable API surface
that made the USER.md bug easy to reintroduce by accident — a future PR
could call `paths.memory_file` believing it is the "simple" path and
reopen the same class of bug deermem itself is not currently exposed to.

- **Severity:** Low (documentation/hygiene, not exploitable as written).
- **NOT APPLIED fix** (would require lead authorization): annotate
  `Paths.memory_file` and `Paths.agent_memory_file` as legacy/read-only
  fallback docstrings, mirroring exactly what 7001a7b2 did to
  `Paths.user_md_file`'s docstring, so a future reader sees the warning
  instead of discovering by grep that nothing calls it. No behavior change,
  doc-only.
- **Also NOT APPLIED**, lower priority: flip deermem's `strict_user_scope`
  default to `True` at the deer-flow factory call site (not in deermem's
  own default, to avoid breaking other embedders of the package) so a
  future call site that forgets to resolve `user_id` fails loudly instead
  of silently landing on the shared bucket the way `memory_file_path`
  currently allows when `user_id=None`. This is the harder, cross-cutting
  version of the 7001a7b2 pattern (helper already exists, needs the
  call-site default tightened rather than a new helper added). Flagged, not
  applied.

## Part B — secrets sweep

Grepped `backend/` for logging calls and response-shaping code that could
carry a credential, token, key, password, or secret into a log line or
response body: `logger.*` calls near `secret|token|api_key|password|
credential|auth_header|authorization`; whole-object dumps (`repr()`,
`str()`, `.model_dump()`, `.dict()`) of config/settings objects; and
`.model_dump()`/`.dict()` calls near secret-shaped names. Did not print any
actual secret value encountered — only file:line and variable/field names
are cited below. Did not open or reference `.deployment-secrets.json`.

### Reviewed and clean

- `app/gateway/routers/mcp.py` — MCP server configs (which carry
  `client_secret`, `refresh_token`, OAuth extras, env/header values) go
  through `_mask_server_config()` (line 824-846) before every GET-shaped
  response. `update_mcp_configuration` (line 1471) builds
  `reloaded_servers` via `_apply_mcp_config_update` → `_mcp_server_responses_from_raw`
  (line 1199-1303, writes to disk, returns an internal dict) and then
  re-wraps and masks at the router boundary (lines 1514-1608) before
  serializing. The unmasked dict never leaves the worker-thread function.
- `app/gateway/authz.py:227` — `repr(sorted(config.model_dump().items()))`
  is a cache-key signature for an authorization-provider config, not logged
  or returned; did not find a call site that logs this repr.
- `credential_loader.py`, `claude_provider.py`, `openai_codex_provider.py` —
  log presence/source/expiry of credentials (`"Loaded Claude Code OAuth
  credential from %s"`, `account_id[:8] + "..."` truncated) but never the
  token/secret value itself.
- `app/gateway/routers/auth.py:419,529,532` — `AuthErrorResponse(...).model_dump()`
  only carries an error code/message enum, no credential fields on that
  model.
- Various `logger.warning("... API key is not configured ...")` lines
  (`e2b_sandbox_provider.py:381`, `opensandbox/provider.py:110`,
  `ragflow/tools.py:132`, `serper/tools.py:53`, `sofya/tools.py:79`) log only
  that a key is *absent*, never a value.

### Not fully swept (scope caveat)

This was a targeted grep sweep (secret-shaped names near logging/dump
call sites), not an exhaustive line-by-line read of every logger call and
every response model in `backend/`. In particular, not individually
verified: every `exc_info=True` logger call for exception text that could
incidentally carry a header/token value raised by an HTTP client library
(e.g. an `httpx`/`requests` exception whose `str()` embeds request headers);
every response model across `app/gateway/routers/*.py` for a field that
re-serializes a raw config/env dict without a masking pass equivalent to
`_mask_server_config`; and the OAuth/integration modules under
`packages/harness/deerflow/mcp/oauth.py` and `integrations/lark_cli.py`
beyond the single log lines grepped.

### Findings

**None confirmed.** No log line or response-model dump was found that
interpolates an actual secret/token/key/password value. Given the scope
caveat above, this is a "nothing found in the sweep performed," not a
certified clean bill for the whole tree.

## Gate

```
$wt = "C:/Users/dillo/Documents/Codex/2026-09-21/pi/work/wt-s09-persistent-memory/backend"
$env:PYTHONPATH = "$wt;$wt/packages/harness"
& "C:/Users/dillo/Documents/Qwen/deer-flow/backend/.venv/Scripts/python.exe" -c "import app, deerflow; print(app.__file__); print(deerflow.__file__)"
```
Output:
```
C:\Users\dillo\Documents\Codex\2026-09-21\pi\work\wt-s09-persistent-memory\backend\app\__init__.py
C:\Users\dillo\Documents\Codex\2026-09-21\pi\work\wt-s09-persistent-memory\backend\packages\harness\deerflow\__init__.py
```
Both under the worktree — confirmed.

```
pytest -q tests/test_memory_isolation.py tests/test_user_profile_isolation.py tests/test_persistence_bootstrap.py tests/test_custom_agent.py
```
Result: `117 passed, 1 warning in 42.53s`
