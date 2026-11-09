"""Codex subscription model with an automatic paid fallback (Nov 9 2026).

Primary: CodexChatModel (a Codex subscription sign-in).
When the primary fails with a usage limit, rate limit, auth failure or outage, the same turn
(messages plus bound tools) goes to `fallback_model`, built through the normal factory so the
paid-route admission caps still apply. Any other error is raised unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deerflow.models.openai_codex_provider import CodexChatModel

logger = logging.getLogger(__name__)

_FALLBACK_STATUS = {401, 402, 403, 429, 500, 502, 503, 529}
_FALLBACK_WORDS = ("usage limit", "rate limit", "quota", "credential", "unauthorized", "expired", "too many requests",
                   "stream ended", "response.completed", "connection reset", "server error", "overloaded")


def _should_fall_back(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code in _FALLBACK_STATUS
    if isinstance(exc, (httpx.TransportError, TimeoutError)):
        return True
    text = str(exc).lower()
    return any(w in text for w in _FALLBACK_WORDS)


def _to_chat_tools(tools: list[dict] | None) -> list[dict]:
    out = []
    for t in tools or []:
        if "function" in t:
            out.append(t)
        else:
            out.append({"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters") or {"type": "object", "properties": {}}}})
    return out


class CodexWithFallback(CodexChatModel):
    fallback_model: str = "openrouter-haiku-5-5-max"

    @property
    def _llm_type(self) -> str:
        return "codex-responses-with-fallback"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as exc:  # noqa: BLE001 - classified below, re-raised when not a fallback case
            if not self.fallback_model or not _should_fall_back(exc):
                raise
            logger.warning("Codex %s failed (%s: %s); falling back to %s", self.model, type(exc).__name__, str(exc)[:200], self.fallback_model)
            from deerflow.models.factory import create_chat_model

            fb = create_chat_model(name=self.fallback_model, thinking_enabled=True)
            tools = _to_chat_tools(kwargs.get("tools"))
            runnable = fb.bind_tools(tools) if tools else fb
            message = runnable.invoke(messages, stop=stop)
            message.response_metadata = {**(message.response_metadata or {}), "momo_fallback_from": self.model, "momo_fallback_reason": type(exc).__name__}
            return ChatResult(generations=[ChatGeneration(message=message)])
