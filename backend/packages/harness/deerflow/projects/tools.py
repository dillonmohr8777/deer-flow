"""Project shelf tools: bounded live reads through the pinned project identity.

Three read-only tools (Phase-2 spec §7.3, plus the evidence-check pilot; the
shelf is user-curated, there is no agent-initiated shelf write). All three
take ``project_id`` from the run's admission-pinned context
(``PROJECT_CONTEXT_KEY``) and ``user_id`` from :func:`resolve_runtime_user_id`,
then query **live** shelf rows: the pinned snapshot fixes *which* project,
never *what* the shelf currently holds. A missing pin or a missing session
factory is a tool error, never an empty success; a document trashed after
this run's index was rendered fails with a "no longer on the shelf" error
rather than serving stale content (§11).

Registration is conditional on the pinned key (§10.11), see
``agents/lead_agent/agent.py``; subagents never receive these tools. Every
file read and conversion is offloaded via
:func:`deerflow.utils.file_io.run_file_io`.

``verify_quote`` is the evidence-check pilot tool: it confirms an exact quote
appears in one shelf document's text (after folding whitespace runs and
curly/smart quote characters), so the lead agent can cite project documents
with checked quotes instead of guessed ones. A matched quote proves the text
exists in the document; it does not prove the quote supports whatever claim
it is cited for, so the check is necessary, not sufficient.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any

from langchain.tools import tool

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.config.paths import Paths, get_paths
from deerflow.projects.context import pinned_project_snapshot
from deerflow.projects.documents import auto_convert_documents_enabled, document_char_count, read_document_text_window, read_text_serving_path
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

_LIST_DEFAULT_LIMIT = 50
_LIST_MAX_LIMIT = 200
_READ_DEFAULT_LIMIT = 8000
_READ_MAX_LIMIT = 20000

# verify_quote bounds: short enough to be a checkable "exact quote" (the lead
# agent's citation instruction caps it at 40 words), long enough that a match
# is meaningful evidence rather than a common phrase.
_QUOTE_MIN_CHARS = 20
_QUOTE_MAX_CHARS = 600
# Characters of normalized-text context kept on each side of a match, for
# "about 200 characters of surrounding context" total.
_QUOTE_CONTEXT_RADIUS = 100

_BINARY_DECLINE_MESSAGE = "This document is binary and cannot be read as text. To let the agent process it, attach it to a thread (attach-to-thread) instead."
_CONVERSION_DISABLED_MESSAGE = "This document is a convertible office/PDF file, but automatic document conversion is disabled (uploads.auto_convert_documents). Enable conversion, or attach the file to a thread (attach-to-thread) instead."
_NOT_ON_SHELF_MESSAGE = "This document is no longer on the shelf (it was trashed or removed after this run started). Call list_project_documents for the current shelf."
_CONTENT_MISSING_MESSAGE = "This document's content is missing from storage (content_missing); only its shelf row remains. Move it to trash from the project page."
_NO_PROJECT_CONTEXT_MESSAGE = "No project is pinned for this run; project document tools are only available in project member threads."
_NO_STORE_MESSAGE = "Project document store is unavailable."

# Curly/smart quote and prime characters folded to their plain ASCII form
# before matching, so a quote copied out of a word processor still matches
# straight-quoted source text (and vice versa).
_QUOTE_CHAR_MAP = {
    "‘": "'",  # left single quotation mark
    "’": "'",  # right single quotation mark (also used as an apostrophe)
    "‚": "'",  # single low-9 quotation mark
    "‛": "'",  # single high-reversed-9 quotation mark
    "′": "'",  # prime
    "“": '"',  # left double quotation mark
    "”": '"',  # right double quotation mark
    "„": '"',  # double low-9 quotation mark
    "‟": '"',  # double high-reversed-9 quotation mark
    "″": '"',  # double prime
}
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_quote_text(text: str) -> str:
    """Fold smart quotes to straight ones and whitespace runs to one space.

    Both the document text and the search quote pass through this before
    matching, so line wrapping or word-processor punctuation that differs
    between the source document and a pasted quote does not defeat an
    otherwise exact match. Offsets returned by ``verify_quote`` are positions
    in this normalized text, not the raw file.
    """
    folded = text
    for smart, plain in _QUOTE_CHAR_MAP.items():
        folded = folded.replace(smart, plain)
    return _WHITESPACE_RE.sub(" ", folded)


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _resolve_pin_and_repo(runtime: Runtime) -> tuple[str, str, Any] | str:
    """Resolve ``(project_id, user_id, repository)`` or a JSON error string.

    Fail closed (§7.3): no pinned project context or no session factory is a
    tool error with no data, never an empty success.
    """
    snapshot = pinned_project_snapshot(runtime)
    project_id = str(snapshot.get("project_id") or "") if snapshot is not None else ""
    if not project_id:
        return _error(_NO_PROJECT_CONTEXT_MESSAGE)
    from deerflow.persistence import get_session_factory
    from deerflow.persistence.projects import ProjectDocumentRepository

    session_factory = get_session_factory()
    if session_factory is None:
        return _error(_NO_STORE_MESSAGE)
    user_id = resolve_runtime_user_id(runtime)
    return project_id, user_id, ProjectDocumentRepository(session_factory)


def _resolve_auto_convert() -> bool:
    """Worker-thread config read: the app config may cold-load from disk."""
    try:
        from deerflow.config.app_config import get_app_config

        return auto_convert_documents_enabled(get_app_config())
    except Exception:
        return False


def _clamp(value: int, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(parsed, upper))


def _shelf_entry_json(row: dict) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": neutralize_untrusted_tags(str(row.get("name") or "")),
        "size_bytes": int(row.get("size_bytes") or 0),
        "updated_at": str(row.get("updated_at") or ""),
    }


async def _list_project_documents_impl(runtime: Runtime, *, offset: int, limit: int) -> str:
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved
    limit = _clamp(limit, default=_LIST_DEFAULT_LIMIT, lower=1, upper=_LIST_MAX_LIMIT)
    offset = max(_clamp(offset, default=0, lower=0, upper=1 << 62), 0)
    rows = await repo.list_active(project_id, limit=limit, offset=offset, user_id=user_id)
    total = await repo.count_active(project_id, user_id=user_id)
    next_offset: int | None = offset + len(rows) if offset + len(rows) < total else None
    return json.dumps(
        {
            "total": total,
            "offset": offset,
            "next_offset": next_offset,
            "documents": [_shelf_entry_json(row) for row in rows],
        },
        ensure_ascii=False,
    )


async def _read_project_document_impl(runtime: Runtime, *, document_id: str, offset: int, limit: int, paths: Paths | None = None) -> str:
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved
    row = await repo.get(document_id, user_id=user_id)
    # Fail closed on every mismatch: trashed/purged after the index rendered,
    # foreign, or belonging to a different project than the pinned one — one
    # stale-entry error, never cross-project reads, never stale content (§11).
    if row is None or row.get("project_id") != project_id:
        return _error(_NOT_ON_SHELF_MESSAGE)
    paths = paths or get_paths()
    auto_convert = await run_file_io(_resolve_auto_convert)
    serving_path, reason = await read_text_serving_path(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if serving_path is None:
        if reason == "content_missing":
            return _error(_CONTENT_MISSING_MESSAGE)
        if reason == "conversion_disabled":
            return _error(_CONVERSION_DISABLED_MESSAGE)
        return _error(_BINARY_DECLINE_MESSAGE)
    offset = _clamp(offset, default=0, lower=0, upper=1 << 62)
    limit = _clamp(limit, default=_READ_DEFAULT_LIMIT, lower=1, upper=_READ_MAX_LIMIT)
    # The character count is content-identity cached (immutable rows, §6.2);
    # the windowed read decodes only what the page needs — and past-end pages
    # read nothing at all.
    total_chars = await document_char_count(document_id=row["id"], sha256=row["sha256"], path=serving_path)
    content = await read_document_text_window(serving_path, offset=offset, limit=limit) if offset < total_chars else ""
    return json.dumps(
        {
            "name": neutralize_untrusted_tags(str(row.get("name") or "")),
            "total_chars": total_chars,
            "offset": offset,
            "returned_chars": len(content),
            "truncated": offset + len(content) < total_chars,
            "content": content,
        },
        ensure_ascii=False,
    )


async def _verify_quote_impl(runtime: Runtime, *, document_id: str, quote: str, paths: Paths | None = None) -> str:
    quote_len = len(quote)
    if not (_QUOTE_MIN_CHARS <= quote_len <= _QUOTE_MAX_CHARS):
        return _error(f"quote must be {_QUOTE_MIN_CHARS} to {_QUOTE_MAX_CHARS} characters (got {quote_len}).")
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved
    row = await repo.get(document_id, user_id=user_id)
    # Same fail-closed identity as read_project_document (§11): a foreign
    # owner, a foreign organization, a foreign project, or a trashed/missing
    # row all collapse to the one "not on the shelf" error, never a
    # distinguishable access-denied response.
    if row is None or row.get("project_id") != project_id:
        return _error(_NOT_ON_SHELF_MESSAGE)
    paths = paths or get_paths()
    auto_convert = await run_file_io(_resolve_auto_convert)
    serving_path, reason = await read_text_serving_path(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if serving_path is None:
        if reason == "content_missing":
            return _error(_CONTENT_MISSING_MESSAGE)
        if reason == "conversion_disabled":
            return _error(_CONVERSION_DISABLED_MESSAGE)
        return _error(_BINARY_DECLINE_MESSAGE)
    # ponytail: reads the whole document into memory to search it; fine at
    # shelf-document scale, switch to a streamed/chunked search if documents
    # routinely grow past a few MB.
    total_chars = await document_char_count(document_id=row["id"], sha256=row["sha256"], path=serving_path)
    full_text = await read_document_text_window(serving_path, offset=0, limit=total_chars)
    normalized_text = _normalize_quote_text(full_text)
    normalized_quote = _normalize_quote_text(quote)
    start = normalized_text.find(normalized_quote)
    if start == -1:
        return json.dumps({"found": False}, ensure_ascii=False)
    end = start + len(normalized_quote)
    context_start = max(start - _QUOTE_CONTEXT_RADIUS, 0)
    context_end = min(end + _QUOTE_CONTEXT_RADIUS, len(normalized_text))
    return json.dumps(
        {
            "found": True,
            "start_offset": start,
            "end_offset": end,
            "context": normalized_text[context_start:context_end],
        },
        ensure_ascii=False,
    )


@tool
async def list_project_documents(
    runtime: Runtime,
    offset: Annotated[int, "Number of shelf entries to skip for pagination (default 0). Use next_offset from a previous call to walk the shelf."] = 0,
    limit: Annotated[int, "Maximum entries to return (default 50, max 200)."] = _LIST_DEFAULT_LIMIT,
) -> str:
    """List documents on the current project's shelf (metadata only, no content).

    Returns JSON: {"total", "offset", "next_offset", "documents": [{"id",
    "name", "size_bytes", "updated_at"}, ...]} in the shelf's own order
    (recently updated first). Use this when the <documents> index says the
    shelf has more entries than it shows, or the user asks what documents the
    project holds. Each entry's stable "id" is what read_project_document
    takes. Live data: reflects the shelf as of this call.
    """
    return await _list_project_documents_impl(runtime, offset=offset, limit=limit)


@tool
async def read_project_document(
    runtime: Runtime,
    document_id: Annotated[str, "Stable document ID from the <documents> index or list_project_documents."],
    offset: Annotated[int, "Character offset into the document's text (default 0)."] = 0,
    limit: Annotated[int, "Maximum characters to return (default 8000, max 20000)."] = _READ_DEFAULT_LIMIT,
) -> str:
    """Read a bounded text slice of one project shelf document.

    Returns JSON: {"name", "total_chars", "offset", "returned_chars",
    "truncated", "content"}. Long documents are served in slices: advance
    "offset" by the returned character count while "truncated" is true.
    Office/PDF documents are served as converted markdown when conversion is
    enabled. Binary documents cannot be read — attach them to a thread
    instead. A document trashed after this run started reports that it is no
    longer on the shelf.
    """
    return await _read_project_document_impl(runtime, document_id=document_id, offset=offset, limit=limit)


@tool
async def verify_quote(
    runtime: Runtime,
    document_id: Annotated[str, "Stable document ID from the <documents> index or list_project_documents."],
    quote: Annotated[str, f"The exact quote to check, {_QUOTE_MIN_CHARS} to {_QUOTE_MAX_CHARS} characters."],
) -> str:
    """Check whether an exact quote appears in one project shelf document.

    Returns JSON: {"found": true, "start_offset", "end_offset", "context"} when
    the quote is found, or {"found": false} when it is not. Matching folds
    whitespace runs to a single space and curly/smart quote characters to
    straight ones on both sides before comparing, so a pasted quote does not
    fail only over line wrapping or word-processor punctuation; offsets and
    context are positions in that normalized text, not the raw file. A
    document this run cannot read (wrong project, wrong owner, wrong
    organization, trashed, or never on this shelf) reports the same "no
    longer on the shelf" error as a missing document ID.

    A "found" result confirms the quote's text exists in the document. It
    does NOT confirm the quote supports whatever claim it is cited for, so
    still judge relevance yourself; and a "not found" result (or no document
    that supports the claim at all) means say plainly that it could not be
    confirmed rather than presenting the claim as sourced.
    """
    return await _verify_quote_impl(runtime, document_id=document_id, quote=quote)


def get_project_document_tools() -> list:
    """The three shelf tools the lead agent gains in project runs (§7.3)."""
    return [list_project_documents, read_project_document, verify_quote]
