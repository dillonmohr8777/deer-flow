"""MomoBot Max: the built-in agent, its config, who can use it and what every run of it gets."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from _role_tier_example import example_authorization
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway import momobot_max
from app.gateway.momobot_max import apply_run_policy, client_keys_for_user, momobot_max_available_to
from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.agents_config import load_agent_config, load_agent_soul
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME, MOMOBOT_MAX_TOOL_NAMES, get_builtin_agent_config
from deerflow.config.momobot_max_config import MomobotMaxConfig
from deerflow.persistence.base import Base
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.runtime.user_context import set_current_user

MODELS = [{"name": name, "use": "langchain_openai:ChatOpenAI", "model": name} for name in ("claude-opus-5-5", "claude-haiku-5-5", "cheap-model")]
FORBIDDEN_IN_SOUL = ["subagent", "sub-agent", "claude", "opus", "anthropic", "openrouter", "luna", "deerflow", "langgraph", "mcp", "dillon"]


def _config(*, momobot_max: dict | None = None, authorization: dict | None = None) -> AppConfig:
    data = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": MODELS}
    if momobot_max is not None:
        data["momobot_max"] = momobot_max
    if authorization is not None:
        data["authorization"] = authorization
    return AppConfig.model_validate(data)


def _user(role: str, user_id: str = "u-1") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, system_role=role, oauth_provider=None, oauth_id=None)


@pytest.fixture
def agent_env(tmp_path: Path, monkeypatch):
    """Isolated agent storage with MomoBot Max enabled and no role policy."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    set_app_config(_config(momobot_max={"enabled": True}))
    try:
        yield
    finally:
        load_agents_api_config_from_dict({})
        reset_app_config()


@pytest.fixture
def as_role():
    """Run the router as a signed-in user with the given role (ends with the test's task context)."""

    def _as(role: str):
        set_current_user(_user(role))

    return _as


# -- config ----------------------------------------------------------------


def test_it_is_off_by_default_on_opus_at_high_effort():
    settings = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}).momobot_max
    assert (settings.enabled, settings.model, settings.default_effort, settings.client_effort) == (False, "claude-opus-5-5", "high", {})


def test_the_clients_override_wins_then_the_default():
    settings = MomobotMaxConfig(default_effort="medium", client_effort={"acme-dental": "high", "acme": "low"})
    assert settings.effort_for(("acme-dental",)) == "high"
    assert settings.effort_for(("c-123", "acme")) == "low"  # the first key with an override
    assert settings.effort_for(("someone-else",)) == "medium"
    assert settings.effort_for() == "medium"


@pytest.mark.parametrize("bad", ["max", "xhigh", "", "HIGH"])
def test_an_effort_outside_low_medium_high_is_rejected(bad):
    with pytest.raises(ValidationError):
        MomobotMaxConfig(default_effort=bad)
    with pytest.raises(ValidationError):
        MomobotMaxConfig(client_effort={"acme-dental": bad})


def test_the_example_block_validates():
    config = _config(momobot_max={"enabled": True, "model": "claude-opus-5-5", "default_effort": "high", "client_effort": {"acme-dental": "high"}})
    assert config.momobot_max.effort_for(("acme-dental",)) == "high"


# -- the agent -----------------------------------------------------------------


def test_the_agent_is_defined_from_config_and_not_before(agent_env):
    agent = get_builtin_agent_config(MOMOBOT_MAX_NAME)
    assert agent is not None
    assert (agent.name, agent.display_name, agent.model) == ("momobot-max", "MomoBot Max", "claude-opus-5-5")
    assert agent.skills == [] and agent.mcp_plugins == [] and agent.self_update_enabled is False
    assert agent.tool_names == MOMOBOT_MAX_TOOL_NAMES
    assert agent.allowed_subagents is None  # it may delegate to anything enabled
    set_app_config(_config(momobot_max={"enabled": True, "model": "cheap-model"}))
    assert get_builtin_agent_config(MOMOBOT_MAX_NAME).model == "cheap-model"
    set_app_config(_config())
    assert get_builtin_agent_config(MOMOBOT_MAX_NAME) is None
    assert get_builtin_agent_config("something-else") is None


