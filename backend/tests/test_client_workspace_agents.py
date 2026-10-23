"""A client inside their dedicated customer workspace sees and runs that workspace's own agents, read-only.

Synthetic names only (``acme-dental``). Workspace admission itself (memberships,
``customer_client_id``) is covered with SQL in ``test_client_portal``; here it is
patched so the visibility and run-policy rules are exercised in isolation.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from test_momobot_max import _config, _run_config, _user, agent_env, as_role  # noqa: F401 -- fixtures

from app.gateway import momobot_max
from app.gateway.momobot_max import apply_run_policy
from app.gateway.routers.agents import get_agent, list_agents
from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME
from deerflow.config.paths import get_paths
from deerflow.persistence.agents import get_agent_store
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

WORKSPACE_BUCKET = "ws-acme-dental"  # the dedicated workspace's storage principal, not a login
OTHER_BUCKET = "ws-someone-else"
UNLOCKED = _config(momobot_max={"enabled": True, "clients": ["acme-dental"]})


def _store_agent(bucket: str, name: str, *, legacy: bool = False) -> None:
    paths = get_paths()
    agent_dir = paths.agent_dir(name) if legacy else paths.user_agent_dir(bucket, name)
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text(f"name: {name}\ndisplay_name: {name.title()}\ndescription: Tailored for {name}\nmodel: claude-opus-5-5\n")
    (agent_dir / "SOUL.md").write_text("Never shown to a client.\n")


@pytest.fixture
def workspace(agent_env, as_role):  # noqa: F811 -- pytest fixture plumbing
    """Three agents on disk: the client's own workspace's, another workspace's, and a legacy shared one."""
    _store_agent(WORKSPACE_BUCKET, "acme-dental-max")
    _store_agent(OTHER_BUCKET, "someone-elses-max")
    _store_agent("", "internal-bot", legacy=True)
    as_role("client")
    token = set_storage_context(WorkspaceStorageContext(actor_user_id="u-1", organization_id="org-acme", storage_user_id=WORKSPACE_BUCKET))
    try:
        yield
    finally:
        reset_storage_context(token)


@contextmanager
def _admitted(*, keys=("acme-dental",), app_config=UNLOCKED, workspace_check=None):
    async def fake_keys(_user_id, _organization_id=None):
        return keys

    with (
        patch.object(momobot_max, "client_keys_for_user", fake_keys),
        patch("app.gateway.client_workspace.require_client_workspace", new=workspace_check or AsyncMock()),
        patch("app.gateway.routers.agents.get_app_config", return_value=app_config),
        patch("app.gateway.momobot_max.get_app_config", return_value=app_config, create=True),
    ):
        yield


# -- what a client sees -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_client_sees_their_workspaces_agent_beside_momobot_max_and_nothing_about_how_it_works(workspace):
    with _admitted():
        listed = {a.name: a.model_dump() for a in (await list_agents()).agents}
    assert list(listed) == [MOMOBOT_MAX_NAME, "acme-dental-max"]
    own = listed["acme-dental-max"]
    assert (own["display_name"], own["description"], own["builtin"]) == ("Acme-Dental-Max", "Tailored for acme-dental-max", False)
    assert own["model"] is None and own["soul"] is None and own["tool_names"] is None and own["allowed_subagents"] is None
    with _admitted():
        read = await get_agent("acme-dental-max")
    assert read.soul is None and read.model is None and read.builtin is False


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["someone-elses-max", "internal-bot"])
async def test_another_workspaces_agent_and_a_legacy_shared_agent_are_invisible(workspace, foreign):
    with _admitted():
        assert foreign not in [a.name for a in (await list_agents()).agents]
        with pytest.raises(HTTPException) as missing:
            await get_agent(foreign)
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_outside_a_dedicated_workspace_a_client_still_gets_only_momobot_max(workspace):
    refused = AsyncMock(side_effect=HTTPException(403, "no dedicated workspace"))
    with _admitted(workspace_check=refused):
        assert [a.name for a in (await list_agents()).agents] == [MOMOBOT_MAX_NAME]
        with pytest.raises(HTTPException) as missing:
            await get_agent("acme-dental-max")
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_a_base_subscription_never_reaches_a_workspace_agent(workspace):
    with _admitted(keys=("not-unlocked",)):
        listed = (await list_agents()).agents
    assert [(a.name, a.display_name) for a in listed] == [(MOMOBOT_MAX_NAME, "MomoBot")]


