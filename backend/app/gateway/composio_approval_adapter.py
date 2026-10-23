"""One claimed Composio attempt through the current authenticated MCP transport."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from deerflow.approvals import AdapterOutcome
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.composio_approval_authority import current_composio_authority
from deerflow.mcp.composio_approval_guard import authenticated_scope, claimed_composio_attempt, validate_composio_payload
from deerflow.persistence.approvals import PendingActionRepository


async def _current_tool(action: dict[str, Any]):
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.interceptors import build_mcp_tool_interceptors
    from deerflow.mcp.private_scope import require_private_mcp_access

    authority = current_composio_authority()
    if authority is None:
        raise ValueError("Composio approval authority is unavailable")
    await authority.verify()
    config = await asyncio.to_thread(ExtensionsConfig.from_file)
    name = action["payload"]["server_name"]
    server = authority.server
    require_private_mcp_access(server)
    # Logical server selection only: no connection URL or credentials in the row.
    selected = config.model_copy(update={"mcp_servers": {name: server}})
    client = MultiServerMCPClient({name: build_server_params(name, server)}, tool_interceptors=build_mcp_tool_interceptors(selected), tool_name_prefix=True)
    if server.tool_name_prefix:
        tools = await client.get_tools(server_name=name)
    else:
        tools = await load_mcp_tools(None, connection=client.connections[name], callbacks=client.callbacks, server_name=name, tool_interceptors=client.tool_interceptors, tool_name_prefix=False)
    tool_name = action["payload"]["tool_name"]
    visible_name = f"{name}_{tool_name}" if server.tool_name_prefix else tool_name
    matches = [tool for tool in tools if tool.name == visible_name]
    if len(matches) != 1:
        raise ValueError("Approved Composio tool is unavailable")
    return matches[0]


class ComposioAdapter:
    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        actor, organization = authenticated_scope()
        authority = current_composio_authority()
        if authority is None or authority.action_id != action.get("id") or authority.decider != actor or authority.organization != organization or action.get("status") != "approved":
            return AdapterOutcome("failed", error="Composio approval scope or status mismatch")
        from deerflow.persistence.engine import get_session_factory

        factory = get_session_factory()
        if factory is None:
            return AdapterOutcome("failed", error="Composio approvals are unavailable")
        repo = PendingActionRepository(factory)
        # Reload rather than trusting the adapter caller's copy of a proposal.
        try:
            current = await authority.verify()
        except Exception:
            return AdapterOutcome("failed", error="Composio approval authority is unavailable")
        if current is None or current["status"] != "approved":
            return AdapterOutcome("failed", error="Composio approval is not executable")
        if current["execution_result"] is not None:
            return AdapterOutcome("approved", {"state": "outcome_unknown"}, error="Composio attempt already claimed; reconcile destination, do not retry")
        validate_composio_payload(current["target"], current["payload"])
        try:
            tool = await _current_tool(current)
        except Exception:
            return AdapterOutcome("failed", error="Current scoped Composio transport is unavailable")
        claimed = await repo.claim_composio_handoff(action["id"])
        if claimed is None:
            return AdapterOutcome("approved", {"state": "outcome_unknown"}, error="Composio attempt already claimed; reconcile destination, do not retry")
        runtime = SimpleNamespace(tool_call_id=claimed["payload"]["tool_call_id"], context={"actor_user_id": actor, "user_id": actor, "organization_id": organization, "thread_id": claimed["thread_id"], "run_id": claimed["run_id"]})
        with claimed_composio_attempt(claimed) as attempt:
            try:
                await tool.coroutine(runtime=runtime, **claimed["payload"]["arguments"])
                if not attempt.consumed:
                    raise RuntimeError("Composio transport did not consume its approval")
            except Exception:
                return AdapterOutcome("approved", {"state": "outcome_unknown"}, error="outcome_unknown: reconcile Composio destination; never automatically retry")
        return AdapterOutcome("executed", {"state": "completed", "upstream_attempts": 1})