def test_the_tool_ceiling_is_the_clients_allow_list_from_the_example():
    roles = example_authorization()["provider"]["config"]["roles"]
    assert roles["client"]["tools"]["allow"] == MOMOBOT_MAX_TOOL_NAMES


def test_the_loaders_return_it_ahead_of_any_stored_agent(agent_env):
    from deerflow.persistence.agents import get_agent_store

    get_agent_store().create("momobot-max", {"name": "momobot-max", "model": "cheap-model"}, "A user wrote this.", user_id="u-1")
    assert load_agent_config("momobot-max", user_id="u-1").model == "claude-opus-5-5"
    assert "MomoBot Max" in load_agent_soul("momobot-max", user_id="u-1")
    # Off, the stored agent is just an agent again.
    set_app_config(_config())
    assert load_agent_config("momobot-max", user_id="u-1").model == "cheap-model"
    assert load_agent_soul("momobot-max", user_id="u-1") == "A user wrote this."


@pytest.mark.parametrize("word", FORBIDDEN_IN_SOUL)
def test_the_client_soul_never_names_the_machinery(agent_env, word):
    assert word not in load_agent_soul("momobot-max").lower()


def test_the_soul_says_what_it_covers_who_it_answers_to_and_what_needs_approval(agent_env):
    soul = load_agent_soul("momobot-max")
    for topic in ("Ads", "Content", "Search", "Reviews", "Google Business Profile", "Website", "Email", "lead follow-up", "Competitor", "Reporting"):
        assert re.search(topic, soul, re.IGNORECASE), topic
    assert "account manager" in soul
    assert re.search(r"sends, spends or goes live needs a person to approve", soul)
    assert "any other client" in soul


# -- who can use it -------------------------------------------------------------


@pytest.mark.parametrize(("role", "available"), [("admin", True), ("exec", True), ("client", True), ("user", False), ("mystery", False)])
def test_it_is_available_to_roles_that_may_use_its_model(role, available):
    config = _config(momobot_max={"enabled": True}, authorization=example_authorization())
    set_app_config(config)
    try:
        assert momobot_max_available_to(_user(role), config) is available
    finally:
        reset_app_config()


def test_it_is_unavailable_to_everyone_while_disabled():
    set_app_config(_config(authorization=example_authorization()))
    try:
        assert momobot_max_available_to(_user("admin"), _config(authorization=example_authorization())) is False
    finally:
        reset_app_config()


@pytest.mark.asyncio
async def test_the_picker_lists_it_first_for_admin_and_exec(agent_env, as_role):
    from deerflow.persistence.agents import get_agent_store

    get_agent_store().create("writer", {"name": "writer"}, "Writes.", user_id="u-1")
    for role in ("admin", "exec"):
        as_role(role)
        agents = (await list_agents()).agents
        assert [a.name for a in agents] == ["momobot-max", "writer"]
        assert agents[0].builtin is True and agents[0].display_name == "MomoBot Max" and agents[0].soul
        assert agents[1].builtin is False


@pytest.mark.asyncio
async def test_teammates_do_not_get_it_because_their_models_exclude_it(agent_env, as_role):
    set_app_config(_config(momobot_max={"enabled": True}, authorization=example_authorization()))
    as_role("user")
    assert (await list_agents()).agents == []
    with pytest.raises(HTTPException) as hidden:
        await get_agent("momobot-max")
    assert hidden.value.status_code == 404
    as_role("exec")
    assert [a.name for a in (await list_agents()).agents] == ["momobot-max"]


