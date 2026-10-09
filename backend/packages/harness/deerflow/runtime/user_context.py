"""Request-scoped user context for user-based authorization.

This module holds a :class:`~contextvars.ContextVar` that the gateway's
auth middleware sets after a successful authentication. Repository
methods read the contextvar via a sentinel default parameter, letting
routers stay free of ``user_id`` boilerplate.

Three-state semantics for the repository ``user_id`` parameter (the
consumer side of this module lives in ``deerflow.persistence.*``):

- ``_AUTO`` (module-private sentinel, default): read from contextvar;
  raise :class:`RuntimeError` if unset.
- Explicit ``str``: use the provided value, overriding contextvar.
- Explicit ``None``: no WHERE clause — used only by migration scripts
  and admin CLIs that intentionally bypass isolation.

Dependency direction
--------------------
``persistence`` (lower layer) reads from this module; ``gateway.auth``
(higher layer) writes to it. ``CurrentUser`` is defined here as a
:class:`typing.Protocol` so that ``persistence`` never needs to import
the concrete ``User`` class from ``gateway.auth.models``. Any object
with an ``.id: str`` attribute structurally satisfies the protocol.

Asyncio semantics
-----------------
``ContextVar`` is task-local under asyncio, not thread-local. Each
FastAPI request runs in its own task, so the context is naturally
isolated. ``asyncio.create_task`` and ``asyncio.to_thread`` inherit the
parent task's context, which is typically the intended behaviour; if
a background task must *not* see the foreground user, wrap it with
``contextvars.copy_context()`` to get a clean copy.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    """Structural type for the current authenticated user.

    Any object with an ``.id: str`` attribute satisfies this protocol.
    Concrete implementations live in ``app.gateway.auth.models.User``.
    """

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)

# The Gateway stamps these fields after authentication.  The marker is an
# in-process capability: it lets the run worker distinguish the values that
# were written by ``inject_authenticated_user_context`` from a caller's
# ordinary ``RunnableConfig.context`` without persisting a secret or relying
# on a user-controlled boolean.  The worker consumes and removes the marker
# before exposing ``ToolRuntime.context``.
AUTHENTICATED_CONTEXT_MARKER_KEY: Final[str] = "__deerflow_authenticated_context"
AUTHENTICATED_CONTEXT_MARKER: Final[object] = object()

WORKSPACE_IDENTITY_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "actor_user_id",
        "storage_user_id",
        "organization_id",
        "organization_role",
    }
)


@dataclass(frozen=True, slots=True)
class WorkspaceStorageContext:
    """Server-selected workspace identity for shared resource storage.

    ``actor_user_id`` is the authenticated human. ``storage_user_id`` is the
    owner bucket used by repositories and filesystem paths; it equals the
    actor for private organizations and is a dedicated non-login principal for
    shared workspaces. The two identities must not be conflated.
    """

    actor_user_id: str
    organization_id: str | None
    storage_user_id: str
    role: str | None = None


StorageContext = WorkspaceStorageContext
_storage_context: Final[ContextVar[WorkspaceStorageContext | None]] = ContextVar("deerflow_storage_context", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Set the current user for this async task.

    Returns a reset token that should be passed to
    :func:`reset_current_user` in a ``finally`` block to restore the
    previous context.
    """
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the context to the state captured by ``token``."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or ``None`` if unset.

    Safe to call in any context. Used by code paths that can proceed
    without a user (e.g. migration scripts, public endpoints).
    """
    return _current_user.get()


def set_storage_context(context: WorkspaceStorageContext) -> Token[WorkspaceStorageContext | None]:
    """Set the server-validated workspace storage identity for this task."""

    if not context.actor_user_id or not context.storage_user_id:
        raise ValueError("workspace storage context requires actor and storage user ids")
    return _storage_context.set(context)


def reset_storage_context(token: Token[WorkspaceStorageContext | None]) -> None:
    """Restore the previous workspace storage context."""

    _storage_context.reset(token)


def get_storage_context() -> WorkspaceStorageContext | None:
    """Return the server-validated workspace context, if one is active."""

    return _storage_context.get()


def get_workspace_actor_user_id() -> str | None:
    """Return the authenticated actor id without changing storage scoping."""

    context = _storage_context.get()
    if context is not None:
        return context.actor_user_id
    user = _current_user.get()
    return str(user.id) if user is not None else None


def require_current_user() -> CurrentUser:
    """Return the current user, or raise :class:`RuntimeError`.

    Used by repository code that must not be called outside a
    request-authenticated context. The error message is phrased so
    that a caller debugging a stack trace can locate the offending
    code path.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the active storage principal, or DEFAULT_USER_ID if unset.

    Unlike :func:`require_current_user` this never raises — it is designed
    for filesystem-path resolution where a valid user bucket is always needed.
    A shared workspace supplies its dedicated principal; private requests fall
    back to the authenticated actor for backwards compatibility.
    """
    context = _storage_context.get()
    if context is not None:
        return context.storage_user_id
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def get_effective_storage_user_id() -> str:
    """Explicit spelling for callers that need the workspace storage bucket."""

    return get_effective_user_id()


def get_effective_actor_user_id() -> str:
    """Return the authenticated actor id, with the legacy default fallback."""

    return get_workspace_actor_user_id() or DEFAULT_USER_ID


def resolve_organization_id() -> str | None:
    """Return the request's server-resolved active organization, if any.

    Only ``AuthMiddleware`` sets it, after proving the session or PAT caller's
    active membership, so no request field can choose it. ``None`` (internal
    callers, auth-disabled mode, work outside a request) means no organization
    boundary was established: keep the user filter and add no organization
    filter.
    """
    context = _storage_context.get()
    return context.organization_id if context is not None else None


def _storage_user_id_from_auth_identity(identity: object | None) -> str | None:
    """Return a stable storage-safe ID for a LangGraph auth identity."""
    if not isinstance(identity, str) or not identity:
        return None

    # LangGraph permits arbitrary strings (commonly email addresses) for
    # BaseUser.identity, while DeerFlow's user directories require a narrower
    # charset. Keep the normalization at the auth boundary so graph
    # construction and runtime middleware always select the same bucket.
    from deerflow.config.paths import make_safe_user_id

    return make_safe_user_id(identity)


def _user_id_from_auth_user(user: object | None) -> str | None:
    if isinstance(user, Mapping):
        identity = user.get("identity")
    else:
        identity = getattr(user, "identity", None)
    return _storage_user_id_from_auth_identity(identity)


def _user_id_from_langgraph_config(config: object | None) -> str | None:
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None

    user_id = _storage_user_id_from_auth_identity(configurable.get("langgraph_auth_user_id"))
    if user_id:
        return user_id
    return _user_id_from_auth_user(configurable.get("langgraph_auth_user"))


def resolve_config_user_id(config: object | None) -> str:
    """Resolve the effective user from a LangGraph/Gateway run config.

    Server-owned LangGraph authentication fields take precedence over ordinary
    ``user_id`` values because Agent Server reserves and overwrites the auth
    fields, while a standalone client may supply regular configurable/context
    values. Gateway runtime context remains the next source for DeerFlow's
    embedded run path, followed by the legacy configurable channel and the
    request ContextVar/default fallback.
    """
    # Gateway-injected storage identity is server-owned and must win over the
    # authenticated actor when a selected shared workspace is active.  The
    # in-process marker prevents an arbitrary standalone RunnableConfig from
    # selecting another workspace by naming ``storage_user_id`` directly.
    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            storage_user_id = context.get("storage_user_id")
            if storage_user_id:
                if context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is AUTHENTICATED_CONTEXT_MARKER:
                    return str(storage_user_id)
                # Once the worker consumes the in-process marker, the
                # middleware's task-local storage context remains the trusted
                # proof for this live run.  Do not infer trust from a caller's
                # actor/org fields; those are ordinary mapping values.
                active_storage = _storage_context.get()
                if active_storage is not None and active_storage.storage_user_id == str(storage_user_id):
                    return str(storage_user_id)

    langgraph_user_id = _user_id_from_langgraph_config(config)
    if langgraph_user_id:
        return langgraph_user_id

    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            context_user_id = context.get("user_id")
            if context_user_id:
                return str(context_user_id)

        configurable = config.get("configurable")
        if isinstance(configurable, Mapping):
            configurable_user_id = configurable.get("user_id")
            if configurable_user_id:
                return str(configurable_user_id)

    return get_effective_user_id()


def resolve_runtime_user_id(runtime: object | None) -> str:
    """Single source of truth for a tool/middleware's effective user_id.

    Resolution order (most authoritative first):
      1. server-owned ``runtime.context["storage_user_id"]`` from the Gateway
         workspace selector.
      2. ``runtime.server_info.user.identity`` — populated by current LangGraph
         runtimes from Agent Server's authenticated user. Unlike ordinary run
         context, this is server-owned.
      3. ``config["configurable"]["langgraph_auth_user_id"]`` — populated by
         LangGraph Server from the deployment's ``@auth.authenticate`` result.
         This supports older runtimes and code paths without ``server_info``.
      4. ``runtime.context["user_id"]`` — legacy Gateway identity when no
         workspace storage principal was selected.
      5. The workspace ContextVar, then
         ``_current_user`` — set by the auth middleware at request entry.
      6. ``DEFAULT_USER_ID`` — last-resort fallback.

    ``actor_user_id`` is carried beside this value for credential-sensitive
    consumers; use :func:`resolve_runtime_actor_user_id` there.

    The storage identity survives boundaries where the contextvar may have
    been lost (background tasks scheduled outside the request task, worker
    pools, and future cross-process drivers).
    """
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        storage_user_id = context.get("storage_user_id")
        if storage_user_id:
            return str(storage_user_id)
    active_storage = _storage_context.get()
    if active_storage is not None:
        return active_storage.storage_user_id

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()


def resolve_runtime_actor_user_id(runtime: object | None) -> str:
    """Resolve the authenticated actor for credentials and audit attribution."""
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        actor_user_id = context.get("actor_user_id")
        if actor_user_id:
            return str(actor_user_id)

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_actor_user_id()


def _user_id_from_langgraph_auth() -> str | None:
    """Return the authenticated LangGraph Server user id, if available.

    LangGraph Server reserves the ``langgraph_auth_user`` and
    ``langgraph_auth_user_id`` configurable keys and populates them from the
    deployment's ``@auth.authenticate`` result. ``get_config()`` raises when
    called outside a runnable context, which simply means this identity channel
    is unavailable.
    """
    try:
        from langgraph.config import get_config

        config = get_config()
    except RuntimeError:
        return None

    return _user_id_from_langgraph_config(config)


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument that
# defaults to ``AUTO``. The three possible values drive distinct
# behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    """Singleton marker meaning 'resolve user_id from contextvar'."""

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    """Resolve the user_id parameter passed to a repository method.

    Three-state semantics:

    - :data:`AUTO` (default): read from contextvar; raise
      :class:`RuntimeError` if no user is in context. This is the
      common case for request-scoped calls.
    - Explicit ``str``: use the provided id verbatim, overriding any
      contextvar value. Useful for tests and admin-override flows.
    - Explicit ``None``: no filter — the repository should skip the
      user_id WHERE clause entirely. Reserved for migration scripts
      and CLI tools that intentionally bypass isolation.
    """
    if isinstance(value, _AutoSentinel):
        storage_context = _storage_context.get()
        if storage_context is not None:
            return storage_context.storage_user_id
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        # Coerce to ``str`` at the boundary: ``User.id`` is typed as
        # ``UUID`` for the API surface, but the persistence layer
        # stores ``user_id`` as ``String(64)`` and aiosqlite cannot
        # bind a raw UUID object to a VARCHAR column ("type 'UUID' is
        # not supported"). Honour the documented return type here
        # rather than ripple a type change through every caller.
        return str(user.id)
    return value
