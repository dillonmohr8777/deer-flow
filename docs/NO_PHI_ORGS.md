# No-PHI workspaces (health-sector clients)

No business associate agreement covers any service behind MomoBot, so a health-sector
client's workspace must never receive patient health information. A workspace can be
flagged `no_phi`. Only a system admin or the operator config can set it; clients cannot.

## What the flag does

| Surface | Effect |
| --- | --- |
| Every agent run in the workspace | `app/gateway/no_phi.py::apply_no_phi_policy` stamps `no_phi: true` on the run config. The lead-agent prompt (`prompt.py::NO_PHI_GUARD`) then adds a `<no_phi_guard>` block: marketing scope only, never request or store patient data, no lead handling or review replies, refuse and redirect if patient data is pasted. Applies to Max and to every custom agent. |
| Memory | A flagged run assembles with memory off: no `MemoryMiddleware`, no `memory_*` tools, no memory injected into the prompt (`lead_agent/agent.py`, via `memory_enabled`). |
| Subagents | `task` and durable batch items pass `no_phi` to the subagent, whose own system prompt carries the same `<no_phi_guard>` block. |
| File uploads | `POST /api/threads/{id}/uploads` and the project shelf routes (`upload`, `from-thread`, `attach-to-thread`) return 403 with a plain message. |
| Channel attachments | Slack, Telegram, Feishu and DingTalk attachments are refused before any download or write (`channels/manager.py::_handle_chat_on_thread`, with a second check in `_ingest_inbound_files`). The files are dropped, nothing is kept, and the sender gets a short refusal; the text of the message is still handled. |
| Client portal and chat | `GET /api/workspaces` returns `active_no_phi`; the frontend `NoPhiBanner` shows a persistent notice with no dismiss button. |

A run request can never set the flag: `no_phi` is a server-owned context key, dropped from
`body.config` and `body.context`, then recomputed from the workspace on every run.

## Who is flagged

A request is no-PHI when any of these is true:

1. its workspace's `organizations.no_phi` column is true (admin API below);
2. the canonical client the workspace is bound to (`organizations.customer_client_id`) has `clients.no_phi` true;
3. the workspace slug is listed under `no_phi.organization_slugs` in `config.yaml` (operator config; the API cannot clear it);
4. the project it works on, or the project its thread belongs to (`projects.client_id`, `threads_meta.project_id`), is linked to a client with `clients.no_phi` true. This covers agency staff in an unflagged agency workspace who work on a health client's project: their runs, uploads and shelf writes are guarded like the client's own.

The check fails closed. A workspace that is named but has no organization row counts as flagged, and so does a project linked to a client row that does not exist. With no database at all, any named workspace counts as flagged whenever `no_phi.organization_slugs` is non-empty (its slug cannot be resolved against the list); with an empty list there is nothing to read. A call that names no workspace, project or thread (internal callers, dev, tests) is unflagged. Database errors propagate rather than being swallowed.

Migration `0054_no_phi_flag` adds both columns (`NOT NULL`, default false).

## Setting it

```
GET  /api/admin/organizations/{organization_id}/no-phi    -> {no_phi, configured, effective}
PUT  /api/admin/organizations/{organization_id}/no-phi    {"no_phi": true}
PUT  /api/admin/clients/{client_id}/no-phi                {"no_phi": true}
```

All three require `system_role == "admin"` and the two writes are audited
(`admin.organization.no_phi_changed`, `admin.client.no_phi_changed`).

Config seed:

```yaml
no_phi:
  organization_slugs: ["example-health-workspace"]
```

## Not covered

The guard works at the prompt and upload level. It is an instruction to the model plus a block on
file ingestion, not a filter on text:

- Text a person types or pastes in their first turn still reaches the model provider and is written
  to the checkpoint store and thread history before the model can refuse it. The guard tells the
  model to stop and not reuse it, but it does not stop the transmission or the storage.
- Subagents get the guard in their own prompt, and the flag is passed to them through the run
  context. A subagent receives whatever the lead agent hands it, so the same first-turn limit
  applies to what it is given.
- It does not turn off connectors a workspace admin has already linked, and it is not a substitute
  for a signed BAA. Do not onboard a health client onto features that move patient data until
  counsel and the model providers cover it.

Tests: `backend/tests/test_no_phi_orgs.py`, `frontend/tests/unit/components/workspace/no-phi-banner.dom.test.tsx`.