@pytest.mark.asyncio
async def test_a_client_sees_only_it_and_nothing_about_how_it_works(agent_env, as_role):
    from deerflow.config.paths import get_paths

    legacy = get_paths().agent_dir("internal-bot")  # the shared legacy layout every user can read
    legacy.mkdir(parents=True)
    (legacy / "config.yaml").write_text("name: internal-bot\n")
    as_role("client")
    listed = (await list_agents()).agents
    assert [a.name for a in listed] == ["momobot-max"]
    seen = listed[0].model_dump()
    assert seen["model"] is None and seen["soul"] is None and seen["tool_names"] is None and seen["allowed_subagents"] is None
    assert (await get_agent("momobot-max")).soul is None
    with pytest.raises(HTTPException) as other:
        await get_agent("internal-bot")
    assert other.value.status_code == 404


@pytest.mark.asyncio
async def test_a_client_reads_it_without_the_management_api_but_staff_still_need_it(agent_env, as_role):
    load_agents_api_config_from_dict({"enabled": False})
    as_role("client")
    assert [a.name for a in (await list_agents()).agents] == ["momobot-max"]
    assert (await get_agent("momobot-max")).display_name == "MomoBot"  # no client unlocked: the base subscription
    as_role("admin")
    with pytest.raises(HTTPException) as disabled:
        await list_agents()
    assert disabled.value.status_code == 403


