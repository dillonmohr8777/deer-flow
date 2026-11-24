"""Zero-retention GCP Vertex AI Gemini chat model provider.

Wraps ``langchain_google_genai.ChatGoogleGenerativeAI`` with two guarantees
required for private client workspaces (e.g. healthcare / senior placement):

1. **Zero-retention Vertex lock**: ``vertexai`` must stay ``True`` (never
   consumer AI Studio), explicit ``cached_content`` is forbidden, and external
   Google Search / URL-context grounding tools cannot be bound.
2. **Gemini 4 ``xhigh`` thinking support**: ``langchain-google-genai 4.2.x``
   caps its Pydantic ``thinking_level`` literal at ``high`` even though Gemini 4
   models (``gemini-4-neon``, ``gemini-4-hydrogen``) accept ``xhigh``. This
   subclass widens ``thinking_level`` to include ``"xhigh"`` and forwards it
   cleanly into ``google.genai.types.ThinkingConfig``.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any, Literal

from google.genai import types as genai_types
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import Field, field_validator

ThinkingLevelValue = Literal["minimal", "low", "medium", "high", "xhigh"]

_BLOCKED_GROUNDING_KEYS = frozenset(
    {
        "google_search",
        "google_search_retrieval",
        "dynamic_retrieval_config",
        "url_context",
        "google_maps",
    }
)


def _is_grounding_tool(tool: Any) -> bool:
    if isinstance(tool, dict):
        if _BLOCKED_GROUNDING_KEYS.intersection(tool.keys()):
            return True
        name = str(tool.get("name") or "").strip().lower()
        if name in _BLOCKED_GROUNDING_KEYS:
            return True
    name_attr = getattr(tool, "name", None)
    if isinstance(name_attr, str) and name_attr.strip().lower() in _BLOCKED_GROUNDING_KEYS:
        return True
    for attr in _BLOCKED_GROUNDING_KEYS:
        if getattr(tool, attr, None) is not None:
            return True
    return False


class VertexGeminiChatModel(ChatGoogleGenerativeAI):
    """Zero-retention Vertex AI Gemini model with Gemini 4 ``xhigh`` thinking."""

    vertexai: bool = Field(default=True)
    cached_content: str | None = Field(default=None)
    thinking_level: ThinkingLevelValue | None = Field(default=None)

    def __init__(self, **kwargs: Any) -> None:
        # DeerFlow's model factory may forward reasoning_effort when a profile or
        # run sets one; ChatGoogleGenerativeAI uses thinking_level instead.
        kwargs.pop("reasoning_effort", None)
        kwargs.setdefault("vertexai", True)
        super().__init__(**kwargs)

    @field_validator("vertexai")
    @classmethod
    def _require_vertexai(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("VertexGeminiChatModel requires vertexai=True (consumer AI Studio is forbidden)")
        return True

    @field_validator("cached_content")
    @classmethod
    def _forbid_cached_content(cls, value: str | None) -> str | None:
        if value is not None:
            raise ValueError("VertexGeminiChatModel forbids cached_content to preserve zero-retention posture")
        return None

    def _build_thinking_config(self, **kwargs: Any) -> genai_types.ThinkingConfig | None:
        thinking_level = kwargs.get("thinking_level", self.thinking_level)
        if thinking_level == "xhigh":
            include_thoughts = kwargs.get("include_thoughts", self.include_thoughts)
            cfg: dict[str, Any] = {"thinking_level": "xhigh"}
            if include_thoughts is not None:
                cfg["include_thoughts"] = include_thoughts
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r"xhigh is not a valid ThinkingLevel")
                return genai_types.ThinkingConfig(**cfg)
        return super()._build_thinking_config(**kwargs)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_config: Any = None,
        **kwargs: Any,
    ) -> Any:
        for tool in tools:
            if _is_grounding_tool(tool):
                raise ValueError("VertexGeminiChatModel forbids Google Search / URL grounding tools on zero-retention routes")
        return super().bind_tools(tools, tool_config=tool_config, **kwargs)
