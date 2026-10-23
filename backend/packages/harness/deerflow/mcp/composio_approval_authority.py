"""One action's server-owned approval handoff; the signed-in actor never changes."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.headers import apply_header_overrides, header_spellings, illegal_header_value_reason
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.runtime.user_context import get_current_user, get_storage_context


def _identity(action: dict) -> str:
    return json.dumps([action["id"], action["user_id"], action["organization_id"], action["target"], action["payload"], action.get("thread_id"), action.get("run_id")], sort_keys=True, separators=(",", ":"), allow_nan=False)


def _binding(config: ExtensionsConfig, action: dict) -> McpServerConfig:
    server = config.get_enabled_mcp_servers().get(action["payload"]["server_name"])
    auth = server.user_auth if server is not None else None
    if server is None or server.type not in {"http", "sse"} or auth is None or not auth.enabled or server.oauth is not None or server.headers_from_context is not None:
        raise ToolException("Composio approval requires a current operator-bound proposer connection.")
    credential = auth.users.get(action["user_id"])
    if not credential or illegal_header_value_reason(credential) is not None:
        raise ToolException("Composio proposer connection is unavailable.")
    return server.model_copy(update={"user_auth": auth.model_copy(update={"users": {action["user_id"]: credential}})}, deep=True)


@dataclass(frozen=True, repr=False)
class ComposioApprovalAuthority:
    action_id: str
    decider: str
    proposer: str
    organization: str
    identity: str
    server_name: str
    server: McpServerConfig = field(repr=False)
    repository: PendingActionRepository = field(repr=False, compare=False)

    async def verify(self, request: Any = None, *, final=False) -> dict:
        actor, scope = get_current_user(), get_storage_context()
        if actor is None or scope is None or (str(actor.id), scope.actor_user_id, scope.organization_id) != (self.decider, self.decider, self.organization):
            raise ToolException("Composio approval authority does not match the deciding actor.")
        current = await self.repository.get_composio_for_approval(self.action_id)
        if current is None or current["status"] != "approved" or current["decided_by"] != self.decider or _identity(current) != self.identity:
            raise ToolException("Composio approval authority is no longer valid.")
        try:
            config = await asyncio.to_thread(ExtensionsConfig.from_file)
            server = _binding(config, current)
        except Exception:
            raise ToolException("Composio proposer connection is unavailable.") from None
        if server != self.server:
            raise ToolException("Composio proposer connection changed; no call was executed.")
        from deerflow.mcp.private_scope import require_private_mcp_access

        require_private_mcp_access(server)
        if request is not None:
            runtime = getattr(request, "runtime", None)
            context = getattr(runtime, "context", {})
            payload = {"server_name": request.server_name, "tool_name": request.name, "arguments": request.args, "tool_call_id": getattr(runtime, "tool_call_id", None)}
            if payload != current["payload"] or (context.get("thread_id"), context.get("run_id")) != (current["thread_id"], current["run_id"]):
                raise ToolException("Composio approval does not match the exact proposed call.")
            if final:
                headers = getattr(request, "headers", None) or {}
                normalized = {key.lower(): value for key, value in headers.items()}
                if len(normalized) != len(headers) or normalized != {key.lower(): value for key, value in self.headers().items()}:
                    raise ToolException("Composio proposer credential headers changed.")
        return current

    def headers(self) -> dict[str, str]:
        auth = self.server.user_auth
        return apply_header_overrides(self.server.headers, {auth.header: auth.users[self.proposer]}, spellings=header_spellings(self.server.headers))


_authority: ContextVar[ComposioApprovalAuthority | None] = ContextVar("composio_approval_authority", default=None)


def current_composio_authority() -> ComposioApprovalAuthority | None:
    return _authority.get()


async def prepare_composio_authority(action: dict, repository: PendingActionRepository) -> ComposioApprovalAuthority:
    from deerflow.mcp.composio_approval_guard import validate_composio_payload
    from deerflow.mcp.private_scope import require_private_mcp_access

    current = await repository.get_composio_for_approval(action["id"])
    actor = get_current_user()
    if current is None or actor is None or _identity(current) != _identity(action):
        raise ToolException("Composio approval is not authorized.")
    validate_composio_payload(current["target"], current["payload"])
    if current["payload"] != current["original_payload"]:
        raise ToolException("Composio approval payload changed.")
    try:
        config = await asyncio.to_thread(ExtensionsConfig.from_file)
        server = _binding(config, current)
    except Exception:
        raise ToolException("Composio proposer connection is unavailable.") from None
    require_private_mcp_access(server)
    return ComposioApprovalAuthority(current["id"], str(actor.id), current["user_id"], current["organization_id"], _identity(current), current["payload"]["server_name"], server, repository)


@contextmanager
def bind_composio_authority(authority: ComposioApprovalAuthority):
    if not isinstance(authority, ComposioApprovalAuthority):
        raise ToolException("Composio approval authority is unavailable.")
    token = _authority.set(authority)
    try:
        yield authority
    finally:
        _authority.reset(token)


def approved_credential_interceptor(normal_interceptor):
    async def scoped(request, handler):
        authority = current_composio_authority()
        if authority is None:
            return await normal_interceptor(request, handler)
        await authority.verify(request)
        return await handler(request.override(headers=authority.headers()))

    return scoped
