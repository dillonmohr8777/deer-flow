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
from urllib.parse import parse_qsl, unquote, urlsplit

from langchain_core.tools import ToolException
from mcp.types import CallToolResult, TextContent

from deerflow.approvals import InvalidPayloadError, register_action_type
from deerflow.runtime.user_context import get_current_user, get_storage_context

ACTION_TYPE = "composio_tool_call"
_CONTROLS = {"COMPOSIO_MANAGE_CONNECTIONS", "COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS"}
_MULTI = "COMPOSIO_MULTI_EXECUTE_TOOL"
# Reviewed public toolkit contracts, 2026-10-23: docs.composio.dev/toolkits/{gmail,hubspot,slack}.
# Gmail 20261018_00; HubSpot 20261020_01; Slack 20261020_00. Unknown actions/keys require approval.
# Public research: composio_search 20260903_00, inspo_mcp 20260925_00, godaddy_mcp 20261018_00.
_READ_ACTIONS = {
    "GMAIL_FETCH_EMAILS": (set(), {"query": str, "user_id": str, "verbose": bool, "ids_only": bool, "label_ids": list, "page_token": str, "max_results": int, "include_payload": bool, "include_spam_trash": bool}),
    "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID": ({"message_id"}, {"message_id": str, "user_id": str, "format": str}),
    "GMAIL_LIST_LABELS": (set(), {"user_id": str, "include_details": bool}),
    "GMAIL_GET_PROFILE": (set(), {"user_id": str}),
    "HUBSPOT_READ_CONTACT": ({"contactId"}, {"contactId": str, "archived": bool, "associations": list, "properties": list, "propertiesWithHistory": list}),
    "HUBSPOT_LIST_CONTACTS": (set(), {"after": str, "archived": bool, "associations": list, "limit": int, "properties": list, "propertiesWithHistory": list}),
    "SLACK_SEARCH_ALL": ({"query"}, {"query": str, "count": int, "highlight": bool, "page": int, "sort": str, "sort_dir": str, "team_id": str}),
    "SLACK_SEARCH_MESSAGES": ({"query"}, {"query": str, "auto_paginate": bool, "cursor": str, "count": int, "highlight": bool, "page": int, "sort": str, "sort_dir": str, "team_id": str}),
    "SLACK_FETCH_CONVERSATION_HISTORY": ({"channel"}, {"channel": str, "cursor": str, "include_all_metadata": bool, "inclusive": bool, "latest": str, "limit": int, "oldest": str}),
    "COMPOSIO_SEARCH_WEB": ({"query"}, {"query": str}),
    "COMPOSIO_SEARCH_NEWS": (set(), {"query": str, "gl": str, "hl": str, "start": int, "when": str}),
    "COMPOSIO_SEARCH_TRENDS": ({"query"}, {"query": str, "data_type": str, "date": str}),
    "COMPOSIO_SEARCH_GOOGLE_MAPS": ({"q"}, {"q": str, "ll": str, "start": int}),
    "COMPOSIO_SEARCH_EXA_SIMILARLINK": (
        {"url"},
        {"url": str, "numResults": int, "includeDomains": list, "excludeDomains": list, "category": str, "type": str, "useAutoprompt": bool, "startCrawlDate": str, "endCrawlDate": str, "startPublishedDate": str, "endPublishedDate": str},
    ),
    "COMPOSIO_SEARCH_NPPESNPI_LOOKUP": (
        set(),
        {"number": str, "enumeration_type": str, "first_name": str, "last_name": str, "organization_name": str, "city": str, "state": str, "postal_code": str, "taxonomy_description": str, "limit": int, "skip": int, "version": str},
    ),
    "INSPO_MCP_SEARCH_SCREENS": (
        set(),
        {
            "query": str,
            "accentHue": str,
            "color": str,
            "detail": str,
            "device": str,
            "displayClass": str,
            "industry": str,
            "limit": int,
            "macrostructure": str,
            "maxTokens": int,
            "mode": str,
            "pageType": str,
            "paperBand": str,
            "style": str,
            "vibe": str,
        },
    ),
    "INSPO_MCP_GET_SCREEN": ({"slug"}, {"slug": str}),
    "GODADDY_MCP_DOMAINS_CHECK_AVAILABILITY": ({"domains"}, {"domains": str}),
    "GODADDY_MCP_DOMAINS_SUGGEST": ({"query"}, {"query": str, "limit": int}),
}
_CREDENTIAL_KEYS = {
    "headers",
    "authorization",
    "authentication",
    "auth",
    "apikey",
    "xapikey",
    "apisecret",
    "key",
    "privatekey",
    "signingkey",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
    "oauthtoken",
    "oauth2token",
    "bearer",
    "bearertoken",
    "cookies",
    "cookie",
    "sessioncookie",
    "sessiontoken",
    "authconfig",
    "secret",
    "secrets",
    "password",
    "clientsecret",
    "clientpassword",
    "credential",
    "credentials",
    "accesskey",
    "secretaccesskey",
    "signature",
    "sig",
    "xamzcredential",
    "xamzsignature",
    "xamzsecuritytoken",
    "xgoogcredential",
    "xgoogsignature",
}
_PAYLOAD_KEYS = {"server_name", "tool_name", "arguments", "tool_call_id"}


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise InvalidPayloadError("Composio arguments must be finite JSON") from None


class CredentialPayloadError(InvalidPayloadError):
    """An exact call cannot be persisted safely; never echo its values."""


