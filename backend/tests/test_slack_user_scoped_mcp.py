"""The documented per-user Slack MCP entry only ever calls Slack as the signed-in person."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.user_scoped_auth import build_user_scoped_auth_interceptor

EXAMPLE = Path(__file__).resolve().parents[2] / "extensions_config.example.json"


def _slack_config(monkeypatch) -> ExtensionsConfig:
    monkeypatch.setenv("SLACK_MCP_DISCOVERY_AUTH", "Bearer discovery-user-token")
    monkeypatch.setenv("SLACK_USER_AUTH_ALICE", "Bearer alice-user-token")
    entry = json.loads(EXAMPLE.read_text(encoding="utf-8"))["mcpServers"]["slack-user"]
    entry = {**entry, "enabled": True, "user_auth": {**entry["user_auth"], "users": {"alice": "$SLACK_USER_AUTH_ALICE"}}}
    return ExtensionsConfig(mcp_servers={"slack-user": McpServerConfig(**ExtensionsConfig.resolve_env_variables(entry))}, skills={})


def _call(interceptor, user_id: str):
    request = MCPToolCallRequest(
        name="slack_search_messages",
        args={"query": "launch"},
        server_name="slack-user",
        headers={"Authorization": "Bearer discovery-user-token"},
        runtime=SimpleNamespace(server_info=None, context={"user_id": user_id}),
    )

    async def handler(req):
        return req

    return asyncio.run(interceptor(request, handler))


def test_example_entry_is_user_scoped_and_fail_closed():
    entry = json.loads(EXAMPLE.read_text(encoding="utf-8"))["mcpServers"]["slack-user"]
    assert entry["enabled"] is False and entry["type"] == "http"
    assert entry["user_auth"] == {"enabled": True, "header": "Authorization", "users": {}, "on_missing": "deny"}
    # Never a workspace bot token in the shipped config.
    assert "xoxb" not in json.dumps(entry)


def test_each_person_calls_slack_with_their_own_token(monkeypatch):
    interceptor = build_user_scoped_auth_interceptor(_slack_config(monkeypatch))
    assert _call(interceptor, "alice").headers["Authorization"] == "Bearer alice-user-token"


def test_unmapped_person_is_denied_instead_of_borrowing_a_token(monkeypatch):
    interceptor = build_user_scoped_auth_interceptor(_slack_config(monkeypatch))
    with pytest.raises(ToolException) as denied:
        _call(interceptor, "bob")
    assert "alice-user-token" not in str(denied.value) and "discovery-user-token" not in str(denied.value)