@pytest.mark.asyncio
async def test_staff_listing_is_unchanged(workspace, as_role):  # noqa: F811
    as_role("admin")
    with _admitted():
        listed = {a.name: a for a in (await list_agents()).agents}
    # Staff in the same workspace read the full definition, legacy shared agents included, as before.
    assert set(listed) == {MOMOBOT_MAX_NAME, "acme-dental-max", "internal-bot"}
    assert listed["acme-dental-max"].soul == "Never shown to a client." and listed["acme-dental-max"].model == "claude-opus-5-5"


# -- the run policy -----------------------------------------------------------------


async def _policy(context: dict, *, keys=("acme-dental",), workspace_check=None) -> dict:
    config = _run_config(context=context)
    with _admitted(keys=keys, workspace_check=workspace_check):
        await apply_run_policy(config, user=_user("client"), actor_user_id="u-1", app_config=UNLOCKED)
    return config


@pytest.mark.asyncio
async def test_a_client_run_of_their_workspace_agent_keeps_it_on_its_own_model_with_the_max_settings(workspace):
    config = await _policy({"agent_name": "Acme_Dental_Max", "model_name": "cheap-model", "reasoning_effort": "low", "subagent_enabled": False, "momobot_tier": "base"})
    for section in (config["configurable"], config["context"]):
        assert section["agent_name"] == "acme-dental-max"
        assert "model_name" not in section and "model" not in section  # the agent's config.yaml decides, under the client role's model policy
        assert (section["reasoning_effort"], section["thinking_enabled"], section["subagent_enabled"], section["momobot_tier"]) == ("high", True, True, "max")


@pytest.mark.asyncio
@pytest.mark.parametrize("named", ["someone-elses-max", "internal-bot", "finance-bot"])
async def test_a_client_run_naming_any_other_agent_is_pinned_to_momobot_max(workspace, named):
    config = await _policy({"agent_name": named})
    assert config["context"]["agent_name"] == MOMOBOT_MAX_NAME and config["configurable"]["agent_name"] == MOMOBOT_MAX_NAME


@pytest.mark.asyncio
async def test_a_base_client_run_naming_the_workspace_agent_falls_back_to_the_base_chat(workspace):
    config = await _policy({"agent_name": "acme-dental-max"}, keys=("not-unlocked",))
    assert config["context"]["agent_name"] == MOMOBOT_MAX_NAME and config["context"]["momobot_tier"] == "base"


# -- the store ----------------------------------------------------------------------


def test_the_store_can_list_a_bucket_without_the_legacy_shared_layout(workspace):
    store = get_agent_store()
    assert [a.name for a in store.list(user_id=WORKSPACE_BUCKET)] == ["acme-dental-max", "internal-bot"]
    assert [a.name for a in store.list(user_id=WORKSPACE_BUCKET, include_legacy=False)] == ["acme-dental-max"]


# -- the ceiling on a client run of a workspace agent ------------------------------


@pytest.mark.asyncio
async def test_a_client_run_of_a_workspace_agent_carries_the_server_set_ceiling_and_a_request_cannot_set_it(workspace):
    config = await _policy({"agent_name": "acme-dental-max", "client_workspace_ceiling": False})
    assert config["context"]["client_workspace_ceiling"] is True and config["configurable"]["client_workspace_ceiling"] is True
    builtin = await _policy({"agent_name": MOMOBOT_MAX_NAME, "client_workspace_ceiling": True})
    assert "client_workspace_ceiling" not in builtin["context"] and "client_workspace_ceiling" not in builtin["configurable"]


