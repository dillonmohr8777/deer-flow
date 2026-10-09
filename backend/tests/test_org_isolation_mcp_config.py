"""M3 gap: MCP server configuration stays deployment-global across organizations.

``app/gateway/routers/mcp.py`` manages the single ``mcpServers`` key of the
shared ``extensions_config.json`` -- one file per Gateway process, not one
per organization (see that router's module docstring and
``persistence/AGENTS.md``'s "deployment-global, not shareable" list, which
this test file is referenced from). This mirrors
``test_managed_subagents_stay_global_and_admin_only_across_orgs`` in
``tests/test_org_isolation_d_agents.py``: the property under test is that
the *same* configuration is visible/mutable while org A or org B is active
(never per-organization data), and that admin gating is by system role, not
by organization role, so it holds identically regardless of which
organization is active.

No database is needed: ``mcp.py`` never calls ``resolve_organization_id()``
at all, so ``acting_as`` only needs to vary ``request.state.user`` for the
admin check while the extensions_config.json path stays fixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as  # noqa: F401

from app.gateway.routers import mcp as mcp_router

pytestmark = pytest.mark.asyncio

_SEED_CONFIG = {
    "mcpServers": {
        "github": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "enabled": True,
        }
    },
    "skills": {},
}


def _seed_config(tmp_path: Path, monkeypatch) -> Path:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps(_SEED_CONFIG), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    return config_path


def _request(system_role: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="actor", system_role=system_role), auth_source=None))


async def test_mcp_config_is_the_same_regardless_of_active_organization(tmp_path, monkeypatch) -> None:
    _seed_config(tmp_path, monkeypatch)

    # Org A's admin disables the server that was seeded enabled.
    with acting_as(USER_A, ORG_A):
        updated = await mcp_router.update_mcp_server_state(
            _request("admin"),
            mcp_router.McpServerStateUpdateRequest(server_name="github", enabled=False),
        )
    assert updated.mcp_servers["github"].enabled is False

    # Org B's admin -- a wholly different organization -- reads the exact
    # same edit. There is no per-organization copy to fall back to.
    with acting_as(USER_B, ORG_B):
        seen_by_b = await mcp_router.get_mcp_configuration(_request("admin"))
    assert seen_by_b.mcp_servers["github"].enabled is False

    # And org B's admin can mutate it right back -- global state, shared by
    # every organization's admin, not owned by whichever org wrote it last.
    with acting_as(USER_B, ORG_B):
        reverted = await mcp_router.update_mcp_server_state(
            _request("admin"),
            mcp_router.McpServerStateUpdateRequest(server_name="github", enabled=True),
        )
    assert reverted.mcp_servers["github"].enabled is True

    with acting_as(USER_A, ORG_A):
        seen_by_a_again = await mcp_router.get_mcp_configuration(_request("admin"))
    assert seen_by_a_again.mcp_servers["github"].enabled is True


async def test_mcp_config_mutation_is_admin_only_regardless_of_active_organization(tmp_path, monkeypatch) -> None:
    _seed_config(tmp_path, monkeypatch)

    for organization_id, user_id in ((ORG_A, USER_A), (ORG_B, USER_B)):
        with acting_as(user_id, organization_id):
            with pytest.raises(HTTPException) as excinfo:
                await mcp_router.get_mcp_configuration(_request("user"))
            assert excinfo.value.status_code == 403

            with pytest.raises(HTTPException) as excinfo:
                await mcp_router.update_mcp_server_state(
                    _request("user"),
                    mcp_router.McpServerStateUpdateRequest(server_name="github", enabled=False),
                )
            assert excinfo.value.status_code == 403

    # Unmutated by every denied attempt above, from either organization.
    with acting_as(USER_A, ORG_A):
        still_enabled = await mcp_router.get_mcp_configuration(_request("admin"))
    assert still_enabled.mcp_servers["github"].enabled is True
