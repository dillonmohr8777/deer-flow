"""Fleet-agent tools for the Momentum staff Team Board (``deerflow.persistence.team_board``).

Two tools, gated behind the ``team`` tool group in an agent's ``config.yaml``:
read a channel's recent messages, and post plain text to one. Both go through
``TeamBoardRepository`` exactly like the human ``/api/team`` routes, so they
inherit the same organization scoping: a channel belonging to another
organization is indistinguishable from a missing one (see
``resolve_organization_id()`` and ``TeamBoardRepository.get_channel``).
Channels are never created here — an owner or admin creates ``#fleet`` once
from the Team Board UI — so both tools fail closed until it exists.

``#fleet`` (and every channel these tools can reach) carries repo and public
information only, never client data, credentials, or anything else private:
some fleet agents run on a model lane that must not see private data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from langchain.tools import tool
from pydantic import Field

from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

_MAX_BODY_CHARS = 2000
_MAX_READ_LIMIT = 200
_DEFAULT_READ_LIMIT = 50


def _error(message: str) -> dict:
    return {"error": message}


def _normalize_slug(channel: str) -> str:
    return (channel or "").strip().lstrip("#").strip().lower()


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
    another organization never matches here.
    """
    slug = _normalize_slug(channel)
    if not slug:
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


async def _team_read_messages_impl(channel: str, since: str | None = None, limit: int = _DEFAULT_READ_LIMIT) -> dict:
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


async def _team_post_message_impl(channel: str, body: str, runtime: Runtime | None = None) -> dict:
    text = (body or "").strip()
    if not text:
        return _error("Message is empty.")
    if len(text) > _MAX_BODY_CHARS:
        return _error(f"Message exceeds {_MAX_BODY_CHARS} characters ({len(text)}).")
    repo = _get_repo()
    if repo is None:
        return _error("Team board storage is unavailable.")
    row = await _find_channel(repo, channel)
    if row is None:
        return _no_such_channel(channel)
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    agent_name = context.get("agent_name") or "agent"
    author_user_id = resolve_runtime_user_id(runtime)
    posted = await repo.add_message(row["id"], author_user_id=author_user_id, body=f"[{agent_name}] {text}")
    if posted is None:
        return _no_such_channel(channel)
    return {"channel": row["slug"], "author": posted["author_user_id"], "body": posted["body"], "created_at": posted["created_at"]}


@tool(parse_docstring=True)
async def team_read_messages(
    channel: str,
    since: str | None = None,
    limit: Annotated[int, Field(ge=1, le=_MAX_READ_LIMIT)] = _DEFAULT_READ_LIMIT,
) -> dict:
    """Read recent messages from a Momentum staff Team Board channel, such as #fleet.

    Scoped to this run's Momentum organization: a channel belonging to
    another organization is indistinguishable from a missing one. Channels
    are not created here — an owner or admin creates #fleet once from the
    Team Board UI. #fleet (and every channel this tool can reach) carries
    repo and public information only, never client data, credentials, or
    anything else private, because some fleet agents run on a model lane
    that must not see private data.

    Args:
        channel: Channel slug, with or without a leading '#' (e.g. "fleet").
        since: Optional ISO-8601 timestamp. Returns only messages posted strictly after it, oldest first. Omit for the newest page (the latest `limit` messages, oldest first).
        limit: Maximum messages to return, 1-200 (default 50).

    Returns:
        {"channel": "fleet", "messages": [{"author": ..., "body": ..., "created_at": ...}, ...]}, or {"error": ...}.
    """
    return await _team_read_messages_impl(channel, since=since, limit=limit)


@tool(parse_docstring=True)
async def team_post_message(
    channel: str,
    body: str,
    runtime: Runtime,
) -> dict:
    """Post a plain-text message to a Momentum staff Team Board channel, such as #fleet.

    Signs the message with this agent's name (e.g. "[fleet-builder] ...") so
    every post shows which agent wrote it. Plain text only, up to 2,000
    characters — no attachments. Scoped to this run's Momentum organization:
    a channel belonging to another organization is indistinguishable from a
    missing one. Channels are not created here — an owner or admin creates
    #fleet once from the Team Board UI, and posting fails until then. #fleet
    (and every channel this tool can reach) carries repo and public
    information only, never client data, credentials, or anything else
    private, because some fleet agents run on a model lane that must not see
    private data.

    Args:
        channel: Channel slug, with or without a leading '#' (e.g. "fleet").
        body: Plain text to post, 1-2,000 characters. No attachments.
        runtime: Injected tool runtime, used to sign the post with this agent's name and resolve its author.

    Returns:
        {"channel": "fleet", "author": ..., "body": ..., "created_at": ...} on success, or {"error": ...}.
    """
    return await _team_post_message_impl(channel, body, runtime=runtime)
