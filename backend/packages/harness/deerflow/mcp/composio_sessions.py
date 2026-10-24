"""Actor-owned Composio references; all credentials and transports stay transient."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID, uuid4

import httpx
from langchain_core.tools import StructuredTool, ToolException
from sqlalchemy import exists, or_, select

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.headers import apply_header_overrides, illegal_header_value_reason
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.persistence.organizations.resolution import active_organization_for_user, storage_user_id_for_organization
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER,
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    PRIVATE_MCP_SESSION_CONTEXT_KEY,
    PRIVATE_MCP_SESSION_MARKER,
    get_current_user,
    get_storage_context,
)
from deerflow.tools.mcp_metadata import tag_mcp_tool
from deerflow.tools.types import Runtime

SERVER_NAME = "composio-me"
SESSION_KEY = "__composio_me_session"
API_ORIGIN = "https://backend.composio.dev"
SESSION_PATH = "/api/v3.1/tool_router/session"
STAFF_ROLES = {"user", "exec", "admin"}
ROUTER_TOOLS = {"COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL"}
ENVELOPE_TOOL_NAME = "composio-me_call"
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
logger = logging.getLogger(__name__)


class ComposioSessionError(ToolException):
    """Only fixed host errors may cross the model boundary."""


_sensitive_transport = ContextVar("composio_sensitive_transport", default=False)


class _TransportLogFilter(logging.Filter):
    def filter(self, record):
        if _sensitive_transport.get():
            record.msg, record.args, record.exc_info, record.exc_text = "Composio transport event", (), None, None
        return True


# SDK/HTTPX logs include credential-bearing endpoints even when callers catch errors.
for _logger_name in ("httpx", "mcp.client.streamable_http", "mcp.client.sse", "mcp.shared.session", "mcp.shared._httpx_utils"):
    logging.getLogger(_logger_name).addFilter(_TransportLogFilter())


@contextmanager
def _private_transport():
    token = _sensitive_transport.set(True)
    try:
        yield
    finally:
        _sensitive_transport.reset(token)


@dataclass(frozen=True)
class ComposioContext:
    actor_user_id: str
    organization_id: str
    storage_user_id: str
    role: str
    thread_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class SessionReference:
    actor_user_id: str
    session_id: str


_run_context: ContextVar[ComposioContext | None] = ContextVar("composio_run_context", default=None)
_approval_context: ContextVar[ComposioContext | None] = ContextVar("composio_approval_context", default=None)
_browser_context: ContextVar[ComposioContext | None] = ContextVar("composio_browser_context", default=None)
_retry_execution = ContextVar("composio_retry_execution", default=False)
_RETRY_SEAL = object()


def _uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _authenticated_context() -> ComposioContext | None:
    user, scope = get_current_user(), get_storage_context()
    actor = _uuid(getattr(user, "id", None))
    role = getattr(user, "system_role", None)
    if actor is None or role not in STAFF_ROLES or getattr(user, "disabled_at", None) is not None or scope is None or _uuid(scope.actor_user_id) != actor or not scope.organization_id or not scope.storage_user_id:
        return None
    return ComposioContext(actor, scope.organization_id, scope.storage_user_id, role)


def _matches(context: object, scope: ComposioContext, *, runtime: bool) -> bool:
    return (
        isinstance(context, Mapping)
        and _uuid(context.get("actor_user_id")) == scope.actor_user_id
        and context.get("organization_id") == scope.organization_id
        and context.get("storage_user_id") == scope.storage_user_id
        and context.get("user_role") == scope.role
        and context.get("is_internal") is False
        and not any(key in context for key in ("channel_name", "public_news_channel"))
        and not any(context.get(key) for key in ("non_interactive", "disable_clarification", "is_subagent"))
        and (not runtime or (context.get("thread_id"), context.get("run_id")) == (scope.thread_id, scope.run_id))
    )


def bind_composio_context(context: object, *, thread_id: str, run_id: str) -> Token:
    """Worker-only binding from the original Gateway context before marker removal."""
    scope = _authenticated_context()
    if (
        scope is None
        or not _matches(context, scope, runtime=False)
        or context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is not AUTHENTICATED_CONTEXT_MARKER
        or context.get(PRIVATE_MCP_SESSION_CONTEXT_KEY) is not PRIVATE_MCP_SESSION_MARKER
        or not thread_id
        or not run_id
    ):
        scope = None
    else:
        scope = ComposioContext(scope.actor_user_id, scope.organization_id, scope.storage_user_id, scope.role, thread_id, run_id)
    return _run_context.set(scope)


def reset_composio_context(token: Token) -> None:
    _run_context.reset(token)


def bind_composio_approval_origin(*, actor_user_id: str, organization_id: str) -> Token:
    """Called only after the Gateway route checks the actual browser auth source."""
    scope = _authenticated_context()
    if scope is None or (scope.actor_user_id, scope.organization_id) != (_uuid(actor_user_id), organization_id):
        raise ComposioSessionError("composio_origin_denied")
    return _approval_context.set(scope)


def reset_composio_approval_origin(token: Token) -> None:
    _approval_context.reset(token)


@contextmanager
def composio_approval_origin(actor_user_id: str, organization_id: str):
    token = bind_composio_approval_origin(actor_user_id=actor_user_id, organization_id=organization_id)
    try:
        yield
    finally:
        reset_composio_approval_origin(token)


@contextmanager
def composio_browser_origin():
    """Gateway-only, after the actual request auth_source is checked as session."""
    scope = _authenticated_context()
    if scope is None:
        raise ComposioSessionError("composio_origin_denied")
    token = _browser_context.set(scope)
    try:
        yield
    finally:
        _browser_context.reset(token)


def current_browser_context():
    bound = _browser_context.get()
    if bound is None or bound != _authenticated_context():
        raise ComposioSessionError("composio_origin_denied")
    return bound


def current_composio_context(runtime: Any = None, *, approval: bool = False) -> ComposioContext:
    bound = (_approval_context if approval else _run_context).get()
    current = _authenticated_context()
    if bound is None or current is None or (bound.actor_user_id, bound.organization_id, bound.storage_user_id, bound.role) != (current.actor_user_id, current.organization_id, current.storage_user_id, current.role):
        raise ComposioSessionError("composio_origin_denied")
    if not approval and runtime is not None and not _matches(getattr(runtime, "context", None), bound, runtime=True):
        raise ComposioSessionError("composio_origin_denied")
    return bound


async def _require_staff(actor: str, scope: ComposioContext, sessions) -> None:
    async with sessions() as session:
        user = await session.get(UserRow, actor)
        organization = await active_organization_for_user(session, actor, scope.organization_id)
        bound_client = select(OrganizationRow.customer_client_id).where(OrganizationRow.id == scope.organization_id).scalar_subquery()
        contact = await session.scalar(
            select(
                exists().where(
                    ClientAssignmentRow.user_id == actor,
                    ClientAssignmentRow.role == "client_contact",
                    or_(ClientAssignmentRow.organization_id == scope.organization_id, ClientAssignmentRow.client_id == bound_client),
                )
            )
        )
    if (
        user is None
        or user.disabled_at is not None
        or user.system_role not in STAFF_ROLES
        or organization is None
        or organization.role not in {"owner", "admin", "member"}
        or storage_user_id_for_organization(organization, actor) != scope.storage_user_id
        or contact
        or (actor == scope.actor_user_id and user.system_role != scope.role)
    ):
        raise ComposioSessionError("composio_actor_denied")


def legacy_actor(config: ExtensionsConfig, actor: str) -> bool:
    server = config.mcp_servers.get("composio-sean")
    auth = server.user_auth if server is not None else None
    # Membership only: mapped credential values are never inspected.
    return auth is not None and auth.enabled and actor in auth.users


def _repository() -> UserPreferencesRepository:
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise ComposioSessionError("composio_persistence_unavailable")
    return UserPreferencesRepository(factory)


def _endpoint(data: object, session_id: str, actor: str, toolkits: list[str]) -> str:
    if not isinstance(data, dict):
        raise ComposioSessionError("composio_session_invalid")
    config = data.get("config")
    if not isinstance(config, dict) or config.get("user_id") != f"momobot-{actor}" or data.get("session_id") != session_id:
        raise ComposioSessionError("composio_session_owner_mismatch")
    enabled = config.get("toolkits", {}).get("enabled") if isinstance(config.get("toolkits"), dict) else None
    if not isinstance(enabled, list) or not all(isinstance(value, str) for value in enabled) or set(enabled) != set(toolkits) or len(enabled) != len(toolkits):
        raise ComposioSessionError("composio_session_policy_mismatch")
    mcp = data.get("mcp")
    if not isinstance(mcp, dict) or mcp.get("type") != "http" or not isinstance(mcp.get("url"), str):
        raise ComposioSessionError("composio_endpoint_denied")
    endpoint = mcp["url"]
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == "backend.composio.dev"
            and parsed.netloc == "backend.composio.dev"
            and parsed.port is None
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and not parsed.query
            and parsed.path == f"/tool_router/v3/{session_id}/mcp"
            and not any(ord(char) < 33 or ord(char) == 127 for char in endpoint)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ComposioSessionError("composio_endpoint_denied")
    return endpoint


async def _json_request(client: httpx.AsyncClient, method: str, path: str, key: str, authorize, **kwargs) -> dict:
    try:
        await authorize()
        with _private_transport():
            response = await client.request(method, API_ORIGIN + path, headers={"x-api-key": key}, follow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ComposioSessionError("composio_session_request_failed")
        data = response.json()
        if not isinstance(data, dict):
            raise ComposioSessionError("composio_session_invalid")
        return data
    except Exception as exc:
        logger.warning("Composio session request failed (%s)", type(exc).__name__)
        raise ComposioSessionError("composio_session_request_failed") from None


def _api_client():
    return httpx.AsyncClient(timeout=30, trust_env=False)


def _mcp_http_client(**kwargs):
    return httpx.AsyncClient(**kwargs)


async def _resolve_transport(runtime: Any, config: ExtensionsConfig, *, repository=None, http_client=None, action=None, allow_create=True, browser=False):
    scope = current_browser_context() if browser else current_composio_context(runtime, approval=action is not None)
    if action is None and runtime is None and not browser:
        raise ComposioSessionError("composio_origin_denied")
    repo = repository or _repository()
    actor = scope.actor_user_id
    if action is not None:
        actor = _uuid(action.get("user_id"))
        if actor is None or action.get("organization_id") != scope.organization_id or action.get("payload", {}).get("tool_name") not in ROUTER_TOOLS:
            raise ComposioSessionError("composio_approval_scope_denied")
        allow_create = False

    async def authorize():
        current_browser_context() if browser else current_composio_context(runtime, approval=action is not None)
        await _require_staff(scope.actor_user_id, scope, repo.sessions)
        await _require_staff(actor, scope, repo.sessions)
        if action is not None:
            from deerflow.persistence.approvals import PendingActionRepository

            current = await PendingActionRepository(repo.sessions).get_composio_for_approval(action["id"])
            if current is None or any(current[key] != action[key] for key in ("id", "user_id", "organization_id", "payload", "target", "thread_id", "run_id")):
                raise ComposioSessionError("composio_approval_scope_denied")

    await authorize()
    policy = config.composio_me
    if not policy.enabled or legacy_actor(config, actor):
        raise ComposioSessionError("composio_session_unavailable")
    key = os.getenv(policy.project_key_env)
    if not key or illegal_header_value_reason(key) is not None:
        raise ComposioSessionError("Composio is unavailable: the server project key is not configured.")
    stored = await repo.get_key(actor, SESSION_KEY)
    if stored is None and allow_create:
        nonce = uuid4().hex
        if await repo.reserve_key(actor, SESSION_KEY, {"state": "creating", "nonce": nonce}):
            try:

                async def create(client):
                    body = {"user_id": f"momobot-{actor}", "toolkits": {"enable": policy.toolkits}}
                    if policy.connect.enabled and policy.connect.auth_configs:
                        body["auth_configs"] = policy.connect.auth_configs
                    return await _json_request(client, "POST", SESSION_PATH, key, authorize, json=body)

                if http_client is None:
                    async with _api_client() as client:
                        created = await create(client)
                else:
                    created = await create(http_client)
                session_id = created.get("session_id")
                if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
                    raise ComposioSessionError("composio_session_invalid")
                stored = {"state": "ready", "session_id": session_id}
                if not await repo.finish_reserved_key(actor, SESSION_KEY, nonce, stored):
                    raise ComposioSessionError("composio_session_held")
            except Exception:
                await repo.finish_reserved_key(actor, SESSION_KEY, nonce, {"state": "uncertain", "nonce": nonce})
                raise ComposioSessionError("composio_session_held") from None
        else:
            stored = await repo.get_key(actor, SESSION_KEY)
    if not isinstance(stored, dict) or stored.get("state") != "ready":
        raise ComposioSessionError("composio_session_held")
    session_id = stored.get("session_id")
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ComposioSessionError("composio_session_held")

    async def lookup(client):
        return await _json_request(client, "GET", f"{SESSION_PATH}/{session_id}", key, authorize)

    if http_client is None:
        async with _api_client() as client:
            data = await lookup(client)
    else:
        data = await lookup(http_client)
    endpoint = _endpoint(data, session_id, actor, policy.toolkits)
    if policy.connect.enabled and any(data["config"].get("auth_configs", {}).get(toolkit) != identifier for toolkit, identifier in policy.connect.auth_configs.items()):
        raise ComposioSessionError("composio_session_policy_mismatch")
    return SessionReference(actor, session_id), endpoint, key


async def resolve_actor_session(runtime: Any, config: ExtensionsConfig, *, repository=None, http_client=None) -> SessionReference:
    """Minimal internal reference contract for future actor-bound connect routes."""
    reference, _, _ = await _resolve_transport(runtime, config, repository=repository, http_client=http_client)
    return reference


class ConnectManager:
    """Actor-owned OAuth attempts in protected KV; unknown writes remain held."""

    def __init__(self, config, *, runtime=None, repository=None):
        self.config, self.runtime, self.repo = config, runtime, repository or _repository()

    async def authorize(self):
        scope = current_browser_context() if self.runtime is None else current_composio_context(self.runtime)
        await _require_staff(scope.actor_user_id, scope, self.repo.sessions)
        current = await asyncio.to_thread(ExtensionsConfig.from_file)
        if current.composio_me != self.config.composio_me:
            raise ComposioSessionError("composio_policy_changed")
        if not self.config.composio_me.enabled or not self.config.composio_me.connect.enabled:
            raise ComposioSessionError("connect_disabled")
        if legacy_actor(self.config, scope.actor_user_id):
            raise ComposioSessionError("legacy_connection_managed_separately")
        return scope

    def unavailable(self, toolkit):
        if toolkit not in self.config.composio_me.toolkits:
            return "toolkit_not_allowed"
        if toolkit == "metaads":
            return "owner_setup_required_managed_oauth_unavailable"
        if toolkit == "fireflies":
            return "owner_setup_required_api_key"
        if toolkit == "composio_search":
            return "no_account_required"
        policy = self.config.composio_me.connect
        if not policy.callback_url or toolkit not in policy.auth_configs or not policy.authorization_origins:
            return "owner_setup_required"
        return None

    async def request(self, method, path, **kwargs):
        await self.authorize()
        key = os.getenv(self.config.composio_me.project_key_env)
        if not key or illegal_header_value_reason(key):
            raise ComposioSessionError("connect_project_key_unavailable")
        async with _api_client() as client:
            return await _json_request(client, method, path, key, self.authorize, **kwargs)

    def account_valid(self, account, scope, toolkit, account_id=None):
        if not isinstance(account, dict) or any(not isinstance(account.get(key), dict) for key in ("toolkit", "auth_config", "experimental")):
            return False
        return (
            isinstance(account, dict)
            and isinstance(account.get("id"), str)
            and bool(_SESSION_ID.fullmatch(account["id"]))
            and (account_id is None or account["id"] == account_id)
            and account.get("user_id") == f"momobot-{scope.actor_user_id}"
            and account.get("toolkit", {}).get("slug") == toolkit
            and account.get("status") == "ACTIVE"
            and account.get("is_disabled") is False
            and account.get("auth_config", {}).get("is_disabled") is False
            and account.get("auth_config", {}).get("id") == self.config.composio_me.connect.auth_configs.get(toolkit)
            and account.get("experimental", {}).get("account_type") == "PRIVATE"
        )

    async def accounts(self, toolkit):
        scope = await self.authorize()
        data = await self.request(
            "GET",
            "/api/v3.1/connected_accounts",
            params={"user_ids": [f"momobot-{scope.actor_user_id}"], "toolkit_slugs": [toolkit], "auth_config_ids": [self.config.composio_me.connect.auth_configs[toolkit]], "statuses": ["ACTIVE"], "account_type": "PRIVATE", "limit": 100},
        )
        items = data.get("items")
        if not isinstance(items, list) or data.get("next_cursor") or any(not self.account_valid(account, scope, toolkit) for account in items):
            raise ComposioSessionError("connection_verification_failed")
        if len(items) > 1:
            raise ComposioSessionError("connection_selection_required")
        return items

    async def status(self):
        await self.authorize()
        rows = []
        for toolkit in self.config.composio_me.toolkits:
            reason = self.unavailable(toolkit)
            connected = False
            if reason is None:
                try:
                    connected = bool(await self.accounts(toolkit))
                except ComposioSessionError:
                    reason = "connection_verification_unavailable"
            rows.append({"toolkit": toolkit, "connected": connected, "connectable": reason is None and not connected, "reason": reason})
        return rows

    @staticmethod
    def attempt_key(handle):
        if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24}", handle):
            raise ComposioSessionError("connect_attempt_not_found")
        return "__c_" + handle

    async def attempt(self, handle, *, nonce=None, account_id=None):
        scope = await self.authorize()
        value = await self.repo.get_key(scope.actor_user_id, self.attempt_key(handle))
        if not isinstance(value, dict) or value.get("organization_id") != scope.organization_id or value.get("storage_user_id") != scope.storage_user_id or value.get("handle") != handle or value.get("expires_at", 0) <= time.time():
            raise ComposioSessionError("connect_attempt_not_found")
        if nonce is not None and (not isinstance(nonce, str) or not hmac.compare_digest(nonce, value["nonce"])):
            raise ComposioSessionError("connect_nonce_denied")
        if account_id is not None and account_id != value.get("connected_account_id"):
            raise ComposioSessionError("connect_account_denied")
        return scope, value

    def redirect(self, value):
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme == "https"
                and parsed.netloc == parsed.hostname
                and f"https://{parsed.hostname}" in self.config.composio_me.connect.authorization_origins
                and bool(parsed.path)
                and not parsed.fragment
                and not any(ord(char) < 33 or ord(char) == 127 for char in value)
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ComposioSessionError("connect_redirect_denied")
        return value

    async def create(self, toolkit, *, intent=None):
        scope = await self.authorize()
        if intent is not None:
            from deerflow.mcp.composio_approval_guard import validate_composio_payload

            if not isinstance(intent, dict) or not intent.get("no_execution") or (intent.get("thread_id"), intent.get("run_id"), intent.get("toolkit")) != (scope.thread_id, scope.run_id, toolkit) or not scope.thread_id or not scope.run_id:
                raise ComposioSessionError("connect_retry_denied")
            validate_composio_payload(SERVER_NAME, {"server_name": SERVER_NAME, "tool_name": intent["tool_name"], "arguments": intent["arguments"], "tool_call_id": intent["tool_call_id"]})
        reason = self.unavailable(toolkit)
        if reason:
            raise ComposioSessionError(reason)
        if await self.accounts(toolkit):
            raise ComposioSessionError("already_connected")
        slot = "__cs_" + hashlib.sha256(f"{scope.organization_id}:{toolkit}".encode()).hexdigest()[:24]
        existing = await self.repo.get_key(scope.actor_user_id, slot)
        if isinstance(existing, dict):
            current_attempt = await self.repo.get_key(scope.actor_user_id, self.attempt_key(existing["handle"]))
            if not isinstance(current_attempt, dict) or current_attempt.get("state") != "ready" or current_attempt.get("nonce") != existing.get("nonce"):
                raise ComposioSessionError("connect_attempt_held")
            if existing.get("state") == "ready" and existing.get("expires_at", 0) > time.time():
                if intent is not None and existing.get("intent") != intent:
                    raise ComposioSessionError("connect_attempt_in_progress")
                return self.public(existing)
            if existing.get("state") != "ready":
                raise ComposioSessionError("connect_attempt_held")
        handle, nonce = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
        value = {
            "state": "creating",
            "nonce": nonce,
            "handle": handle,
            "actor_user_id": scope.actor_user_id,
            "organization_id": scope.organization_id,
            "storage_user_id": scope.storage_user_id,
            "toolkit": toolkit,
            "auth_config_id": self.config.composio_me.connect.auth_configs[toolkit],
            "expires_at": time.time() + self.config.composio_me.connect.ttl_seconds,
            "intent": intent,
        }
        won = await self.repo.transition_key(scope.actor_user_id, slot, existing["nonce"], "ready", value) if existing else await self.repo.reserve_key(scope.actor_user_id, slot, value)
        if not won:
            raise ComposioSessionError("connect_attempt_held")
        if not await self.repo.reserve_key(scope.actor_user_id, self.attempt_key(handle), value):
            raise ComposioSessionError("connect_attempt_held")
        try:
            reference, _, _ = await _resolve_transport(self.runtime, self.config, repository=self.repo, browser=self.runtime is None)
            callback = self.config.composio_me.connect.callback_url + "?handle=" + handle
            result = await self.request("POST", f"{SESSION_PATH}/{reference.session_id}/link", json={"toolkit": toolkit, "callback_url": callback})
            account_id = result.get("connected_account_id")
            if not isinstance(account_id, str) or not _SESSION_ID.fullmatch(account_id) or result.get("experimental", {}).get("account_type") != "PRIVATE":
                raise ComposioSessionError("connect_link_invalid")
            ready = {**value, "state": "ready", "connected_account_id": account_id, "redirect_url": self.redirect(result.get("redirect_url"))}
            if not await self.repo.finish_reserved_key(scope.actor_user_id, self.attempt_key(handle), nonce, ready) or not await self.repo.finish_reserved_key(scope.actor_user_id, slot, nonce, ready):
                raise ComposioSessionError("connect_attempt_held")
            return self.public(ready)
        except Exception:
            held = {**value, "state": "uncertain"}
            await self.repo.finish_reserved_key(scope.actor_user_id, self.attempt_key(handle), nonce, held)
            await self.repo.finish_reserved_key(scope.actor_user_id, slot, nonce, held)
            raise ComposioSessionError("connect_attempt_held") from None

    @staticmethod
    def public(value):
        from datetime import UTC, datetime

        return {"handle": value["handle"], "toolkit": value["toolkit"], "expires_at": datetime.fromtimestamp(value["expires_at"], UTC).isoformat()}

    async def open(self, handle):
        scope, value = await self.attempt(handle)
        if value["state"] != "ready" or not await self.repo.transition_key(scope.actor_user_id, self.attempt_key(handle), value["nonce"], "ready", {**value, "state": "opened"}):
            raise ComposioSessionError("connect_open_consumed")
        return self.redirect(value["redirect_url"]), value["nonce"]

    async def callback(self, handle, nonce, account_id):
        if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce):
            raise ComposioSessionError("connect_nonce_denied")
        scope, value = await self.attempt(handle, nonce=nonce, account_id=account_id)
        if value.get("auth_config_id") != self.config.composio_me.connect.auth_configs.get(value["toolkit"]):
            raise ComposioSessionError("connection_verification_failed")
        if value["state"] in {"complete", "connected"}:
            return value
        if value["state"] != "opened" or not await self.repo.transition_key(scope.actor_user_id, self.attempt_key(handle), value["nonce"], "opened", {**value, "state": "verifying"}):
            raise ComposioSessionError("connect_attempt_held")
        try:
            data = await self.request("GET", "/api/v3.1/connected_accounts/" + account_id)
            if not self.account_valid(data, scope, value["toolkit"], account_id):
                raise ComposioSessionError("connection_verification_failed")
            accounts = await self.accounts(value["toolkit"])
            if len(accounts) != 1 or accounts[0]["id"] != account_id:
                raise ComposioSessionError("connection_verification_failed")
            connected = {**value, "state": "connected", "redirect_url": None}
            if not await self.repo.transition_key(scope.actor_user_id, self.attempt_key(handle), value["nonce"], "verifying", connected):
                raise ComposioSessionError("connect_attempt_held")
            return connected
        except Exception:
            await self.repo.transition_key(scope.actor_user_id, self.attempt_key(handle), value["nonce"], "verifying", {**value, "state": "uncertain", "redirect_url": None})
            raise ComposioSessionError("connection_verification_failed") from None

    async def claim_dispatch(self, value):
        scope = await self.authorize()
        return await self.repo.transition_key(scope.actor_user_id, self.attempt_key(value["handle"]), value["nonce"], "connected", {**value, "state": "dispatching"})

    async def settle_dispatch(self, value, reply):
        scope = await self.authorize()
        if not await self.repo.transition_key(scope.actor_user_id, self.attempt_key(value["handle"]), value["nonce"], "dispatching", {**value, "state": "complete", "reply": reply}):
            raise ComposioSessionError("connect_attempt_held")

    async def preflight(self, tool_name, arguments):
        """A local no-execution failure, never an inferred provider error/replay."""
        if tool_name != "COMPOSIO_MULTI_EXECUTE_TOOL" or not isinstance(arguments, dict) or not isinstance(arguments.get("tools"), list) or len(arguments["tools"]) != 1:
            return None
        from deerflow.mcp.composio_approval_guard import validate_composio_payload

        scope = await self.authorize()
        call_id = getattr(self.runtime, "tool_call_id", None)
        inner = arguments["tools"][0]
        slug = inner.get("tool_slug") if isinstance(inner, dict) else None
        if not call_id or not isinstance(slug, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", slug):
            return None
        # Exact reviewed public actions, not a name-prefix auth inference.
        if slug in {"COMPOSIO_SEARCH_WEB", "COMPOSIO_SEARCH_NEWS", "COMPOSIO_SEARCH_TRENDS", "COMPOSIO_SEARCH_GOOGLE_MAPS", "COMPOSIO_SEARCH_EXA_SIMILARLINK", "COMPOSIO_SEARCH_NPPESNPI_LOOKUP"}:
            return None
        validate_composio_payload(SERVER_NAME, {"server_name": SERVER_NAME, "tool_name": tool_name, "arguments": arguments, "tool_call_id": call_id})
        try:
            definition = await self.request("GET", "/api/v3.1/tools/" + slug)
        except ComposioSessionError:
            raise ComposioSessionError("connect_tool_metadata_unavailable") from None
        toolkit = definition["toolkit"].get("slug") if isinstance(definition.get("toolkit"), dict) else None
        if definition.get("slug") != slug or definition.get("no_auth") is not False or toolkit not in self.config.composio_me.toolkits or self.unavailable(toolkit):
            return None
        if await self.accounts(toolkit):
            return None
        intent = {"thread_id": scope.thread_id, "run_id": scope.run_id, "tool_call_id": call_id, "tool_name": tool_name, "arguments": arguments, "toolkit": toolkit, "no_execution": True}
        attempt = await self.create(toolkit, intent=intent)
        return {"status": "no_connected_account", "no_execution": True, "connect": {"handle": attempt["handle"], "toolkit": toolkit}}


@dataclass(frozen=True, repr=False)
class ComposioRetry:
    handle: str
    nonce: str
    actor_user_id: str
    organization_id: str
    storage_user_id: str
    intent: dict
    seal: object

    @classmethod
    def from_attempt(cls, value):
        return cls(value["handle"], value["nonce"], value["actor_user_id"], value["organization_id"], value["storage_user_id"], json.loads(json.dumps(value["intent"])), _RETRY_SEAL)

    async def verify(self, thread_id, *, runtime=None):
        if self.seal is not _RETRY_SEAL or not self.intent.get("no_execution") or self.intent.get("thread_id") != thread_id:
            raise ComposioSessionError("connect_retry_denied")
        scope = current_composio_context(runtime) if runtime is not None else current_browser_context()
        if (scope.actor_user_id, scope.organization_id, scope.storage_user_id) != (self.actor_user_id, self.organization_id, self.storage_user_id):
            raise ComposioSessionError("connect_retry_denied")
        repo = _repository()
        await _require_staff(scope.actor_user_id, scope, repo.sessions)
        config = await asyncio.to_thread(ExtensionsConfig.from_file)
        await ConnectManager(config, runtime=runtime, repository=repo).authorize()
        value = await repo.get_key(scope.actor_user_id, ConnectManager.attempt_key(self.handle))
        if (
            not isinstance(value, dict)
            or value.get("state") not in {"dispatching", "complete"}
            or value.get("nonce") != self.nonce
            or value.get("intent") != self.intent
            or value.get("organization_id") != self.organization_id
            or value.get("expires_at", 0) <= time.time()
        ):
            raise ComposioSessionError("connect_retry_denied")
        if value["state"] == "complete":
            submitted = value.get("reply", {}).get("retry", {})
            if runtime is None or submitted.get("state") != "submitted" or submitted.get("run_id") != scope.run_id:
                raise ComposioSessionError("connect_retry_denied")

    def input(self):
        return {"messages": [{"type": "ai", "content": "", "tool_calls": [{"name": ENVELOPE_TOOL_NAME, "args": {"tool_name": self.intent["tool_name"], "arguments": self.intent["arguments"]}, "id": self.intent["tool_call_id"]}]}]}

    def factory(self, *, config, app_config=None):
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode

        from deerflow.agents.thread_state import get_thread_state_schema
        from deerflow.runtime.checkpoint_mode import INTERNAL_CHECKPOINT_MODE_KEY

        scope = current_composio_context()
        if self.seal is not _RETRY_SEAL or (scope.actor_user_id, scope.organization_id, scope.storage_user_id, scope.thread_id) != (self.actor_user_id, self.organization_id, self.storage_user_id, self.intent["thread_id"]):
            raise ComposioSessionError("connect_retry_denied")
        tools = composio_tools(config.get("context"), ExtensionsConfig.from_file())
        if len(tools) != 1:
            raise ComposioSessionError("connect_retry_denied")

        async def exact_call(tool_name: RouterToolName, arguments: dict[str, Any] | None = None, runtime: Runtime = None):
            await self.verify(self.intent["thread_id"], runtime=runtime)
            if tool_name != self.intent["tool_name"] or arguments != self.intent["arguments"]:
                raise ComposioSessionError("connect_retry_denied")
            token = _retry_execution.set(True)
            try:
                return await tools[0].coroutine(tool_name=tool_name, arguments=arguments, runtime=runtime)
            finally:
                _retry_execution.reset(token)

        tool = StructuredTool.from_function(name=ENVELOPE_TOOL_NAME, description="Retry one verified connection-blocked call", coroutine=exact_call, response_format="content_and_artifact")
        schema = get_thread_state_schema((config.get("configurable") or {}).get(INTERNAL_CHECKPOINT_MODE_KEY, "full"))
        builder = StateGraph(schema)
        builder.add_node("tools", ToolNode([tool], handle_tool_errors=False))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        return builder.compile()


async def _reject_redirect(response: httpx.Response) -> None:
    if 300 <= response.status_code < 400:
        raise ComposioSessionError("composio_redirect_denied")


async def resolve_approval_server(action: dict, config: ExtensionsConfig) -> McpServerConfig:
    _, endpoint, key = await _resolve_transport(None, config, action=action, allow_create=False)
    return McpServerConfig(type="http", url=endpoint, headers={"x-api-key": key})


async def _load_current_tools(runtime: Any, config: ExtensionsConfig, *, action=None):
    from langchain_mcp_adapters.client import MultiServerMCPClient

    from deerflow.mcp.composio_approval_authority import current_composio_authority
    from deerflow.mcp.interceptors import build_mcp_tool_interceptors
    from deerflow.mcp.tools import _resolve_session_init_timeout

    _, endpoint, key = await _resolve_transport(runtime, config, action=action)
    server = McpServerConfig(type="http", url=endpoint, headers={"x-api-key": key})
    selected = config.model_copy(update={"mcp_servers": {SERVER_NAME: server}})

    async def authorize():
        current_composio_context(runtime, approval=action is not None)
        repo = _repository()
        scope = current_composio_context(runtime, approval=action is not None)
        await _require_staff(scope.actor_user_id, scope, repo.sessions)
        current_config = await asyncio.to_thread(ExtensionsConfig.from_file)
        if current_config.composio_me != config.composio_me or not current_config.composio_me.enabled or os.getenv(config.composio_me.project_key_env) != key:
            raise ComposioSessionError("composio_policy_changed")
        if action is not None:
            authority = current_composio_authority()
            if authority is None or authority.action_id != action["id"]:
                raise ComposioSessionError("composio_approval_scope_denied")
            await authority.verify()

    async def check_request(request):
        if request.method != "POST" or str(request.url) != endpoint:
            raise ComposioSessionError("composio_endpoint_denied")
        await authorize()

    def factory(headers=None, timeout=None, auth=None):
        return _mcp_http_client(headers=headers, timeout=timeout or 30, auth=auth, trust_env=False, follow_redirects=False, event_hooks={"request": [check_request], "response": [_reject_redirect]})

    async def inject_headers(request, handler):
        await authorize()
        return await handler(request.override(headers=apply_header_overrides(request.headers, server.headers)))

    async def final_scope(request, handler):
        await authorize()
        headers = request.headers or {}
        if len({name.lower() for name in headers}) != len(headers) or {name.lower(): value for name, value in headers.items()} != server.headers:
            raise ComposioSessionError("composio_headers_changed")
        return await handler(request)

    interceptors = build_mcp_tool_interceptors(selected)
    interceptors.insert(1, inject_headers)
    interceptors.insert(-1, final_scope)
    client = MultiServerMCPClient(
        {SERVER_NAME: {"transport": "http", "url": endpoint, "headers": {"x-api-key": key}, "terminate_on_close": False, "httpx_client_factory": factory}},
        tool_interceptors=interceptors,
        tool_name_prefix=True,
    )
    try:
        with _private_transport():
            discovery = client.get_tools(server_name=SERVER_NAME)
            timeout = _resolve_session_init_timeout(server)
            return await discovery if timeout is None else await asyncio.wait_for(discovery, timeout=timeout)
    except Exception as exc:
        logger.warning("Composio MCP discovery failed (%s)", type(exc).__name__)
        raise ComposioSessionError("composio_transport_unavailable") from None


async def load_current_composio_tool(tool_name: str, runtime: Any, config: ExtensionsConfig, *, action=None):
    if tool_name not in ROUTER_TOOLS:
        raise ComposioSessionError("composio_tool_denied")
    tools = await _load_current_tools(runtime, config, action=action)
    matches = [tool for tool in tools if tool.name == f"{SERVER_NAME}_{tool_name}"]
    if len(matches) != 1:
        raise ComposioSessionError("composio_tool_unavailable")
    tool = matches[0]

    async def private_call(runtime: Runtime = None, **arguments):
        with _private_transport():
            return await tool.coroutine(runtime=runtime, **arguments)

    return StructuredTool(name=tool.name, description=tool.description, args_schema=tool.args_schema, coroutine=private_call, response_format=tool.response_format)


def _structural_schema(schema: object, *, secret: str | None = None) -> dict:
    """Retain structure only: provider defaults/descriptions/examples may be private."""
    if not isinstance(schema, dict) or len(json.dumps(schema)) > 32768:
        raise ComposioSessionError("composio_schema_unavailable")

    def structural(node, depth=0):
        if not isinstance(node, dict) or depth > 12:
            raise ComposioSessionError("composio_schema_unavailable")
        result = {}
        kind = node.get("type")
        kinds = {"object", "array", "string", "number", "integer", "boolean", "null"}
        if isinstance(kind, str) and kind in kinds:
            result["type"] = kind
        elif isinstance(kind, list) and all(item in kinds for item in kind):
            result["type"] = kind
        for name in ("properties", "$defs"):
            entries = node.get(name)
            if isinstance(entries, dict):
                if len(entries) > 100 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,127}", key) or (secret and secret in key) for key in entries):
                    raise ComposioSessionError("composio_schema_unavailable")
                result[name] = {key: structural(value, depth + 1) for key, value in entries.items() if key != "runtime"}
        required = node.get("required")
        if isinstance(required, list):
            result["required"] = [key for key in required if key in result.get("properties", {})]
        for name in ("items", "additionalProperties"):
            value = node.get(name)
            if isinstance(value, dict):
                result[name] = structural(value, depth + 1)
            elif isinstance(value, bool):
                result[name] = value
        for name in ("anyOf", "oneOf", "allOf"):
            value = node.get(name)
            if isinstance(value, list) and len(value) <= 20:
                result[name] = [structural(item, depth + 1) for item in value]
        reference = node.get("$ref")
        if isinstance(reference, str):
            if not re.fullmatch(r"#/\$defs/[A-Za-z_][A-Za-z0-9_-]{0,127}", reference) or (secret and secret in reference):
                raise ComposioSessionError("composio_schema_unavailable")
            result["$ref"] = reference
        return result

    return structural(schema)


def _safe_result(result, config):
    # Guided-connect cards come from host preflight; provider links stay private.
    serialized = json.dumps(result, default=lambda value: value.model_dump() if hasattr(value, "model_dump") else str(value))
    key = os.getenv(config.composio_me.project_key_env)
    if len(serialized) > 131072:
        return {"status": "connection_setup_unavailable"}, None

    connection_links = []

    def embedded_json(value, json_depth):
        if not value.lstrip().startswith(("{", "[")):
            return None
        try:
            decoded = json.loads(value)
        except ValueError:
            return None
        except RecursionError:
            raise ComposioSessionError("composio_result_unavailable") from None
        if isinstance(decoded, (dict, list)):
            if json_depth >= 8:
                raise ComposioSessionError("composio_result_unavailable")
            return decoded
        return None

    def field_scope(name, connection):
        field = re.sub(r"[^a-z]", "", name.lower())
        container = field in {"connection", "connections", "connectionsetup", "connect", "auth", "authentication", "oauth"}
        link = container or field in {
            "authurl",
            "authuri",
            "authenticationurl",
            "authenticationuri",
            "authorizationurl",
            "authorizationuri",
            "oauthurl",
            "oauthuri",
            "connecturl",
            "connecturi",
            "connectionurl",
            "connectionuri",
            "consenturl",
            "consenturi",
        }
        link = link or (connection and field in {"url", "uri", "href", "link", "redirect", "redirecturl", "redirecturi", "callbackurl", "callbackuri"})
        return connection or container, link

    def collect_connection_links(value, *, connection=False, connection_url=False, json_depth=0):
        # Classify explicit connection links before aliases in other fields.
        if isinstance(value, dict):
            for name, item in value.items():
                if connection:
                    connection_links.extend(re.findall(r"https?://[^\s\"<>]+", name, re.IGNORECASE))
                child, link = field_scope(name, connection)
                collect_connection_links(item, connection=child, connection_url=link, json_depth=json_depth)
        elif isinstance(value, list):
            for item in value:
                collect_connection_links(item, connection=connection, connection_url=connection_url, json_depth=json_depth)
        elif isinstance(value, str):
            decoded = embedded_json(value, json_depth)
            if decoded is not None:
                collect_connection_links(decoded, connection=connection, connection_url=connection_url, json_depth=json_depth + 1)
            elif connection_url:
                connection_links.extend(re.findall(r"https?://[^\s\"<>]+", value, re.IGNORECASE))

    def credential_parameters(component):
        for name, _ in parse_qsl(unquote(component)):
            name = re.sub(r"[^a-z0-9]", "", name.lower())
            if name.endswith(("token", "key")) or name in {"code", "state", "signature", "password", "passwd", "secret", "clientsecret", "session", "sessionid", "authorization"}:
                return True
        return False

    def unsafe(value, *, connection_url=False):
        if (key and key in value) or any(link in value for link in connection_links):
            return True
        for url in re.findall(r"https?://[^\s\"<>]+", value, re.IGNORECASE):
            try:
                parsed = urlsplit(url)
                host = (parsed.hostname or "").lower().rstrip(".")
                session_url = (host == "composio.dev" or host.endswith(".composio.dev")) and parsed.path.startswith(("/tool_router/", "/api/v3.1/tool_router/session", "/v3/mcp/"))
                if connection_url or not host or parsed.username is not None or parsed.password is not None or session_url or credential_parameters(parsed.query) or credential_parameters(parsed.fragment):
                    return True
            except ValueError:
                return True
        return False

    def sanitize(value, *, connection=False, connection_url=False, json_depth=0):
        if isinstance(value, dict):
            result = {}
            for name, item in value.items():
                if unsafe(name, connection_url=connection):
                    continue
                field = re.sub(r"[^a-z]", "", name.lower())
                if field in {"headers", "authorization", "apikey", "projectkey", "accesstoken", "refreshtoken"}:
                    result[name] = "[redacted]"
                    continue
                child, link = field_scope(name, connection)
                result[name] = sanitize(item, connection=child, connection_url=link, json_depth=json_depth)
            return result
        if isinstance(value, list):
            return [sanitize(item, connection=connection, connection_url=connection_url, json_depth=json_depth) for item in value]
        if isinstance(value, str):
            decoded = embedded_json(value, json_depth)
            if decoded is not None:
                return json.dumps(sanitize(decoded, connection=connection, connection_url=connection_url, json_depth=json_depth + 1), ensure_ascii=False)
            value = re.sub(r"https?://[^\s\"<>]+", lambda match: "[connection setup unavailable]" if unsafe(match[0], connection_url=connection_url) else match[0], value, flags=re.IGNORECASE)
            return value.replace(key, "[redacted]") if key else value
        return value

    decoded = json.loads(serialized)
    collect_connection_links(decoded)
    sanitized = sanitize(decoded)
    return tuple(sanitized) if isinstance(result, tuple) else sanitized


RouterToolName = Literal["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS", "COMPOSIO_MULTI_EXECUTE_TOOL"]


def composio_tools(run_context: object, config: ExtensionsConfig) -> list[StructuredTool]:
    try:
        scope = current_composio_context()
    except ComposioSessionError:
        return []
    if not config.composio_me.enabled or not _matches(run_context, scope, runtime=True) or legacy_actor(config, scope.actor_user_id):
        return []

    async def call(tool_name: RouterToolName, arguments: dict[str, Any] | None = None, runtime: Runtime = None):
        if tool_name not in ROUTER_TOOLS:
            raise ComposioSessionError("composio_tool_denied")
        current_composio_context(runtime)
        try:
            current_config = await asyncio.to_thread(ExtensionsConfig.from_file)
            if arguments is not None and current_config.composio_me.connect.enabled and not _retry_execution.get():
                blocked = await ConnectManager(current_config, runtime=runtime).preflight(tool_name, arguments)
                if blocked is not None:
                    return blocked, None
            tool = await load_current_composio_tool(tool_name, runtime, current_config)
            if arguments is None:
                schema = tool.args_schema
                if not isinstance(schema, dict):
                    schema = schema.model_json_schema()
                return {"tool_name": tool_name, "input_schema": _structural_schema(schema, secret=os.getenv(current_config.composio_me.project_key_env))}, None
            return _safe_result(await tool.coroutine(runtime=runtime, **arguments), current_config)
        except ComposioSessionError:
            raise
        except Exception as exc:
            logger.warning("Composio tool call failed (%s)", type(exc).__name__)
            raise ComposioSessionError("composio_call_failed") from None

    return [
        tag_mcp_tool(
            StructuredTool.from_function(
                name=ENVELOPE_TOOL_NAME,
                description="Your Composio connection. Omit arguments to inspect current input schema; pass a JSON object to invoke. Writes require approval. Connection prompts use opaque browser handles when enabled.",
                coroutine=call,
                response_format="content_and_artifact",
            ),
            server_name=SERVER_NAME,
            transport="http",
        )
    ]
