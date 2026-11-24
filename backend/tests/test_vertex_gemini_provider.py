"""Unit tests for VertexGeminiChatModel zero-retention lock and Gemini 4 xhigh thinking."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models.factory import create_chat_model
from deerflow.models.vertex_gemini_provider import VertexGeminiChatModel


def _make_model(**overrides) -> VertexGeminiChatModel:
    params = {
        "model": "gemini-4-neon",
        "vertexai": True,
        "project": "synthetic-project",
        "location": "global",
        "thinking_level": "xhigh",
        "max_output_tokens": 32768,
    }
    params.update(overrides)
    return VertexGeminiChatModel(**params)


def test_accepts_xhigh_thinking_level_and_builds_thinking_config():
    llm = _make_model(thinking_level="xhigh")
    assert llm.vertexai is True
    assert llm.cached_content is None
    assert llm.thinking_level == "xhigh"
    tc = llm._build_thinking_config()
    assert tc is not None
    assert str(tc.thinking_level).lower().endswith("xhigh")


def test_rejects_non_vertex_consumer_ai_studio():
    with pytest.raises(ValidationError, match="vertexai=True"):
        _make_model(vertexai=False)


def test_rejects_cached_content_for_zero_retention():
    with pytest.raises(ValidationError, match="cached_content"):
        _make_model(cached_content="projects/synthetic/locations/global/cachedContents/123")


def test_forbids_google_search_and_url_context_grounding_tools():
    llm = _make_model()
    for bad_tool in (
        {"google_search": {}},
        {"google_search_retrieval": {}},
        {"url_context": {}},
        {"name": "google_search"},
    ):
        with pytest.raises(ValueError, match="grounding"):
            llm.bind_tools([bad_tool])


def test_factory_creates_vertex_gemini_xhigh_and_ignores_reasoning_effort():
    cfg = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        models=[
            ModelConfig(
                name="vertex-gemini-4-neon-xhigh",
                display_name="Gemini 4 Neon (Vertex Zero-Retention)",
                use="deerflow.models.vertex_gemini_provider:VertexGeminiChatModel",
                model="gemini-4-neon",
                vertexai=True,
                project="synthetic-project",
                location="global",
                thinking_level="xhigh",
                supports_thinking=True,
                when_thinking_enabled={"thinking_level": "xhigh"},
                when_thinking_disabled={"thinking_level": "low"},
                max_output_tokens=32768,
            )
        ],
    )
    llm = create_chat_model(
        "vertex-gemini-4-neon-xhigh",
        thinking_enabled=True,
        reasoning_effort="high",
        app_config=cfg,
        attach_tracing=False,
    )
    assert isinstance(llm, VertexGeminiChatModel)
    assert llm.thinking_level == "xhigh"
    assert llm.vertexai is True
    assert llm.cached_content is None
