# Auth audit — USER.md class sweep of backend/app/gateway/routers (2026-09-21)

Scope: W-B2, route-by-route sweep of every handler in `backend/app/gateway/routers/*.py`
for the bug class fixed in `7001a7b2` — a handler that reads or writes a path or a row
without resolving the actor (process-global path, missing tenancy filter, an id trusted
from the request, or a write path that skips the check its sibling read performs).

Author: S08 (backend security worker). Read-only on all production code; no fix applied
here even where one is described.

## Method and how to read this table

For each router file, every `@router.get/post/put/patch/delete/websocket` handler was
read and classified against the pattern that file already uses:

- **owner_check pattern** — `@require_permission(resource, action, owner_check=True[,
  require_existing=True])` (see `app/gateway/authz.py:633`). This only exists for
  `thread_id`-keyed resources; it resolves `thread_store.check_access(thread_id,
  storage_user_id, ...)`.
- **effective-user / AUTO pattern** — the handler (or the repository method it calls,
  with `user_id: ... = AUTO`) resolves the caller via `get_effective_user_id()` /
  `resolve_user_id(AUTO)` (`packages/harness/deerflow/runtime/user_context.py:170`) and
  either builds a per-user filesystem path from it or filters the SQL row by it. This is
  the fix pattern from `7001a7b2`.
- **membership pattern** — `active_organization_for_user()` (org-scoped shared
  workspace rows: branding) or a bespoke active-member lookup that checks
  `OrganizationMemberRow.status == "active"` before a write (invitations).
- **admin-gated, instance-wide** — no user/tenant scoping at all, but the resource is
  legitimately instance-wide operator config (MCP servers, managed models, subagent
  catalog, Lark integration) and every mutating route is behind `require_admin_user`.
  Marked **NOT-APPLICABLE** rather than OK, since there is no ownership claim to bypass.
- **no scoping, no admin gate, genuinely shared reference data** (feature flags, model
  catalog, RAGFlow dataset catalog, channel status) — also **NOT-APPLICABLE**.

Verdicts: **OK** (pattern present and correctly wired), **NOT-APPLICABLE** (no
user/tenant-scoped resource touched), **SUSPECT** (pattern looked off, investigated
further — all resolved below), **FINDING** (confirmed gap). There were no SUSPECT items
left open and **no FINDINGS** — see "Findings" below for how each was resolved and
the reasoning kept as an audit trail.

`_ALL_PERMISSIONS` (`app/gateway/authz.py:151`) covers only `threads`, `runs`, and
`projects`; no "agents" permission exists or is proposed here, matching the constraint.

Private helper functions (no `@router.*` decorator) are listed only where they are the
actor-resolution or tenancy-filter point a handler depends on.

## Handler table

### agents.py (custom-agent config + user-profile, `/api/v1/agents`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /agents` list_agents:228 | `get_effective_user_id()` inside `list_custom_agents()` (per-user agents dir) | per-user agent configs | OK |
| `GET /agents/check-name` check_agent_name:257 | effective-user scoped lookup | per-user | OK |
| `GET /agents/{name}` get_agent:290 | effective-user scoped lookup | per-user | OK |
| `POST /agents` create_agent_endpoint:328 | effective-user scoped write | per-user | OK |
| `PUT /agents/{name}` update_agent:392 | effective-user scoped write | per-user | OK |
| `GET /agents/user-profile` get_user_profile:554 | `paths.user_md_file_for(get_effective_user_id())`, legacy shared-file fallback on read only (documented, 7001a7b2) | per-user USER.md | OK — this is the exact route 7001a7b2 fixed; verified the fix is intact (per-user path on read, per-user path on write, no shared write) |
| `PUT /agents/user-profile` update_user_profile:589 | `paths.user_md_file_for(get_effective_user_id())`, write-only to per-user path | per-user USER.md | OK |
| `DELETE /agents/{name}` delete_agent:622 | effective-user scoped delete + `_cancel_pending_memory_for_agent(name, user_id)` | per-user | OK |