@pytest.mark.asyncio
async def test_it_is_read_only_and_its_name_is_reserved(agent_env, as_role):
    as_role("admin")
    for call in (
        create_agent_endpoint(AgentCreateRequest(name="momobot-max", soul="mine")),
        create_agent_endpoint(AgentCreateRequest(name="MomoBot-Max", soul="mine")),
        update_agent("momobot-max", AgentUpdateRequest(soul="mine")),
        delete_agent("momobot-max"),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        assert refused.value.status_code == 403
    assert (await check_agent_name("momobot-max"))["available"] is False


# -- the run policy ---------------------------------------------------------------


def _run_config(**sections) -> dict:
    return {"recursion_limit": 100, "configurable": {"thread_id": "t-1", **sections.get("configurable", {})}, "context": dict(sections.get("context", {}))}


async def _policy(config: dict, user, *, keys=(), app_config=None, internal=False, actor="u-1"):
    async def fake_keys(_user_id, _organization_id=None):
        return keys

    # This helper exercises model/effort pinning in isolation. Real workspace
    # admission is covered with SQL memberships/binding in test_client_portal.
    with patch.object(momobot_max, "client_keys_for_user", fake_keys), patch("app.gateway.client_workspace.require_client_workspace", new=AsyncMock()):
        await apply_run_policy(
            config, user=user, actor_user_id=actor, app_config=app_config or _config(momobot_max={"enabled": True, "client_effort": {"acme-dental": "medium"}, "clients": ["acme-dental", "someone-else"]}), internal=internal
        )


@pytest.mark.asyncio
async def test_a_client_run_is_pinned_to_the_agent_whatever_the_request_names():
    config = _run_config(
        configurable={"agent_name": "finance-bot", "model_name": "cheap-model", "is_bootstrap": True},
        context={"agent_name": "lead_agent", "model_name": "claude-haiku-5-5", "model": "x", "reasoning_effort": "low", "thinking_enabled": False, "subagent_enabled": False},
    )
    await _policy(config, _user("client"), keys=("someone-else",))  # a client unlocked for Max
    for section in (config["configurable"], config["context"]):
        assert section["agent_name"] == "momobot-max"
        assert not {"model_name", "model", "is_bootstrap"} & set(section)
        assert (section["reasoning_effort"], section["thinking_enabled"], section["subagent_enabled"], section["momobot_tier"]) == ("high", True, True, "max")


@pytest.mark.asyncio
async def test_a_client_run_with_no_context_section_still_gets_pinned():
    config = {"configurable": {"thread_id": "t-1"}}
    await _policy(config, _user("client"))
    assert config["context"]["agent_name"] == "momobot-max" and config["configurable"]["agent_name"] == "momobot-max"


@pytest.mark.asyncio
async def test_effort_comes_from_the_clients_assignment_then_the_default():
    for keys, expected in ((("acme-dental", "c-1"), "medium"), (("someone-else",), "high")):
        config = _run_config()
        await _policy(config, _user("client"), keys=keys)
        assert config["context"]["reasoning_effort"] == expected, keys


@pytest.mark.asyncio
async def test_a_client_cannot_run_it_while_it_is_disabled():
    with pytest.raises(HTTPException) as refused:
        await _policy(_run_config(), _user("client"), app_config=_config())
    assert refused.value.status_code == 503


@pytest.mark.asyncio
async def test_config_owns_the_settings_for_every_caller_of_the_agent():
    config = _run_config(context={"agent_name": "momobot-max", "reasoning_effort": "low", "thinking_enabled": False, "subagent_enabled": False, "model_name": "cheap-model"})
    await _policy(config, _user("exec"))
    assert (config["context"]["reasoning_effort"], config["context"]["thinking_enabled"], config["context"]["subagent_enabled"]) == ("high", True, True)
    assert config["context"]["model_name"] == "cheap-model"  # only a client's model is dropped; the model allow-list still applies


@pytest.mark.asyncio
async def test_a_role_that_may_not_use_its_model_cannot_run_it_by_name():
    app_config = _config(momobot_max={"enabled": True}, authorization=example_authorization())
    set_app_config(app_config)
    try:
        with pytest.raises(HTTPException) as refused:
            await _policy(_run_config(context={"agent_name": "momobot-max"}), _user("user"), app_config=app_config)
        assert refused.value.status_code == 422
        await _policy(_run_config(context={"agent_name": "momobot-max"}), _user("exec"), app_config=app_config)
    finally:
        reset_app_config()


@pytest.mark.asyncio
async def test_every_other_run_is_left_exactly_as_it_was():
    for user in (_user("admin"), _user("exec"), _user("user")):
        config = {"configurable": {"thread_id": "t-1", "agent_name": "writer"}}
        before = {"configurable": dict(config["configurable"])}
        await _policy(config, user)
        assert config == before
    plain = {"configurable": {"thread_id": "t-1"}}
    await _policy(plain, _user("user"))
    assert plain == {"configurable": {"thread_id": "t-1"}}


@pytest.mark.asyncio
async def test_a_trusted_internal_caller_skips_the_visibility_check_but_gets_the_settings():
    config = _run_config(context={"agent_name": "momobot-max"})
    await _policy(config, SimpleNamespace(system_role="internal"), internal=True)
    assert config["context"]["reasoning_effort"] == "high"


# -- the client assignment lookup --------------------------------------------------


@pytest_asyncio.fixture()
async def clients_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ClientRow.__table__, ClientAssignmentRow.__table__, OrganizationRow.__table__]))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    ClientRow(id="c-1", display_name="Acme Dental", registry_id="acme-dental"),
                    ClientRow(id="c-2", display_name="Acme", registry_id=None),
                    ClientRow(id="c-3", display_name="Other", registry_id="other"),
                    ClientAssignmentRow(client_id="c-1", user_id="jordan", role="client_contact"),
                    ClientAssignmentRow(client_id="c-2", user_id="jordan", role="client_contact"),
                    ClientAssignmentRow(client_id="c-3", user_id="jordan", role="account_manager"),
                    ClientAssignmentRow(client_id="c-3", user_id="someone", role="client_contact"),
                ]
            )
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_client_contact_resolves_to_their_clients_registry_id_and_id(clients_db):
    assert await client_keys_for_user("jordan") == ("acme-dental", "c-1", "c-2")
    assert await client_keys_for_user("someone") == ("other", "c-3")  # only client_contact counts for justin, not account_manager
    assert await client_keys_for_user("nobody") == ()