def _credential_key(value: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", value.lower()) in _CREDENTIAL_KEYS


def _check_url(value: str, depth: int = 0) -> None:
    if depth > 3:
        raise CredentialPayloadError("Composio URL nesting cannot be verified credential-free")
    # Inspect scalar URLs, including percent-encoded redirect URLs and fragments.
    for candidate in re.findall(r"(?:[a-zA-Z][a-zA-Z0-9+.-]*://|//)[^\s<>\"']+", value):
        try:
            url = urlsplit(candidate)
        except ValueError:
            raise CredentialPayloadError("Composio URL cannot be verified credential-free") from None
        if url.username is not None or url.password is not None:
            raise CredentialPayloadError("Composio proposals cannot persist URL credentials")
        if re.match(r"(?i)^(?:bearer|basic)\s+\S+", unquote(url.fragment)):
            raise CredentialPayloadError("Composio proposals cannot persist URL credentials")
        fragment = url.fragment.partition("?")[2] if "?" in url.fragment else url.fragment
        for key, child in parse_qsl(url.query, keep_blank_values=True) + parse_qsl(fragment, keep_blank_values=True):
            if _credential_key(unquote(key)) or key.lower() in {"code", "jwt", "auth_code", "authorization_code"}:
                raise CredentialPayloadError("Composio proposals cannot persist URL credentials")
            if "://" in child or "%3a%2f%2f" in child.lower():
                _check_url(unquote(child), depth + 1)
    decoded = unquote(value)
    if decoded != value and ("://" in decoded or "%3a%2f%2f" in decoded.lower()):
        _check_url(decoded, depth + 1)


def _check_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise InvalidPayloadError("Composio argument keys must be strings")
            if _credential_key(key):
                raise CredentialPayloadError("Composio proposals cannot persist credential carriers")
            _check_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _check_credentials(child)
    elif isinstance(value, str):
        _check_url(value)


def validate_composio_payload(target: str, payload: dict[str, Any]) -> None:
    if set(payload) != _PAYLOAD_KEYS or payload.get("server_name") != target or not target.startswith("composio-") or len(target) > 128:
        raise InvalidPayloadError("Invalid Composio server or proposal shape")
    if not isinstance(payload.get("tool_name"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", payload["tool_name"]):
        raise InvalidPayloadError("Invalid Composio tool name")
    if not isinstance(payload.get("tool_call_id"), str) or not payload["tool_call_id"]:
        raise InvalidPayloadError("Composio approval requires a tool call id")
    if not isinstance(payload.get("arguments"), dict):
        raise InvalidPayloadError("Composio arguments must be an object")
    try:
        _check_credentials(payload["arguments"])
    except RecursionError:
        raise InvalidPayloadError("Composio arguments are too deeply nested") from None
    _json(payload)


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
    policy = _READ_ACTIONS.get(name)
    if policy is None:
        return False
    required, fields = policy
    return (
        required <= args.keys()
        and not (args.keys() - fields.keys())
        and all(type(value) is fields[key] and (not isinstance(value, list) or all(isinstance(item, str) for item in value)) and (key not in required or bool(value)) for key, value in args.items())
    )


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


def _runtime_identity(runtime: Any) -> tuple[Any, Any, Any]:
    context = getattr(runtime, "context", None)
    return (getattr(runtime, "tool_call_id", None), context.get("thread_id"), context.get("run_id")) if isinstance(context, Mapping) else (None, None, None)


@dataclass(frozen=True)
class _CallOrigin:
    server_name: str
    runtime: Any
    runtime_identity: tuple[Any, Any, Any]
    scope: tuple[str, str] | None


_call_origin: ContextVar[_CallOrigin | None] = ContextVar("composio_call_origin", default=None)


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
    async def check(request: Any, handler: Any, origin: _CallOrigin) -> Any:
        if not origin.server_name.startswith("composio-"):
            return await handler(request)
        if request.server_name != origin.server_name or getattr(request, "runtime", None) is not origin.runtime or _runtime_identity(getattr(request, "runtime", None)) != origin.runtime_identity:
            raise ToolException("MCP request origin changed inside the interceptor chain.")
        actor, organization = authenticated_scope()
        if (actor, organization) != origin.scope:
            raise ToolException("Composio authenticated origin changed inside the interceptor chain.")
        call_id, thread, run = origin.runtime_identity
        payload = {"server_name": origin.server_name, "tool_name": request.name, "arguments": request.args, "tool_call_id": call_id}
        try:
            _check_credentials(request.args)
        except CredentialPayloadError:
            result = {"status": "not_executed", "reason": "credential_bearing_arguments"}
            return CallToolResult(content=[TextContent(type="text", text=_json(result))], structuredContent=result)
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
        if not all(isinstance(value, str) and value and len(value) <= 64 for value in (thread, run)):
            raise ToolException("Composio approval requires the server run and thread identity.")
        validate_composio_payload(origin.server_name, payload)
        from deerflow.persistence.approvals import PendingActionRepository
        from deerflow.persistence.engine import get_session_factory

        factory = get_session_factory()
        if factory is None:
            raise ToolException("Composio approval is unavailable; no call was executed.")
        action_id = hashlib.sha256(_json([actor, organization, thread, run, origin.server_name, call_id]).encode()).hexdigest()
        row = await PendingActionRepository(factory).create(
            action_type=ACTION_TYPE,
            target=origin.server_name,
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

    async def guard(request: Any, handler: Any) -> Any:
        if final:
            origin = _call_origin.get()
            if origin is None:
                raise ToolException("MCP transport origin is unavailable.")
            return await check(request, handler, origin)
        runtime = getattr(request, "runtime", None)
        origin = _CallOrigin(request.server_name, runtime, _runtime_identity(runtime), authenticated_scope() if request.server_name.startswith("composio-") else None)
        token = _call_origin.set(origin)
        try:
            return await check(request, handler, origin)
        finally:
            _call_origin.reset(token)

    return guard