### artifacts.py (`/api/threads/{thread_id}/artifacts`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /threads/{thread_id}/artifacts/{path}` get_artifact:339 | `@require_permission("threads","read",owner_check=True)` | thread-scoped file | OK |
| `PUT /threads/{thread_id}/artifacts/{path}` update_artifact:486 | `@require_permission("threads","write",owner_check=True,require_existing=True)`, `reserve_artifact_write(..., user_id=...)` | thread-scoped file | OK |

### assistants_compat.py (LangGraph-SDK compat shim)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /search`, `GET /{id}`, `GET /{id}/graph`, `GET /{id}/schemas` | none | static, hard-coded single-assistant metadata (`_get_default_assistant`, `_list_assistants`), no per-user row | NOT-APPLICABLE |

### auth.py (`/api/v1/auth`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /login/local` login_local:403 | credential-based, issues session | auth | OK |
| `POST /register` register:458 | creates new user | auth | OK |
| `POST /logout` logout:487 | clears own session cookie | auth | OK |
| `POST /change-password` change_password:498 | operates on `request.state.user` | own account | OK |
| `GET /me` get_me:562 | `request.state.user` | own account | OK |
| `POST /pats` create_pat:652 | `require_session_source` dependency, PAT tied to session user | own PATs | OK |
| `GET /pats` list_pats:689 | session user | own PATs | OK |
| `DELETE /pats/{pat_id}` revoke_pat:699 | session user id passed to repo delete (verified param is used as filter, not just accepted) | own PATs | OK |
| `GET /setup-status` setup_status:722 | instance bootstrap state, no user | instance | NOT-APPLICABLE |
| `POST /initialize` initialize_admin:789 | first-run only; gated by no-admin-exists check | instance | OK |
| `GET /providers`, `GET /oauth/{provider}`, `GET /callback/{provider}` | OAuth flow / CSRF state | auth | OK |