@pytest.mark.asyncio
async def test_with_no_database_there_is_no_client_and_the_default_applies(monkeypatch):
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)
    assert await client_keys_for_user("jordan") == ()


# -- start_run applies the policy -----------------------------------------------


async def _start_run_as(role: str, context: dict, *, app_config: AppConfig):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.routers.thread_runs import RunCreateRequest
    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=None, user=_user(role)),
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(),
                run_manager=RunManager(store=MemoryRunStore()),
                checkpointer=InMemorySaver(),
                store=InMemoryStore(),
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(InMemoryStore()),
            )
        ),
    )
    body = RunCreateRequest(input={"messages": [{"role": "user", "content": "hello"}]}, context=context)
    captured: dict = {}

    async def fake_run_agent(*args, **kwargs):
        captured["config"] = kwargs["config"]

    set_app_config(app_config)
    try:
        with patch("app.gateway.services.resolve_agent_factory", return_value=object()), patch("app.gateway.services.run_agent", side_effect=fake_run_agent), patch("app.gateway.client_workspace.require_client_workspace", new=AsyncMock()):
            record = await start_run(body, "thread-max", request)
            await record.task
    finally:
        reset_app_config()
    return captured["config"]


@pytest.mark.asyncio
async def test_start_run_pins_a_client_to_the_agent_before_anything_reads_the_agent_name():
    app_config = _config(momobot_max={"enabled": True, "base_effort": "low"})
    config = await _start_run_as("client", {"agent_name": "finance-bot", "model_name": "cheap-model", "reasoning_effort": "high", "subagent_enabled": True}, app_config=app_config)

    for section in (config["configurable"], config["context"]):
        assert section["agent_name"] == "momobot-max"
        # The client's own model is scrubbed; a client with no Max gets the base model, which start_run admits and meters.
        assert section["model_name"] == "claude-haiku-5-5"
        assert (section["reasoning_effort"], section["subagent_enabled"], section["thinking_enabled"], section["momobot_tier"]) == ("low", False, False, "base")
    assert config["context"]["user_role"] == "client"


@pytest.mark.asyncio
async def test_start_run_leaves_a_teammates_ordinary_run_alone():
    config = await _start_run_as("user", {"model_name": "cheap-model", "reasoning_effort": "low"}, app_config=_config(momobot_max={"enabled": True}))

    assert config["context"]["model_name"] == "cheap-model" and config["context"]["reasoning_effort"] == "low"
    assert "agent_name" not in config["context"]


@pytest.mark.asyncio
async def test_the_total_subagent_cap_is_config_owned_not_request_owned():
    app_config = _config(momobot_max={"enabled": True})
    cap = app_config.subagents.max_total_per_run
    app_config = _config(momobot_max={"enabled": True, "clients": ["acme-dental"]})
    for user in (_user("client"), _user("exec")):
        config = _run_config(
            configurable={"max_total_subagents": 50},
            context={"agent_name": "momobot-max", "max_total_subagents": 50},
        )
        await _policy(config, user, app_config=app_config, keys=("acme-dental",))
        assert config["context"]["max_total_subagents"] == cap
        assert config["configurable"]["max_total_subagents"] == cap


@pytest.mark.asyncio
async def test_a_stored_row_with_the_reserved_name_is_not_listed_beside_the_builtin(agent_env, as_role):
    from deerflow.persistence.agents import get_agent_store

    get_agent_store().create("momobot-max", {"name": "momobot-max", "model": "cheap-model"}, "A user wrote this.", user_id="u-1")
    get_agent_store().create("writer", {"name": "writer"}, "Writes.", user_id="u-1")
    as_role("admin")
    listed = (await list_agents()).agents
    assert [a.name for a in listed] == ["momobot-max", "writer"]
    assert listed[0].builtin is True
    # Off, the stored row is an ordinary agent again and is listed.
    set_app_config(_config())
    assert sorted(a.name for a in (await list_agents()).agents) == ["momobot-max", "writer"]


