"""Momo Board thread triage (Workspace Phase 4 item b3).

Classifies a new board thread's ``kind``, ``urgency`` and a one-sentence
``summary`` through the same LLM plumbing used for skill security screening
(``deerflow.models.create_chat_model`` + ``ainvoke``, a single-line JSON
response, hand-rolled parsing) -- see
``deerflow.skills.security_scanner.scan_skill_content`` for the pattern this
mirrors.

Deliberately ephemeral: ``board_threads`` has no ``urgency``/``summary``
column yet, so this module has no persistence dependency of its own. Callers
decide whether and how to store the result (e.g. patching ``kind`` onto the
thread via ``BoardRepository.patch_thread``); a follow-up migration would be
needed before ``urgency``/``summary`` could be persisted.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.persistence.board.model import BoardThreadKind
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.llm_text import extract_response_text

logger = logging.getLogger(__name__)

VALID_KINDS: frozenset[str] = frozenset(k.value for k in BoardThreadKind)
VALID_URGENCIES: tuple[str, ...] = ("low", "normal", "high", "urgent")
_DEFAULT_URGENCY = "normal"
_FALLBACK_SUMMARY_LEN = 140


@dataclass(slots=True)
class BoardThreadTriage:
    kind: str
    urgency: str
    summary: str
    # True when the model call failed or produced an unparseable response
    # and this is the safe-default classification, not a real one. Callers
    # must not persist a fallback result as if Momo actually looked at the
    # thread (e.g. it must not read as a real "normal" urgency).
    fallback: bool = False


def _extract_json_object(raw: str) -> dict | None:
    raw = raw.strip()

    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        c = raw[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _fallback_summary(content: str) -> str:
    stripped = " ".join(content.split())
    if len(stripped) <= _FALLBACK_SUMMARY_LEN:
        return stripped
    return stripped[: _FALLBACK_SUMMARY_LEN - 1].rstrip() + "…"


async def triage_board_thread(
    content: str,
    *,
    subject: str = "",
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    attach_tracing: bool = True,
) -> BoardThreadTriage:
    """Classify a new board thread's kind, urgency and summary.

    On any model failure or unparseable response, falls back to a safe
    default (``ticket`` / ``normal`` / a truncated echo of the content) rather
    than raising -- triage is an aid, not a gate, so a thread must never be
    lost because classification failed.
    """
    rubric = (
        "You are Momo, an assistant that triages incoming messages on a client's board. "
        "Classify the message into a kind, an urgency and a one-sentence summary.\n"
        f"kind must be one of: {', '.join(sorted(VALID_KINDS))}.\n"
        f"urgency must be one of: {', '.join(VALID_URGENCIES)} (urgent = needs a response within hours, e.g. a site down or broken form).\n"
        "summary is one plain sentence describing what the sender wants, no preamble.\n"
        "Respond with ONLY a single JSON object on one line, no code fences, no commentary:\n"
        '{"kind":"post|ticket|concern|dm","urgency":"low|normal|high|urgent","summary":"..."}'
    )
    prompt = f"Subject: {subject or '(none)'}\n\nMessage:\n-----\n{content}\n-----"

    try:
        config = app_config or get_app_config()
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config, attach_tracing=attach_tracing)
        invoke_config: dict[str, Any] = {"run_name": "board_triage"}
        if attach_tracing:
            inject_langfuse_metadata(
                invoke_config,
                thread_id=None,
                user_id=get_effective_user_id(),
                assistant_id="board_triage",
                model_name=model_name,
                environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
            )
        response = await model.ainvoke(
            [
                {"role": "system", "content": rubric},
                {"role": "user", "content": prompt},
            ],
            config=invoke_config,
        )
        raw = extract_response_text(getattr(response, "content", ""))
        parsed = _extract_json_object(raw)
        if parsed:
            kind = str(parsed.get("kind", "")).lower()
            urgency = str(parsed.get("urgency", "")).lower()
            summary = str(parsed.get("summary") or "").strip()
            if kind in VALID_KINDS and urgency in VALID_URGENCIES and summary:
                return BoardThreadTriage(kind=kind, urgency=urgency, summary=summary)
        logger.warning("Board triage produced unparseable output: %s", raw[:200])
    except Exception:
        logger.warning("Board triage model call failed; falling back to a default classification", exc_info=True)

    return BoardThreadTriage(kind=BoardThreadKind.TICKET.value, urgency=_DEFAULT_URGENCY, summary=_fallback_summary(content), fallback=True)