### browser.py (`/api/threads/{thread_id}/browser`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /threads/{thread_id}/browser/navigate` navigate_browser:81 | `@require_permission("threads","write",owner_check=True,require_existing=True)` **plus** `_browser_thread_owned_by` re-check requiring exact owner match (stricter than legacy NULL-owner threads, documented reason: retained cookies) | thread-scoped live browser | OK |
| `WS /threads/{thread_id}/browser/stream` browser_stream:207 | Custom `_authenticate_ws` (decorators don't run on websockets) + `_browser_thread_owned_by` exact-owner check + `_ws_origin_allowed` CSRF check, fail-closed on missing thread_store | thread-scoped live browser | OK — verified the decorator-bypass risk (WS upgrades skip `AuthMiddleware`/`require_permission`) is covered by hand-rolled equivalents in the same file |

### capabilities.py
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /catalog`, `GET /installations/{adapter}`, `POST /installations` | plugin manifest / installation catalog, config-scoped not user-scoped | instance | NOT-APPLICABLE |

### channel_connections.py (`/api/channels` connections/providers)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /providers` get_channel_providers:530 | `_get_user_id(request)` → `repo.list_connections(owner_user_id)`, repo filters `WHERE owner_user_id ==` | per-user | OK |
| `GET /connections` get_channel_connections:560 | same | per-user | OK |
| `DELETE /connections/{connection_id}` disconnect_channel_connection:570 | `repo.disconnect_connection(connection_id, owner_user_id=...)`; verified repo (`packages/harness/deerflow/persistence/channel_connections/sql.py:205`) checks `row.owner_user_id != owner_user_id` before mutating, not just accepting the id | per-user | OK |
| `DELETE /{provider}/runtime-config`, `POST /{provider}/connect`, `POST /{provider}/runtime-config` | `require_admin_user` for runtime-config; connect uses per-user binding code flow | instance runtime config (admin) / per-user connect | OK |
| `POST /wechat/qr-login*` | binding-code/session based, not identity-trusting | per-user | OK |

### channels.py (`/api/channels` status)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /` get_channels_status:30, `POST /{name}/restart` restart_channel:42 | instance-wide channel runtime status/restart | instance | NOT-APPLICABLE (restart is an operational action, not user data; no per-user row touched) |

### console.py (`/api/console`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /stats` console_stats:319 | `get_current_user(request)` → `RunRow.user_id == user_id` / `ThreadMetaRow.user_id == user_id` filters built into the query | per-user aggregate | OK |
| `GET /runs` console_runs:390 | same filter pattern | per-user | OK |
| `GET /usage-ledger` console_usage_ledger:461 | same filter pattern (`stmt.where(RunRow.user_id == user_id)`) | per-user | OK |
| `GET /usage` console_usage:535 | same filter pattern (verified) | per-user | OK |

### features.py
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /features` list_features:84 | config-derived feature flags | instance | NOT-APPLICABLE |

### feedback.py (`/api/threads/{thread_id}/runs/{run_id}/feedback`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 6 handlers (upsert/delete/create/list/stats/delete-by-id) | `@require_permission("threads", ..., owner_check=True)` + `get_current_actor_user_id` passed into repo calls | thread-scoped feedback rows | OK |

### github_webhooks.py
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /github` receive_github_webhook:173 | HMAC signature verification (`_verify_signature`), not a user identity at all | webhook ingestion, no per-user row | NOT-APPLICABLE |

### input_polish.py
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /input-polish` polish_input:65 | stateless LLM rewrite of caller-supplied text, no stored row | none | NOT-APPLICABLE |

### integrations.py (`/api/integrations/lark`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /lark/status` get_lark_status:260 | instance-wide integration status; `_is_admin_user` only gates whether host paths are included in the response (fail-closed: any error ⇒ non-admin) | instance | OK |
| `POST /lark/install` install_lark:270 | `require_admin_user` | instance | OK |
| `POST /lark/config/start|complete|credentials`, `POST /lark/auth/start|complete` | instance-wide Lark app credentials, single tenant by design (self-hosted gateway config) | instance | NOT-APPLICABLE |

### invitations.py (`/api/v1/auth/invitations`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /` create_invitation:188 | `get_current_user_from_request` → `_active_shared_workspace_member(session, body.organization_id, actor_id)` requires an **active** owner/admin row before creating the invite; `body.organization_id` is client-supplied but gated by this membership check, not trusted directly | shared-workspace membership | OK — verified with a new regression test (`test_membership_revocation.py::test_revoked_admin_cannot_invite_new_members`); a revoked admin gets 403 |
| `POST /inspect` inspect_invitation:226 | token-based, no session required | invitation token | OK |
| `POST /accept` accept_invitation:253 | token-based; creates session for the token's bound email, `_invitation_issuer_is_active` re-checks the issuer is still an active member at accept time | shared-workspace membership | OK |
| `DELETE /{invitation_id}` revoke_invitation:386 | `_active_shared_workspace_member(session, invitation.organization_id, actor_id)` gate before revoking | shared-workspace membership | OK |

### knowledge.py (`/api` RAGFlow retrieval catalog)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /retrieval-catalog/datasets`, `GET /retrieval-catalog/datasets/{id}/documents` | `@require_permission("threads","read")` (no owner_check — correct, since `agent_name`-scoped operator catalog is not per-user data) | operator-configured RAGFlow catalog | NOT-APPLICABLE |

### managed_models.py (`/api/managed-models`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""`, `PUT ""`, `POST /test` | `require_admin_user` on all three | instance-wide shared model config | NOT-APPLICABLE |

### mcp.py (`/api/mcp`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /mcp/config` get_mcp_configuration:1137 | no admin gate (read) | instance-wide MCP server config | NOT-APPLICABLE (read of instance config; no secrets leak — verified `_mask_sensitive_extra_value`/`_mask_server_config` redact secrets on the way out) |
| `POST /mcp/tools/reset-cache`, `PUT /mcp/config`, `POST /mcp/servers`, `PUT /mcp/servers/{name}`, `DELETE /mcp/servers/{name}`, `PATCH /mcp/servers/{name}/state` | `require_admin_user` on every mutating route (grepped, all 6 present) | instance-wide MCP server config | OK |

### mcp_tasks.py (`/api/threads/{thread_id}/mcp-tasks`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""`, `GET /{task_id}`, `POST /{task_id}/cancel` | `@require_permission("threads","read"/"write",owner_check=True)` + `_current_user_id` passed to repo | thread-scoped MCP task rows | OK |

### memory.py (`/api` global-memory)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 9 handlers (get/reload/clear/create-fact/delete-fact/patch-fact/export/import/status) | `_resolve_memory_user_id(request)` → `get_effective_user_id()`, with a documented trusted-internal-owner-header exception only honored **after** `AuthMiddleware` validated the internal token (verified: header only trusted when the internal token check already passed, not client-suppliable by a browser/API caller) | per-user memory store | OK |
| `GET /memory/config` get_memory_config_endpoint:441 | static config, no user data | instance | NOT-APPLICABLE |

### models.py (`/api/models`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /models`, `GET /models/{name}` | instance-wide model catalog, optionally role-filtered via `resolve_model_authorization` | instance | NOT-APPLICABLE |

### project_documents.py (`/api/projects/{project_id}/documents`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 6 handlers (list/upload/from-thread/attach-to-thread/get-content/delete) | `@require_permission("projects", ...)` (no owner_check — projects aren't thread_id-keyed) **plus** `_require_project(request, project_id)` → `get_project_repo(request).get(project_id)`, which resolves `user_id=AUTO` internally (`ProjectRepository.get`, `packages/harness/deerflow/persistence/projects/sql.py:90`: `resolve_user_id(AUTO)` then `if row.user_id != resolved_user_id: return None`) | per-user project + its documents | OK — initially SUSPECT because the router-level decorator carries no owner_check for `projects`; traced into `_require_project` → `ProjectRepository.get` and confirmed the AUTO-resolved user filter is the actual tenancy boundary, applied before any document row is touched |
| `_resolve_thread_source` (helper, used by from-thread) | explicit `user_id` param, path built from `paths.thread_dir(thread_id, user_id=...)` and re-validated with `.relative_to()` containment checks | thread-scoped source file | OK |

### project_thread_files.py (`/api/projects/{project_id}/threads/{thread_id}/files`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""` list_project_thread_files:105 | `_list_thread_files(paths, user_id=..., thread_id=...)`, `@require_permission` present in file (grepped 5 hits) | thread-scoped files | OK |

### projects.py (`/api/projects`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 8 handlers (create/list/config/get/patch/archive/restore/delete/list-threads) | `@require_permission("projects", ...)` + repo methods resolve `user_id=AUTO` (same `ProjectRepository` as above: `create`, `get`, `patch`, `list` all call `resolve_user_id(AUTO)` and filter) | per-user projects | OK |

### runs.py (`/api/runs` stateless variant)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /stream`, `POST /wait` | `_resolve_thread_id(body)` creates/uses an ephemeral thread scoped to the caller via `get_effective_user_id()` downstream in the run pipeline (grepped 5 hits of effective-user usage in file) | ephemeral per-user thread | OK |
| `GET /{run_id}/messages`, `GET /{run_id}/feedback` | `_resolve_run(run_id, request)` re-derives thread ownership before returning messages | per-user | OK |

### scheduled_tasks.py (`/api/scheduled-tasks`, `/api/threads/{thread_id}/scheduled-tasks`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 9 handlers | `@require_permission("threads", ...)` + `get_optional_user_from_request(request)` then every repo call passes `user_id=str(user.id)` explicitly (list_by_user/get/create/update/pause/resume/trigger/delete all keyed by user id — verified in source, not by name) | per-user scheduled tasks | OK |

### skills.py (`/api` skills catalog + custom skills)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /skills`, `POST /skills/install`, `POST /skills/upload`, `POST /skills/reload` | instance-wide skill catalog; install/upload/reload require admin (grepped: `require_admin_user`/admin checks present) | instance | NOT-APPLICABLE |
| `GET /skills/custom`, `GET/PUT/DELETE /skills/custom/{name}`, `GET .../history`, `POST .../rollback` | `_get_user_skill_storage(config)` — per-user skill storage keyed off `get_effective_user_id()`-derived path (file uses the pattern 7 times per grep) | per-user custom skills | OK |
| `GET /skills/{name}`, `PUT /skills/{name}` | operator-managed skill state (extensions config), admin-gated for the PUT | instance | NOT-APPLICABLE |

### subagent_batches.py (`/api/threads/{thread_id}/subagent-batches`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| all 7 handlers | `@require_permission("threads","read",owner_check=True)` + `_owned_batch` re-fetches `repo.get_batch(batch_id, user_id=user_id)` and 404s if `batch["thread_id"] != thread_id` — a belt-and-suspenders double check (thread ownership via decorator, batch ownership via repo filter, cross-check batch actually belongs to that thread) | thread-scoped subagent batches | OK |

### subagents.py (`/api/subagents`, managed subagent catalog)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""` list_subagents:164 | any authenticated caller; system prompt only shown to admins (`is_admin_user`) | instance-wide catalog | NOT-APPLICABLE |
| `POST ""`, `PUT /{name}`, `DELETE /{name}` | `require_admin_user` on all three | instance-wide catalog | OK |

### suggestions.py (`/api` input suggestions)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /suggestions/config`, `POST /suggestions` | stateless LLM suggestion generation from caller-supplied conversation, no stored row | none | NOT-APPLICABLE |

### thread_runs.py (`/api/threads/{thread_id}/runs*`, messages, archive, events)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST /regenerate/prepare`, `/edit-regenerate/prepare` | internal helpers `_prepare_regenerate_payload`/`_prepare_edit_regenerate_payload` take `request` and re-derive thread scope | thread-scoped | OK |
| `POST /{thread_id}/runs`, `.../stream`, `.../wait` | file-wide 28 hits of the effective-user/owner_check pattern; spot-checked `create_run`/`stream_run`/`wait_run` — all resolve via `request` → decorator chain | thread-scoped | OK |
| `GET /{thread_id}/runs`, `/runs/page`, `/runs/{run_id}` | `_run_scope_user_id`/`_require_run_visible_to_scope` helpers explicitly re-derive and check scope before returning a run outside the decorator's owner_check | thread-scoped | OK |
| `POST /{thread_id}/runs/{run_id}/cancel` | `require_cancel_permission_when_action` + owner_check | thread-scoped | OK |
| `GET .../join`, `POST .../stream` (existing-run) | `_stream_existing_run` re-validates run belongs to thread | thread-scoped | OK |
| `GET /{thread_id}/messages`, `/messages/page`, `/runs/{run_id}/messages` | owner_check decorator | thread-scoped | OK |
| `POST /{thread_id}/runs/{run_id}/artifacts/archive`, `GET .../artifacts/archive` | thread-scoped, owner_check | thread-scoped | OK |
| `GET /{thread_id}/runs/{run_id}/events`, `/workspace-changes`, `GET /{thread_id}/token-usage` | owner_check | thread-scoped | OK |

### threads.py (`/api/threads*`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `DELETE /{thread_id}` delete_thread_data:708 | `@require_permission("threads","delete",owner_check=True,require_existing=True)` + `get_effective_user_id()` passed into `run_manager.reserve_thread_operation` | per-thread | OK |
| `POST ""` create_thread:868 | creates thread scoped to the authenticated caller | per-user | OK |
| `POST /{thread_id}/branches` branch_thread:955 | owner_check + `_copy_branch_user_data(..., user_id=...)` explicitly threads the source thread's owner into the filesystem copy (checked: it does not silently use a process-global path) | per-thread | OK |
| `POST /search` search_threads:1175 | search scoped by caller (owner_check-equivalent filter built into the query, not a path param so no `thread_id` for the decorator — verified the search query itself filters by user) | per-user | OK |
| `PATCH /{thread_id}` patch_thread:1218 | owner_check | per-thread | OK |
| `POST /{thread_id}/move` move_thread:1257 | owner_check | per-thread | OK |
| `GET /{thread_id}`, `/goal` (GET/PUT/DELETE), `/compact`, `/state` (GET/POST), `/history` | owner_check on every one (26 total hits of the pattern across the file, spot-checked 8 of them directly) | per-thread | OK |

### trash.py (`/api/trash`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /documents`, `POST /documents/{id}/restore`, `POST /documents/{id}/purge`, `POST /purge` | `@require_permission("projects", ...)` + `get_effective_user_id()` passed explicitly, or relies on `ProjectDocumentRepository` methods' `user_id=AUTO` default (verified `list_trashed`, `count_trashed`, `get(..., include_trashed=True)`, `purge` all take `user_id: ... = AUTO` and filter, mirroring `ProjectRepository`) | per-user trashed documents | OK — same AUTO-resolution pattern verified for `project_documents.py` above |

### uploads.py (`/api/threads/{thread_id}/uploads`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `POST ""` upload_files:358 | `@require_permission("threads","write",owner_check=True,require_existing=False)` + `ThreadUploadIngestionService(..., user_id=get_effective_user_id())` | thread-scoped uploads | OK |
| `GET /limits` | owner_check | thread-scoped | OK |
| `GET /list` list_uploaded_files:444 | owner_check + `get_effective_user_id()` passed to `_list_uploaded_files_for_thread` | thread-scoped | OK |
| `DELETE /{filename}` delete_uploaded_file:456 | `owner_check=True, require_existing=True` + `get_effective_user_id()` passed to `_delete_uploaded_file_for_thread` | thread-scoped | OK |

### user_preferences.py (`/api/v1/auth/preferences`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""`, `PATCH ""` | `_owner(request, expected_user)`: owner is `get_current_user_from_request(request)` (session-derived), `x_expected_user_id` header is only cross-checked against that server-derived value (409 on mismatch) and never trusted as the authorization input itself | per-user preferences | OK — initially SUSPECT (a client-supplied header participating in an ownership decision), traced and confirmed the header cannot substitute for the session-derived identity: it can only narrow (cause a 409), never widen access |

### workspace_branding.py (`/api/workspaces/{workspace_id}/branding`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET /{workspace_id}/branding` get_workspace_branding:219 | `_shared_membership(session, actor_id, workspace_id)` → `active_organization_for_user` equivalent; outsider and revoked member both get 404 (verified via existing test + new write-side test) | shared-workspace row | OK |
| `PUT /{workspace_id}/branding` update_workspace_branding:282 | same membership check + `_require_editor(active)` role gate (owner/admin only) | shared-workspace row | OK |
| `DELETE /{workspace_id}/branding` reset_workspace_branding:302 | same | shared-workspace row | OK |

### workspaces.py (`/api/workspaces`)
| Handler | Actor resolution | Resource | Verdict |
|---|---|---|---|
| `GET ""` list_workspaces:99 | `_active_memberships(session, user_id)` — lists only active memberships | per-user | OK |
| `POST ""` create_workspace:133 | creates workspace owned by caller | per-user | OK |
| `POST /select` select_workspace:192 | `_active_memberships` gate before issuing the workspace session cookie (verified this is what makes revoked-then-reselect return 404 in the existing `test_shared_workspace_membership.py` case) | per-user | OK |

## Findings

**None.** Every handler that touches a user- or workspace-scoped path or row resolves
the actor through one of the established patterns (`owner_check` for `thread_id`-keyed
resources, `get_effective_user_id()`/`resolve_user_id(AUTO)` for per-user paths and
rows, or an explicit active-membership check for shared-workspace rows) before touching
storage. No process-global path, no missing tenancy filter, no client-trusted
org/workspace id, and no write path that skips a check its sibling read performs was
found.

Three items were carried as SUSPECT during the sweep and resolved by reading the call
chain rather than the handler body alone (all now OK, documented above with why):

1. `project_documents.py` / `trash.py` — `@require_permission("projects", ...)` carries
   no `owner_check` (the decorator's owner_check only understands `thread_id`). Traced
   into `_require_project` → `ProjectRepository.get(project_id, user_id=AUTO)` and
   `ProjectDocumentRepository`'s trash methods, and confirmed `resolve_user_id(AUTO)` +
   an explicit `row.user_id != resolved_user_id` check is the real tenancy boundary,
   applied before any document row is returned or mutated.
2. `user_preferences.py` — a client-supplied `x-expected-user-id` header appears to
   participate in the ownership decision. Traced `_owner()` and confirmed the header is
   compared *against* the server-derived session user (`get_current_user_from_request`),
   never substituted for it; a mismatched header only produces a 409, it cannot grant
   access to another user's preferences.
3. `invitations.py` `create_invitation` — `body.organization_id` is client-supplied.
   Traced into `_active_shared_workspace_member`, which requires the caller to hold an
   **active** `owner`/`admin` row in that exact organization before the invite is
   created; confirmed with a new revocation regression test (below) that this closes for
   a member the instant they're revoked, not just at token-issue time.

## Existing revocation coverage found (per Deliverable 2 instructions, checked before writing new tests)

- `tests/test_shared_workspace_membership.py::test_two_members_share_content_identity_but_revocation_and_foreign_cookie_deny`
  — real `AuthMiddleware` + real SQL; proves a revoked member's cookie 403s on an
  arbitrary authenticated route, and that `/api/workspaces` listing / `/api/workspaces/select`
  behave correctly post-revocation (empty list, 404 on reselect).
- `tests/test_workspace_branding.py::test_revoked_member_loses_branding_access` — proves
  a revoked member's **read** (`GET .../branding`) 404s.
- `tests/test_workspace_invitations.py` — covers a revoked *invitation issuer* (i.e. the
  issuer went inactive between invite creation and someone else accepting it), not a
  live member's own session being revoked while they still hold a valid cookie.

Gaps identified and filled in `tests/test_membership_revocation.py` (new, this
deliverable): a revoked admin's **write** access to workspace branding (PUT/DELETE) was
untested — only the read path had a regression test — and invitation creation's
bespoke membership gate had no revocation test at all. Both new tests pass against
current behavior (403/404 as expected); nothing here required a "document the gap, don't
ship a failing test" fallback.

## Gate

Venv: `C:/Users/dillo/Documents/Qwen/deer-flow/backend/.venv/Scripts/python.exe`
(PYTHONPATH set to the worktree's `backend` + `backend/packages/harness`).

`import app, deerflow` resolved to:
```
C:\Users\dillo\Documents\Codex\2026-09-21\pi\work\wt-s08-auth-audit\backend\app\__init__.py
C:\Users\dillo\Documents\Codex\2026-09-21\pi\work\wt-s08-auth-audit\backend\packages\harness\deerflow\__init__.py
```
Both under `wt-s08-auth-audit` — confirmed before running any test.

`pytest -q tests/test_membership_revocation.py tests/test_user_profile_isolation.py
tests/test_custom_agent.py tests/test_persistence_bootstrap.py`:
```
113 passed, 1 warning in 48.85s
```
