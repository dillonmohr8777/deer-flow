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
in-process authenticated-context marker proves the actor and workspace. The
current authenticated user must match the actor and the storage bucket must
equal that actor. The configured actor and organization must both match.
Channel runs, internal callers, non-interactive runs, missing identity, and
unknown origins are denied. A shared workspace's separate storage principal
cannot satisfy this policy. Changing a model-visible role never grants access.

The process-wide MCP cache contains only unrestricted servers. Restricted
servers are discovered fresh during an authorized run, before OAuth acquisition,
client construction, or connection. Their tools recheck the captured scope
before invoking either the HTTP/SSE adapter or the pooled stdio wrapper. Reusing
a graph or tool under another actor/workspace cannot reuse that access. Private
discovery preserves task context when the synchronous cache entry point must
cross a worker thread. Ordinary public-server caching and session pooling keep
their existing behavior.

Restricted servers cannot declare `task_toolsets`; raw durable-task calls also
deny them before connection. Background notifications, scheduled retrieval,
IM/DM retrieval, and cross-tenant retrieval need a separate reviewed trust path.
No request-controlled private/public flag exists.

This source change does not register a server, mount private data, change an
agent's tool permissions, or activate retrieval. The built-in `momobot-max`
still has `mcp_plugins=[]` and its existing fixed tool-name ceiling. Deployment
and any narrowly scoped agent wiring require separate review. Before any Brain
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
