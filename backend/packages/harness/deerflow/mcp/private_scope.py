"""Operator-bound private MCP access, independent of model-visible context."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER,
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    PRIVATE_MCP_SESSION_CONTEXT_KEY,
    PRIVATE_MCP_SESSION_MARKER,
    get_current_user,
    get_storage_context,
)
from deerflow.tools.types import Runtime


@dataclass(frozen=True)
class PrivateMcpContext:
    actor_user_id: str
    organization_id: str
    storage_user_id: str


_private_context: ContextVar[PrivateMcpContext | None] = ContextVar("deerflow_private_mcp_context", default=None)


def bind_private_mcp_context(context: object) -> Token[PrivateMcpContext | None]:
    """Bind only a Gateway-authenticated direct web run; unknown origins deny.

    The worker calls this before assembly and resets the token after execution.
    No request flag, role name, or ordinary ToolRuntime field grants access.
    """
    scope = None
    user = get_current_user()
    if (
        isinstance(context, Mapping)
        and context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is AUTHENTICATED_CONTEXT_MARKER
        and context.get(PRIVATE_MCP_SESSION_CONTEXT_KEY) is PRIVATE_MCP_SESSION_MARKER
        and context.get("is_internal") is False
        and "channel_name" not in context
        and "public_news_channel" not in context
        and not context.get("non_interactive")
        and user is not None
        and getattr(user, "system_role", None) != "internal"
    ):
        actor = context.get("actor_user_id")
        organization = context.get("organization_id")
        storage = context.get("storage_user_id")
        if all(isinstance(value, str) and value.strip() for value in (actor, organization, storage)) and str(user.id) == actor and storage == actor:
            scope = PrivateMcpContext(actor, organization, storage)
    return _private_context.set(scope)


def reset_private_mcp_context(token: Token[PrivateMcpContext | None]) -> None:
    _private_context.reset(token)


def current_private_mcp_context() -> PrivateMcpContext | None:
    """Reject inherited bindings if the authenticated principal has changed."""
    scope = _private_context.get()
    user = get_current_user()
    if scope is None or user is None or str(user.id) != scope.actor_user_id:
        return None
    storage = get_storage_context()
    if storage is not None and (storage.actor_user_id, storage.organization_id, storage.storage_user_id) != (scope.actor_user_id, scope.organization_id, scope.storage_user_id):
        return None
    return scope


def private_mcp_allowed(server: McpServerConfig) -> bool:
    policy = server.private_scope
    if policy is None:
        return True
    scope = current_private_mcp_context()
    return scope is not None and scope.actor_user_id == policy.actor_user_id and scope.organization_id == policy.organization_id and scope.storage_user_id == policy.actor_user_id


def require_private_mcp_access(server: McpServerConfig, expected: PrivateMcpContext | None = None) -> None:
    if server.private_scope is not None and (not private_mcp_allowed(server) or (expected is not None and current_private_mcp_context() != expected)):
        raise ToolException("This MCP server requires its operator-bound private web workspace.")


@dataclass(frozen=True)
class _PrivateMcpProvenance:
    server_name: str
    configuration: str


def _configuration_identity(server: McpServerConfig) -> str:
    return json.dumps(server.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def matches_private_mcp_discovery(tool: BaseTool, server: McpServerConfig, *, server_name: str) -> bool:
    # A backend coroutine capability, never a provider-supplied metadata claim.
    provenance = getattr(getattr(tool, "coroutine", None), "_deerflow_private_mcp_provenance", None)
    return isinstance(provenance, _PrivateMcpProvenance) and provenance == _PrivateMcpProvenance(server_name, _configuration_identity(server))


def guard_private_mcp_tool(tool: BaseTool, server: McpServerConfig, *, server_name: str) -> BaseTool:
    """Check again before any adapter/pool coroutine can open a connection."""
    if server.private_scope is None:
        return tool
    require_private_mcp_access(server)
    expected = current_private_mcp_context()
    discovered_config = server.model_dump()

    async def private_call(runtime: Runtime | None = None, **arguments: Any) -> Any:
        require_private_mcp_access(server, expected)
        try:
            config = await asyncio.to_thread(ExtensionsConfig.from_file)
            current = config.get_enabled_mcp_servers().get(server_name)
        except Exception:
            raise ToolException("Private MCP configuration is unavailable; rediscover the tool.") from None
        # The adapter/pool closes over its discovered connection. Any config
        # change requires rediscovery rather than using stale authority/transport.
        if current is None or current.private_scope is None or current.model_dump() != discovered_config:
            raise ToolException("Private MCP configuration changed; rediscover the tool.")
        require_private_mcp_access(current, expected)
        return await tool.coroutine(runtime=runtime, **arguments)

    private_call._deerflow_private_mcp_provenance = _PrivateMcpProvenance(server_name, _configuration_identity(server))
    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=private_call,
        response_format=tool.response_format,
        metadata=tool.metadata,
    )