# -- the tier: MomoBot Max is the base subscription plus the all-in-one agent --


def test_a_client_has_max_only_when_one_of_its_keys_is_unlocked():
    settings = MomobotMaxConfig(clients=["acme-dental"])
    assert settings.unlocked_for(("c-9", "acme-dental")) is True
    assert settings.unlocked_for(("someone-else",)) is False
    assert settings.unlocked_for(()) is False
    assert MomobotMaxConfig().clients == [] and (MomobotMaxConfig().base_model, MomobotMaxConfig().base_effort) == ("claude-haiku-5-5", "medium")


@pytest.mark.asyncio
@pytest.mark.parametrize("keys", [("not-unlocked",), ()])
async def test_a_client_without_max_gets_the_base_chat_on_the_same_agent(keys):
    config = _run_config(context={"agent_name": "momobot-max", "model_name": "claude-opus-5-5", "reasoning_effort": "high", "thinking_enabled": True, "subagent_enabled": True})
    await _policy(config, _user("client"), keys=keys)
    for section in (config["configurable"], config["context"]):
        assert section["agent_name"] == "momobot-max"  # one agent, one memory, whatever the tier
        assert (section["model_name"], section["reasoning_effort"], section["thinking_enabled"], section["subagent_enabled"], section["momobot_tier"]) == ("claude-haiku-5-5", "medium", False, False, "base")
        assert "max_total_subagents" not in section


@pytest.mark.asyncio
async def test_the_tier_is_set_by_the_server_never_by_the_request():
    base = _run_config(context={"momobot_tier": "max"}, configurable={"momobot_tier": "max"})
    await _policy(base, _user("client"))
    assert base["context"]["momobot_tier"] == base["configurable"]["momobot_tier"] == "base"
    staff = _run_config(context={"agent_name": "finance-bot", "momobot_tier": "base"})
    await _policy(staff, _user("admin"))
    assert "momobot_tier" not in staff["context"]
    exec_run = _run_config(context={"agent_name": "momobot-max", "momobot_tier": "base"})
    await _policy(exec_run, _user("exec"))
    assert exec_run["context"]["momobot_tier"] == "max"  # staff always get Max


@pytest.mark.asyncio
async def test_a_base_client_whose_role_may_not_use_the_base_model_is_refused():
    authorization = example_authorization()
    authorization["provider"]["config"]["roles"]["client"]["models"] = {"allow": ["claude-opus-5-5"]}
    app_config = _config(momobot_max={"enabled": True, "clients": ["acme-dental"]}, authorization=authorization)
    set_app_config(app_config)
    try:
        with pytest.raises(HTTPException) as refused:
            await _policy(_run_config(), _user("client"), app_config=app_config)
        assert refused.value.status_code == 422
        await _policy(_run_config(), _user("client"), app_config=app_config, keys=("acme-dental",))  # Max uses the allowed model
    finally:
        reset_app_config()


@pytest.mark.asyncio
async def test_a_client_sees_momobot_on_base_and_momobot_max_once_unlocked(agent_env, as_role):
    set_app_config(_config(momobot_max={"enabled": True, "clients": ["acme-dental"]}))
    as_role("client")
    for keys, name in (((), "MomoBot"), (("acme-dental",), "MomoBot Max")):
        with patch.object(momobot_max, "client_keys_for_user", AsyncMock(return_value=keys)):
            listed = (await list_agents()).agents
            fetched = await get_agent("momobot-max")
        assert [a.name for a in listed] == ["momobot-max"] and listed[0].display_name == fetched.display_name == name, keys
        assert fetched.model is None and fetched.soul is None


