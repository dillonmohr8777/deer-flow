"""Staff memory namespaces, bound by the host rather than request identifiers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from langchain_core.messages import SystemMessage

STAFF_MEMORY_SCOPE_KEY = "__deerflow_staff_memory_scope"
STAFF_MEMORY_PROVENANCE_KEY = "deerflow_memory_scope"
_STAFF_ROLES = {"user", "exec", "admin"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryScope:
    user_id: str
    agent_name: str | None
    actor_user_id: str | None = None
    organization_id: str | None = None
    storage_user_id: str | None = None
    user_role: str | None = None
    organization_role: str | None = None
    # Current-run creation proof; persisted hashes alone never grant authority.
    boundary_ids: set[str] = field(default_factory=set, compare=False, repr=False)

    @property
    def isolated(self) -> bool:
        return self.actor_user_id is not None


def momo_memory_enabled() -> bool:
    """Staff memory scoping is on only when MomoBot Max is enabled."""
    from deerflow.config.app_config import get_app_config

    return get_app_config().momobot_max.enabled


def staff_memory_scope(context: Mapping, *, agent_name: str | None, client_id: str | None = None) -> MemoryScope | None:
    """Mint only after host authentication, agent admission and client validation.

    ``client_id`` is supplied by the host's portal binding lookup, never by the
    free-form context. Non-memory storage resolution is deliberately unchanged.
    """
    from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER, AUTHENTICATED_CONTEXT_MARKER_KEY

    if context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is not AUTHENTICATED_CONTEXT_MARKER:
        return None
    actor, storage, role = (context.get(key) for key in ("actor_user_id", "storage_user_id", "user_role"))
    organization, organization_role = context.get("organization_id"), context.get("organization_role")
    if not all(isinstance(value, str) and value for value in (actor, storage)) or not isinstance(role, str) or role not in _STAFF_ROLES:
        return None
    if client_id is not None and (not isinstance(client_id, str) or not client_id or not organization):
        return None
    # Roles gate admission above but stay out of the key: a promotion must not rotate the bucket.
    parts = ["staff-memory-v1", actor, organization, storage, agent_name, client_id]
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return MemoryScope(f"staff-v1-{digest}", agent_name, actor, organization, storage, role, organization_role)


def private_memory_scope(user: object | None, workspace: object | None, *, agent_name: str | None) -> MemoryScope | None:
    """Bind host management APIs to authenticated, unbound private memory only."""
    from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER, AUTHENTICATED_CONTEXT_MARKER_KEY

    actor = str(user.id) if user is not None else None
    if not actor or workspace is not None and workspace.actor_user_id != actor:
        return None
    return staff_memory_scope(
        {
            AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
            "actor_user_id": actor,
            "storage_user_id": workspace.storage_user_id if workspace else actor,
            "organization_id": workspace.organization_id if workspace else None,
            "organization_role": workspace.role if workspace else None,
            "user_role": getattr(user, "system_role", None),
        },
        agent_name=agent_name,
    )


def _matches_active_identity(scope: MemoryScope, runtime: object | None) -> bool:
    from deerflow.runtime.user_context import get_current_user, get_storage_context

    server_user = getattr(getattr(runtime, "server_info", None), "user", None)
    if server_user is not None:
        from deerflow.config.paths import make_safe_user_id

        identity = server_user.get("identity") if isinstance(server_user, Mapping) else getattr(server_user, "identity", None)
        role = server_user.get("system_role") if isinstance(server_user, Mapping) else getattr(server_user, "system_role", None)
        if not isinstance(identity, str) or make_safe_user_id(identity) != make_safe_user_id(scope.actor_user_id) or role is not None and role != scope.user_role:
            return False
    user = get_current_user()
    workspace = get_storage_context()
    role = getattr(user, "system_role", None)
    # Delegated internal runs (scheduled tasks, IM) carry the gateway's role-less
    # storage-principal user; the actor is proven by the scope and storage context.
    if user is not None and role is not None:
        if str(user.id) != scope.actor_user_id or (role != scope.user_role and (role != "internal" or workspace is None)):
            return False
    return workspace is None or (workspace.actor_user_id, workspace.organization_id, workspace.storage_user_id, workspace.role) == (scope.actor_user_id, scope.organization_id, scope.storage_user_id, scope.organization_role)


def _agent_server_scope(runtime: object, agent_name: str) -> MemoryScope | None:
    from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER, AUTHENTICATED_CONTEXT_MARKER_KEY, get_current_user, get_storage_context

    server_user = getattr(getattr(runtime, "server_info", None), "user", None)
    if server_user is None:
        try:
            from langgraph.config import get_config

            server_user = get_config().get("configurable", {}).get("langgraph_auth_user")
        except RuntimeError:
            return None
    identity = server_user.get("identity") if isinstance(server_user, Mapping) else getattr(server_user, "identity", None)
    role = server_user.get("system_role") if isinstance(server_user, Mapping) else getattr(server_user, "system_role", None)
    if not isinstance(identity, str) or not identity:
        return None
    from deerflow.config.paths import make_safe_user_id

    safe_actor = make_safe_user_id(identity)
    current = get_current_user()
    if current is not None:
        if make_safe_user_id(str(current.id)) != safe_actor:
            return None
        role = getattr(current, "system_role", None)
    workspace = get_storage_context()
    if workspace is not None and make_safe_user_id(workspace.actor_user_id) != safe_actor:
        return None
    actor = workspace.actor_user_id if workspace else str(current.id) if current else identity
    return staff_memory_scope(
        {
            AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
            "actor_user_id": actor,
            "storage_user_id": workspace.storage_user_id if workspace else safe_actor,
            "organization_id": workspace.organization_id if workspace else None,
            "organization_role": workspace.role if workspace else None,
            "user_role": role,
        },
        agent_name=agent_name,
    )


def resolve_memory_scope(runtime: object | None, agent_name: str | None) -> MemoryScope | None:
    """Resolve one scope for recall, capture and tools; ambiguous Max runs deny.

    Legacy non-Momo embedded callers retain their existing memory interface.
    Gateway staff runs carry a typed scope for every admitted agent. Agent
    Server can establish a private Max scope from its authenticated user, but
    a request-supplied workspace or client never selects a namespace.
    """
    from deerflow.runtime.user_context import resolve_runtime_user_id

    context = getattr(runtime, "context", None)
    scope = context.get(STAFF_MEMORY_SCOPE_KEY) if isinstance(context, Mapping) else None
    if isinstance(scope, MemoryScope):
        if scope.agent_name == agent_name and _matches_active_identity(scope, runtime):
            return scope
        return None
    if isinstance(context, Mapping) and STAFF_MEMORY_SCOPE_KEY in context:
        logger.warning("Staff memory unavailable: host scope binding is invalid")
        return None
    if agent_name != "momobot-max":
        return MemoryScope(resolve_runtime_user_id(runtime), agent_name)
    scope = _agent_server_scope(runtime, agent_name)
    if scope is None:
        logger.warning("Staff Max memory unavailable: trusted actor/workspace/role binding is missing")
    elif isinstance(context, dict):
        context[STAFF_MEMORY_SCOPE_KEY] = scope
    return scope


def trusted_scope_boundary(message: object, scope: MemoryScope, runtime: object | None) -> bool:
    from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

    context = getattr(runtime, "context", None)
    prior = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY, ()) if isinstance(context, Mapping) else ()
    return (
        isinstance(message, SystemMessage)
        and message.additional_kwargs.get("dynamic_context_reminder") is True
        and message.additional_kwargs.get(STAFF_MEMORY_PROVENANCE_KEY) == scope.user_id
        and (message.id in scope.boundary_ids or isinstance(prior, (set, frozenset, list, tuple)) and message.id in prior)
    )


def scoped_capture_messages(messages: list, scope: MemoryScope, runtime: object | None) -> list:
    """Never import unmarked or foreign checkpoint history into a fresh scope."""
    if not scope.isolated:
        return messages
    for index in reversed(range(len(messages))):
        if trusted_scope_boundary(messages[index], scope, runtime):
            return messages[index + 1 :]
    logger.warning("Staff memory capture skipped: no trusted current-scope transcript boundary")
    return []