def test_the_ceiling_keeps_a_workspace_agent_inside_momobot_maxs_tools_with_nothing_extra():
    from deerflow.config.agents_config import AgentConfig
    from deerflow.config.builtin_agents import MOMOBOT_MAX_TOOL_NAMES, client_workspace_ceiling

    uncapped = client_workspace_ceiling(AgentConfig(name="acme-dental-max", model="claude-opus-5-5"))
    assert uncapped.tool_names == list(MOMOBOT_MAX_TOOL_NAMES)
    assert (uncapped.skills, uncapped.mcp_plugins, uncapped.self_update_enabled, uncapped.memory_enabled) == ([], [], False, False)
    assert uncapped.knowledge_scope is not None and uncapped.knowledge_scope.mode == "disabled"
    assert uncapped.model == "claude-opus-5-5"
    narrowed = client_workspace_ceiling(AgentConfig(name="acme-dental-max", tool_names=["web_search", "bash", "update_agent"]))
    assert narrowed.tool_names == ["web_search"]


def test_the_lead_agent_applies_the_ceiling_with_role_permissions_off(monkeypatch):
    """With authorization off and an agent that names no tools, a marked run still only gets MomoBot Max's tools."""
    from unittest.mock import MagicMock, create_autospec

    from test_lead_agent_model_resolution import _make_app_config, _make_model

    import deerflow.agents.lead_agent.agent as lead_agent_module
    import deerflow.tools as tools_module
    from deerflow.config.agents_config import AgentConfig

    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    def _named_tool(name: str):
        tool = MagicMock()
        tool.name = name
        return tool

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda name, **_: AgentConfig(name=name))
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [_named_tool("bash"), _named_tool("web_search"), _named_tool("gmail_send")])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", create_autospec(lead_agent_module.build_middlewares, return_value=[]))
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "prompt")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    def tools_for(context):
        result = lead_agent_module.make_lead_agent({"context": {"model_name": "safe-model", "thinking_enabled": False, "subagent_enabled": False, "agent_name": "acme-dental-max", **context}})
        return sorted(tool.name for tool in result["tools"])

    assert tools_for({}) == ["bash", "gmail_send", "update_agent", "web_search"]  # staff: the agent's own, uncapped
    assert tools_for({"client_workspace_ceiling": True}) == ["web_search"]


@pytest.mark.asyncio
async def test_an_agent_stamped_for_another_client_or_with_a_capitalized_name_is_handled(workspace):
    paths = get_paths()
    other = paths.user_agent_dir(WORKSPACE_BUCKET, "rival-max")
    other.mkdir(parents=True)
    (other / "config.yaml").write_text("name: rival-max\ndescription: x\nclient_id: rival-co\n")
    caps = paths.user_agent_dir(WORKSPACE_BUCKET, "acme-caps")
    caps.mkdir(parents=True)
    (caps / "config.yaml").write_text("name: Acme-Caps\ndescription: x\n")
    with _admitted():
        agents = await momobot_max.client_workspace_agents(_user("client"), "u-1", UNLOCKED)
    assert sorted(agents) == ["acme-caps", "acme-dental-max"]


@pytest.mark.asyncio
async def test_an_unreadable_bucket_leaves_the_client_with_momobot_max_only(workspace):
    with _admitted(), patch.object(momobot_max, "_bucket_agents", side_effect=ValueError("bad row")):
        assert await momobot_max.client_workspace_agents(_user("client"), "u-1", UNLOCKED) == {}


@pytest.mark.asyncio
async def test_a_workspace_agent_with_no_model_runs_on_the_model_that_was_checked(workspace):
    agent_dir = get_paths().user_agent_dir(WORKSPACE_BUCKET, "acme-plain")
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text("name: acme-plain\ndescription: x\n")
    config = await _policy({"agent_name": "acme-plain"})
    assert config["context"]["agent_name"] == "acme-plain"
    assert config["context"]["model_name"] == UNLOCKED.momobot_max.model
    with_model = await _policy({"agent_name": "acme-dental-max"})
    assert "model_name" not in with_model["context"]
