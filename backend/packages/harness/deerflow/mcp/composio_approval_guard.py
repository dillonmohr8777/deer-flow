"""Mandatory, fail-closed Composio approvals at both MCP call boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import ToolException
from mcp.types import CallToolResult, TextContent

from deerflow.approvals import InvalidPayloadError, register_action_type
from deerflow.runtime.user_context import get_current_user, get_storage_context

ACTION_TYPE = "composio_tool_call"
_CONTROLS = {"COMPOSIO_MANAGE_CONNECTIONS", "COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS"}
_MULTI = "COMPOSIO_MULTI_EXECUTE_TOOL"
_READ = re.compile(r"^(?:[A-Z0-9]+|GOOGLE_ANALYTICS|GOOGLE_SEARCH_CONSOLE)_(?:GET|LIST|FETCH|SEARCH|FIND|READ|QUERY|RETRIEVE|DESCRIBE|REPORT)(?:_|$)")
_EXECUTION_WORDS = {"EXECUTE", "EXECUTION", "REMOTE", "WORKBENCH", "BASH", "PROXY", "SCRIPT", "CODE", "SEND", "CREATE", "UPDATE", "DELETE", "POST", "PATCH", "MUTATE", "ADD", "REMOVE", "PUBLISH", "SCHEDULE", "INVITE", "UPLOAD"}
_CREDENTIAL_KEYS = {"headers", "authorization", "apikey", "key", "accesstoken", "refreshtoken", "cookies", "cookie", "sessioncookie", "authconfig", "secrets", "password"}
_PAYLOAD_KEYS = {"server_name", "tool_name", "arguments", "tool_call_id"}


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise InvalidPayloadError("Composio arguments must be finite JSON") from None


def _check_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise InvalidPayloadError("Composio argument keys must be strings")
            if re.sub(r"[^a-z]", "", key.lower()) in _CREDENTIAL_KEYS:
                raise InvalidPayloadError("Composio proposals cannot persist credential carriers")
            _check_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _check_credentials(child)


def validate_composio_payload(target: str, payload: dict[str, Any]) -> None:
    if set(payload) != _PAYLOAD_KEYS or payload.get("server_name") != target or not target.startswith("composio-") or len(target) > 128:
        raise InvalidPayloadError("Invalid Composio server or proposal shape")
    if not isinstance(payload.get("tool_name"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", payload["tool_name"]):
        raise InvalidPayloadError("Invalid Composio tool name")
    if not isinstance(payload.get("tool_call_id"), str) or not payload["tool_call_id"]:
        raise InvalidPayloadError("Composio approval requires a tool call id")
    if not isinstance(payload.get("arguments"), dict):
        raise InvalidPayloadError("Composio arguments must be an object")
    _json(payload)
    try:
        _check_credentials(payload["arguments"])
    except RecursionError:
        raise InvalidPayloadError("Composio arguments are too deeply nested") from None


register_action_type(ACTION_TYPE, validate_composio_payload)


def _read_only(name: str, args: Any, depth: int = 0) -> bool:
    if not isinstance(args, dict) or depth > 8:
        return False
    if name in _CONTROLS:
        return True
    if name == _MULTI:
        # Meta schemas can change: unknown fields/shapes withhold the entire batch.
        metadata = {"session_id": str, "sync_response_to_workbench": bool, "thought": str, "current_step": str, "current_step_index": int}
        if set(args) - {"tools", *metadata} or any(type(args[key]) is not expected for key, expected in metadata.items() if key in args):
            return False
        tools = args.get("tools")
        return (
            isinstance(tools, list)
            and 1 <= len(tools) <= 50
            and all(isinstance(item, dict) and set(item) == {"tool_slug", "arguments"} and isinstance(item["tool_slug"], str) and _read_only(item["tool_slug"], item["arguments"], depth + 1) for item in tools)
        )
    return not name.startswith("COMPOSIO_") and bool(re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+", name)) and bool(_READ.match(name)) and not (_EXECUTION_WORDS & set(name.split("_")))


def authenticated_scope() -> tuple[str, str]:
    user, scope = get_current_user(), get_storage_context()
    if user is None or scope is None or str(user.id) != scope.actor_user_id or not scope.organization_id or getattr(user, "system_role", None) == "internal":
        raise ToolException("Composio requires an authenticated actor and active organization.")
    return str(user.id), scope.organization_id


@dataclass
class _ApprovedAttempt:
    action_id: str
    actor: str
    organization: str
    payload: str
    consumed: bool = False


_approved_attempt: ContextVar[_ApprovedAttempt | None] = ContextVar("composio_approved_attempt", default=None)


@contextmanager
def claimed_composio_attempt(action: dict[str, Any]):
    """Gateway-only capability, installed only after the durable execution CAS."""
    attempt = _ApprovedAttempt(action["id"], action["user_id"], action["organization_id"], _json(action["payload"]))
    token = _approved_attempt.set(attempt)
    try:
        yield attempt
    finally:
        _approved_attempt.reset(token)


def build_composio_approval_guard(*, final: bool = False):
    async def guard(request: Any, handler: Any) -> Any:
        if not request.server_name.startswith("composio-"):
            return await handler(request)
        actor, organization = authenticated_scope()
        runtime = getattr(request, "runtime", None)
        payload = {"server_name": request.server_name, "tool_name": request.name, "arguments": request.args, "tool_call_id": getattr(runtime, "tool_call_id", None)}
        attempt = _approved_attempt.get()
        if attempt is not None:
            if attempt.consumed:
                raise ToolException("Composio approval attempt was already consumed; reconcile before any new proposal.")
            if (actor, organization, _json(payload)) != (attempt.actor, attempt.organization, attempt.payload):
                raise ToolException("Composio approval does not match the authenticated scope and exact call.")
            if final:
                attempt.consumed = True
            return await handler(request)
        if _read_only(request.name, request.args):
            return await handler(request)
        context = getattr(runtime, "context", None)
        thread, run = (context.get(key) for key in ("thread_id", "run_id")) if isinstance(context, Mapping) else (None, None)
        if not all(isinstance(value, str) and value and len(value) <= 64 for value in (thread, run)):
            raise ToolException("Composio approval requires the server run and thread identity.")
        validate_composio_payload(request.server_name, payload)
        from deerflow.persistence.approvals import PendingActionRepository
        from deerflow.persistence.engine import get_session_factory

        factory = get_session_factory()
        if factory is None:
            raise ToolException("Composio approval is unavailable; no call was executed.")
        action_id = hashlib.sha256(_json([actor, organization, thread, run, request.server_name, payload["tool_call_id"]]).encode()).hexdigest()
        row = await PendingActionRepository(factory).create(
            action_type=ACTION_TYPE,
            target=request.server_name,
            payload=payload,
            title=f"Approve Composio: {request.name}",
            thread_id=thread,
            run_id=run,
            user_id=actor,
            organization_id=organization,
            action_id=action_id,
        )
        result = {"status": "pending_approval" if row["status"] == "pending" else row["status"], "id": row["id"]}
        return CallToolResult(content=[TextContent(type="text", text=_json(result))], structuredContent=result)

    return guard
