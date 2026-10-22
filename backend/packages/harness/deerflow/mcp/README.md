# Private MCP server scope

An operator may restrict an MCP server to one authenticated actor in one exact
private workspace. This is a server policy, independent of role profiles,
prompts, tool arguments, and ordinary request context.

Synthetic example only:

```json
{
  "mcpServers": {
    "synthetic-private-reader": {
      "enabled": false,
      "type": "http",
      "url": "https://synthetic.invalid/mcp",
      "private_scope": {
        "actor_user_id": "synthetic-owner",
        "organization_id": "synthetic-private-org"
      }
    }
  }
}
```

The Gateway run worker binds an immutable task-local scope only when its
in-process authenticated-context marker proves the actor and workspace, a
separate Gateway-issued capability proves session authentication, and the
server-stamped `is_internal` is explicitly false. The
current authenticated user must match the actor and the storage bucket must
equal that actor. The configured actor and organization must both match.
Channel runs, internal callers (including delegated owners without role
attributes), PATs, auth-disabled callers, non-interactive runs, missing identity, and
unknown origins are denied. A shared workspace's separate storage principal
cannot satisfy this policy. Changing a model-visible role never grants access.

The process-wide MCP cache contains only unrestricted servers. Restricted
servers are discovered fresh during an authorized run, before OAuth acquisition,
client construction, or connection. Their tools recheck the captured scope
before invoking either the HTTP/SSE adapter or the pooled stdio wrapper. Each
call reloads the current configuration off-loop and requires the server to
remain enabled with the same private policy and complete configuration as at
discovery. Disabling, rebinding, removing, or changing its connection denies
stale tools; an unreadable configuration also denies. Rediscover after a change.
Reusing
a graph or tool under another actor/workspace cannot reuse that access. Private
discovery preserves task context when the synchronous cache entry point must
cross a worker thread. Ordinary public-server caching and session pooling keep
their existing behavior.

Restricted servers cannot declare `task_toolsets`; raw durable-task calls also
deny them before connection. Background notifications, scheduled retrieval,
IM/DM retrieval, and cross-tenant retrieval need a separate reviewed trust path.
No request-controlled private/public flag exists. The Gateway clears the
session capability from both client config feeds before stamping it. The worker
consumes it for task-local admission and excludes it from graph/runtime context.

This source change does not register a server, mount private data, change an
agent's tool permissions, or activate retrieval. The built-in `momobot-max`
still has `mcp_plugins=[]` and its existing fixed tool-name ceiling globally.
During an authenticated private Max run only, lead assembly selects the exact
enabled, scope-authorized `brain` installation and locally adds four read names:
`brain_now`, `brain_client`, `brain_open_items`, and `brain_systems`, honoring
`tool_name_prefix` (default final names are `brain_brain_now`,
`brain_brain_client`, `brain_brain_open_items`, `brain_brain_systems`). It keeps
normal capability selection, authorization, and execution-time scope/revocation
guards. Added candidates must already carry private-discovery provenance from
the backend guard coroutine, matching the selected server policy and connection.
Ordinary metadata cannot claim that provenance, and raw/public tools are never
promoted by wrapping them with a private policy, including when configuration
changes A to public transport B and returns to A during assembly.
Search/capture/refresh and other MCP tools are excluded. The local
selection is not written to agent configuration or delegated subagent metadata.
Deployment still requires separate review. Before any Brain
registration, privately verify the authenticated actor, exact private
organization, storage provenance, adapter contents, and destination-side
denials for another actor, shared/client workspace, channel, and background run.
Never enable a whole-snapshot private adapter as an unrestricted server.

Offline evidence: `backend/tests/test_mcp_private_scope.py` covers policy
validation, authenticated worker binding/reset, forged context, actor/workspace
changes, discovery filtering, public-cache separation, real adapter/ToolNode
runtime forwarding, and denial before background connections. These are
synthetic checks; they do not establish production account binding or live
adapter isolation.

The synthetic `tests/test_momobot_private_brain.py` suite exercises real tool
loading and lead authorization, both prefix modes, four fake adapter reads,
per-tool authorization denial, concurrent actor isolation, and configuration
change during discovery. It performs no production retrieval or model call.
