"""Credential-bearing loader/provider failures must stay out of logs and HTTP."""

import json
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.routers import mcp
from deerflow.config.extensions_config import ExtensionsConfig

SECRET = "synthetic-sensitive-bearer-value"


def test_extensions_loader_does_not_render_resolved_header_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SYNTHETIC_SECRET", SECRET)
    path = tmp_path / "extensions_config.json"
    path.write_text(json.dumps({"mcpServers": {"remote": {"type": "http", "url": "https://example.test/mcp", "headers": {"Authorization": "$AUDIT_SYNTHETIC_SECRET", "authorization": "$AUDIT_SYNTHETIC_SECRET"}}}}), encoding="utf-8")
    with pytest.raises(RuntimeError) as error:
        ExtensionsConfig.from_file(str(path))
    assert SECRET not in "".join(traceback.format_exception(error.value))
    assert "ValidationError" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint, worker, body",
    [
        (mcp.update_mcp_configuration, "_apply_mcp_config_update", mcp.McpConfigUpdateRequest(mcp_servers={})),
        (mcp.create_mcp_servers, "_apply_mcp_servers_create", mcp.McpConfigUpdateRequest(mcp_servers={})),
        (mcp.update_mcp_server, "_apply_mcp_server_config_update", mcp.McpServerConfigUpdateRequest(server_name="remote", server=mcp.McpServerConfigResponse())),
        (mcp.delete_mcp_server, "_apply_mcp_server_delete", "remote"),
        (mcp.update_mcp_server_state, "_apply_mcp_server_state_update", mcp.McpServerStateUpdateRequest(server_name="remote", enabled=False)),
    ],
)
async def test_mcp_unexpected_errors_do_not_disclose_secrets(monkeypatch, caplog, endpoint, worker, body):
    monkeypatch.setattr(mcp, "require_admin_user", AsyncMock())
    monkeypatch.setattr(mcp, "_validate_mcp_update_request", lambda *args, **kwargs: None)

    def fail(*args):
        raise RuntimeError(f"Remote request failed with credential {SECRET}")

    monkeypatch.setattr(mcp, worker, fail)
    with pytest.raises(HTTPException) as error:
        await endpoint(SimpleNamespace(), body)
    assert error.value.status_code == 500
    assert SECRET not in str(error.value.detail)
    assert SECRET not in caplog.text
