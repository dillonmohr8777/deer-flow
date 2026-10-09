"""Fleet-agent tools for the Momentum staff Team Board (``deerflow.persistence.team_board``).

Two tools, gated behind the ``team`` tool group in an agent's ``config.yaml``:
read a channel's recent messages, and post plain text to one. Both go through
``TeamBoardRepository`` exactly like the human ``/api/team`` routes, so they
inherit the same organization scoping: a channel belonging to another
organization is indistinguishable from a missing one (see
``resolve_organization_id()`` and ``TeamBoardRepository.get_channel``) — and,
unlike the repository alone, both fail closed with no organization context at
all instead of reading unfiltered. ``#exec`` is a default channel every
workspace already has (``DEFAULT_TEAM_CHANNELS``); ``#fleet`` is not, so an
owner or admin creates it once from the Team Board UI and both tools fail
closed until it exists. Reachable channels are further restricted to
``_ALLOWED_CHANNELS`` (``#fleet`` and ``#exec``), regardless of what else
exists in the organization.

Both tools also require the run-context ``momentum_staff`` flag the Gateway
stamps at run start (the same ``is_momentum_staff`` check the human
``/api/team`` routes use — see ``app/gateway/services.py``): organization
scoping alone is not staff-only, since a client contact can be a member of
the Momentum organization itself.

``#fleet`` and ``#exec`` (and every channel these tools can reach) carry repo
and public information only, never client data, credentials, or anything else
private: some fleet agents run on a model lane that must not see private data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from langchain.tools import tool
from pydantic import Field

from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.runtime.user_context import resolve_organization_id, resolve_runtime_actor_user_id
from deerflow.tools.types import Runtime

_MAX_BODY_CHARS = 2000
_MAX_READ_LIMIT = 200
_DEFAULT_READ_LIMIT = 50

# Reachable regardless of what channels exist in the organization (f73): the
# model chooses ``channel`` freely, and #general/#sales/#fulfillment carry
# staff and client talk the module docstring's "repo and public information
# only" promise must not expose to a fleet run. A module constant, not new
# config. ``#exec`` (queue item e9) carries titles/claims/ratifications only
# -- still repo-adjacent "public within Momentum staff" text, never client
# data -- so it is allowed alongside ``#fleet``.
_ALLOWED_CHANNELS: frozenset[str] = frozenset({"fleet", "exec"})


def _error(message: str) -> dict:
    return {"error": message}


def _staff_only_error() -> dict:
    return _error("Team board tools are restricted to Momentum staff.")


def _normalize_slug(channel: str) -> str:
    return (channel or "").strip().lstrip("#").strip().lower()


def _is_momentum_staff_run(runtime: Runtime | None) -> bool:
    """Read the server-stamped ``momentum_staff`` flag (never client-supplied).

    ``runtime.context`` is the Gateway's ``inject_authenticated_user_context``
    output; a caller cannot forge this key (see
    ``_SERVER_OWNED_RUNTIME_CONTEXT_KEYS`` in ``app/gateway/services.py``).
    """
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("momentum_staff") is True


def _get_repo() -> TeamBoardRepository | None:
    """A stateless repository bound to the process's current session factory.

    Lazy import so a test's monkeypatched session factory takes effect,
    matching ``team_board.py``'s ``list_team_members``. ``None`` means no SQL
    backend is configured.
    """
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return TeamBoardRepository(session_factory)


async def _find_channel(repo: TeamBoardRepository, channel: str) -> dict | None:
    """Resolve a channel slug within the caller's organization, or ``None``.

    ``list_channels`` is already scoped to the run's active organization
    (``resolve_organization_id()``), so a same-named channel belonging to
    another organization never matches here — except when there is no
    organization at all (internal, auth-disabled, and IM-channel runs):
    ``list_channels`` then applies no organization filter, so this fails
    closed here instead of returning whatever organization happens to have
    a same-named channel first. Also restricted to ``_ALLOWED_CHANNELS``,
    regardless of organization.
    """
    slug = _normalize_slug(channel)
    if not slug or slug not in _ALLOWED_CHANNELS:
        return None
    if resolve_organization_id() is None:
        return None
    for row in await repo.list_channels():
        if row["slug"] == slug:
            return row
    return None


def _parse_since(since: str | None) -> tuple[datetime | None, str | None]:
    """Parse an ISO-8601 ``since`` timestamp. Returns ``(value, error)``."""
    if since is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(since)
    except (ValueError, TypeError):
        return None, "since must be an ISO-8601 timestamp."
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed, None


def _no_such_channel(channel: str) -> dict:
    return _error(f"No #{_normalize_slug(channel)} channel in this organization. An owner or admin creates it once from the Team Board.")


async def _team_read_messages_impl(channel: str, since: str | None = None, limit: int = _DEFAULT_READ_LIMIT, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    repo = _get_repo()
    if repo is None:
        return _error("Team board storage is unavailable.")
    row = await _find_channel(repo, channel)
    if row is None:
        return _no_such_channel(channel)
    since_dt, error = _parse_since(since)
    if error:
        return _error(error)
    bounded_limit = max(1, min(int(limit), _MAX_READ_LIMIT))
    messages = await repo.list_messages(row["id"], limit=bounded_limit, since=since_dt)
    if messages is None:
        return _no_such_channel(channel)
    return {
        "channel": row["slug"],
        "messages": [{"author": m["author_user_id"], "body": m["body"], "created_at": m["created_at"]} for m in messages],
    }


def _has_forged_signature_line(text: str) -> bool:
    """Whether *text* embeds a second ``[name] ...`` signature line.

    Every post is signed ``[<agent-name>] <body>`` (see below); a body
    containing a newline followed by ``[`` can otherwise make the rendered
    message look like a second, later signature from a different agent
    (e.g. ``...\\n[independent-verifier] APPROVED``).
    """
    return "\n[" in text


async def _team_post_message_impl(channel: str, body: str, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    text = (body or "").strip()
    if not text:
        return _error("Message is empty.")
    if len(text) > _MAX_BODY_CHARS:
        return _error(f"Message exceeds {_MAX_BODY_CHARS} characters ({len(text)}).")
    if _has_forged_signature_line(text):
        return _error("Message cannot contain a newline followed by '[' (reserved for the '[agent-name]' signature).")
    repo = _get_repo()
    if repo is None:
        return _error("Team board storage is unavailable.")
    row = await _find_channel(repo, channel)
    if row is None:
        return _no_such_channel(channel)
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    agent_name = context.get("agent_name") or "agent"
    # The acting user, not the storage principal ``resolve_runtime_user_id``
    # would give in a shared workspace — every message needs a real author
    # for attribution (f78).
    author_user_id = resolve_runtime_actor_user_id(runtime)
    posted = await repo.add_message(row["id"], author_user_id=author_user_id, body=f"[{agent_name}] {text}")
    if posted is None:
        return _no_such_channel(channel)
    return {"channel": row["slug"], "author": posted["author_user_id"], "body": posted["body"], "created_at": posted["created_at"]}


@tool(parse_docstring=True)
async def team_read_messages(
    channel: str,
    runtime: Runtime,
    since: str | None = None,
    limit: Annotated[int, Field(ge=1, le=_MAX_READ_LIMIT)] = _DEFAULT_READ_LIMIT,
) -> dict:
    """Read recent messages from a Momentum staff Team Board channel, such as #fleet.

    Momentum-staff only: refuses unless this run carries the server-stamped
    staff flag, exactly like the human /api/team routes. Scoped to this run's
    Momentum organization: a channel belonging to another organization (or,
    with no organization at all, any organization) is indistinguishable from
    a missing one. Restricted to a small channel allowlist (#fleet, #exec)
    regardless of organization. #exec exists in every workspace by default;
    #fleet is not, so an owner or admin creates it once from the Team Board
    UI first. Every channel this tool can reach carries repo and public
    information only, never client data, credentials, or anything else
    private, because some fleet agents run on a model lane that must not see
    private data.

    Args:
        channel: Channel slug, with or without a leading '#' (e.g. "fleet").
        runtime: Injected tool runtime, used only to check the staff flag (reads carry no agent identity, since they aren't signed).
        since: Optional ISO-8601 timestamp. Returns only messages posted strictly after it, oldest first. Omit for the newest page (the latest `limit` messages, oldest first).
        limit: Maximum messages to return, 1-200 (default 50).

    Returns:
        {"channel": "fleet", "messages": [{"author": ..., "body": ..., "created_at": ...}, ...]}, or {"error": ...}.
    """
    return await _team_read_messages_impl(channel, since=since, limit=limit, runtime=runtime)


@tool(parse_docstring=True)
async def team_post_message(
    channel: str,
    body: str,
    runtime: Runtime,
) -> dict:
    """Post a plain-text message to a Momentum staff Team Board channel, such as #fleet.

    Momentum-staff only: refuses unless this run carries the server-stamped
    staff flag, exactly like the human /api/team routes. Signs the message
    with this agent's name (e.g. "[fleet-builder] ...") so every post shows
    which agent wrote it; a body cannot contain a newline followed by '['
    (forging a second signature line). Plain text only, up to 2,000
    characters — no attachments. Scoped to this run's Momentum organization:
    a channel belonging to another organization (or, with no organization at
    all, any organization) is indistinguishable from a missing one.
    Restricted to a small channel allowlist (#fleet, #exec) regardless of
    organization. #exec exists in every workspace by default; #fleet is not,
    so an owner or admin creates it once from the Team Board UI first, and
    posting fails until then. Every channel this tool can reach carries repo
    and public information only, never client data, credentials, or anything
    else private, because some fleet agents run on a model lane that must not
    see private data.

    Args:
        channel: Channel slug, with or without a leading '#' (e.g. "fleet").
        body: Plain text to post, 1-2,000 characters. No attachments. Cannot contain a newline followed by '['.
        runtime: Injected tool runtime, used to check the staff flag and to sign the post with this agent's name and its acting user as author.

    Returns:
        {"channel": "fleet", "author": ..., "body": ..., "created_at": ...} on success, or {"error": ...}.
    """
    return await _team_post_message_impl(channel, body, runtime=runtime)