@pytest.mark.asyncio
async def test_a_client_gets_the_tier_of_the_workspace_it_chats_in_and_archived_clients_never_count(clients_db):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    async with clients_db() as session:
        async with session.begin():
            session.add(OrganizationRow(id="org-c2", slug="acme", name="Acme", status="active", storage_user_id="s", customer_client_id="c-2", created_at=now, updated_at=now))
            session.add(OrganizationRow(id="org-staff", slug="agency", name="Agency", status="active", storage_user_id="s2", created_at=now, updated_at=now))
    assert await client_keys_for_user("jordan", "org-c2") == ("c-2",)  # not the unlocked c-1 they also contact for
    assert await client_keys_for_user("jordan", "org-staff") == ()  # a workspace bound to no client
    async with clients_db() as session:
        async with session.begin():
            row = await session.get(ClientRow, "c-1")
            row.status = "archived"
    assert await client_keys_for_user("jordan") == ("c-2",)


def test_a_client_side_job_always_runs_on_the_base_model():
    set_app_config(_config(momobot_max={"enabled": True, "base_model": "claude-haiku-5-5"}))
    try:
        assert momobot_max.client_side_model(_user("client"), "claude-opus-5-5") == "claude-haiku-5-5"
        assert momobot_max.client_side_model(_user("client"), None) == "claude-haiku-5-5"
        for role in ("admin", "exec", "user"):
            assert momobot_max.client_side_model(_user(role), "claude-opus-5-5") == "claude-opus-5-5"
    finally:
        reset_app_config()


# -- staff on a cheaper model (Dillon, Oct 22: clients get Opus, the team Haiku 5.5) --

_STAFF_CHEAP = {"enabled": True, "model": "claude-opus-5-5", "staff_model": "claude-haiku-5-5", "staff_effort": "high", "clients": ["acme-dental"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "exec"])
async def test_non_admin_staff_run_max_on_the_staff_model(role):
    config = _run_config(context={"agent_name": "momobot-max", "model_name": "claude-opus-5-5", "reasoning_effort": "low"})
    await _policy(config, _user(role), app_config=_config(momobot_max=_STAFF_CHEAP, authorization=example_authorization()))
    assert config["context"]["model_name"] == "claude-haiku-5-5"
    assert (config["context"]["reasoning_effort"], config["context"]["momobot_tier"]) == ("high", "max")


@pytest.mark.asyncio
async def test_admins_and_max_clients_keep_the_max_model():
    for user, keys in ((_user("admin"), ()), (_user("client"), ("acme-dental",))):
        config = _run_config(context={"agent_name": "momobot-max"})
        await _policy(config, user, keys=keys, app_config=_config(momobot_max=_STAFF_CHEAP, authorization=example_authorization()))
        assert config["context"].get("model_name") != "claude-haiku-5-5"


def test_staff_whose_role_may_use_the_staff_model_can_open_max():
    config = _config(momobot_max=_STAFF_CHEAP, authorization=example_authorization())
    set_app_config(config)
    try:
        assert momobot_max_available_to(_user("user"), config) is True
        assert momobot_max_available_to(_user("user"), _config(momobot_max={"enabled": True}, authorization=example_authorization())) is False
    finally:
        reset_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["internal", None, "mystery"])
async def test_internal_channel_runs_and_unknown_roles_keep_the_max_model(role):
    config = _run_config(context={"agent_name": "momobot-max"})
    await _policy(config, _user(role) if role else SimpleNamespace(id="u-1"), app_config=_config(momobot_max=_STAFF_CHEAP, authorization=example_authorization()), internal=True)
    assert config["context"].get("model_name") != "claude-haiku-5-5"


def test_staff_who_may_not_use_the_staff_model_fall_back_to_the_max_model():
    settings = _config(momobot_max={**_STAFF_CHEAP, "staff_model": "not-in-any-role"}, authorization=example_authorization())
    set_app_config(settings)
    try:
        assert momobot_max.staff_runs_cheap(_user("exec"), settings.momobot_max) is False
        assert momobot_max_available_to(_user("exec"), settings) is True
    finally:
        reset_app_config()
