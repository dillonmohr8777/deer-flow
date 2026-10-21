"""The role tiers shown in config.example.yaml do what they claim, and an undefined role denies everything."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _role_tier_example import example_roles
from fastapi import HTTPException
from langchain_core.tools import tool

from app.gateway.authz import _ALL_PERMISSIONS, Permissions, model_use_allowed, resolve_route_permissions, role_has_policy
from app.gateway.routers import models as models_router
from deerflow.authz.enforcement import filter_tools_by_authorization
from deerflow.authz.provider import AuthzRequest, Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig

MODELS = ["claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4", "gpt-4o-mini"]
CLIENT_TOOLS = ["web_search", "web_fetch", "read_file", "write_file", "present_files", "ask_clarification", "view_image", "task", "tool_search"]
CHAT_PERMISSIONS = {p for p in _ALL_PERMISSIONS if p.startswith(("threads:", "runs:"))}


@pytest.fixture(scope="module")
def rbac() -> RbacAuthorizationProvider:
    return RbacAuthorizationProvider(roles=example_roles())


def _visible(rbac, role: str, resource: str, candidates: list[str]) -> list[str]:
    return rbac.filter_resources(Principal(user_id="u", role=role), resource, candidates)


def test_the_example_defines_all_four_tiers_and_the_default_role():
    assert {"admin", "exec", "user", "client"} <= set(example_roles())


def test_models_climb_the_tiers(rbac):
    assert _visible(rbac, "admin", "model", MODELS) == MODELS
    assert _visible(rbac, "exec", "model", MODELS) == ["claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4"]
    assert _visible(rbac, "user", "model", MODELS) == ["claude-haiku-5-5"]
    assert _visible(rbac, "client", "model", MODELS) == ["claude-opus-5-5"]


def test_a_client_gets_only_the_minimal_tool_list(rbac):
    candidates = [*CLIENT_TOOLS, "bash", "ls", "str_replace", "update_agent", "propose_action", "browser_navigate", "mcp_anything"]
    assert _visible(rbac, "client", "tool", candidates) == CLIENT_TOOLS


def test_exec_has_the_same_tools_as_user_and_neither_may_self_update(rbac):
    candidates = ["web_search", "bash", "update_agent"]
    assert _visible(rbac, "exec", "tool", candidates) == _visible(rbac, "user", "tool", candidates) == ["web_search", "bash"]


def test_route_permissions_per_tier(rbac):
    def granted(role: str) -> set[str]:
        return {p for p in _ALL_PERMISSIONS if rbac.authorize(AuthzRequest(principal=Principal(role=role), resource="route", action=p.split(":")[1], target=p)).allow}

    assert granted("admin") == set(_ALL_PERMISSIONS)
    assert granted("exec") == granted("user") == set(_ALL_PERMISSIONS) - {Permissions.FLEET_WORK}
    assert granted("client") == CHAT_PERMISSIONS


def test_a_client_has_no_skills_and_may_use_the_sandbox_for_file_tools(rbac):
    assert _visible(rbac, "client", "skill", ["a", "b"]) == []
    assert rbac.authorize(AuthzRequest(principal=Principal(role="client"), resource="sandbox", action="execute", target="*")).allow


# -- an undefined role denies everything --------------------------------------


@pytest.fixture
def enabled(monkeypatch):
    """RBAC from the example, minus the client block: `client` is undefined."""
    roles = {name: policy for name, policy in example_roles().items() if name != "client"}
    provider = RbacAuthorizationProvider(roles=roles)
    config = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda _config: provider)
    return provider


UNDEFINED = ["client", "mystery", "Admin"]


@pytest.mark.parametrize("role", UNDEFINED)
def test_the_provider_refuses_to_decide_for_an_undefined_role(enabled, role):
    with pytest.raises(ValueError, match="Unknown role"):
        enabled.authorize(AuthzRequest(principal=Principal(role=role), resource="tool", action="call", target="web_search"))
    with pytest.raises(ValueError, match="Unknown role"):
        enabled.filter_resources(Principal(role=role), "model", MODELS)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", UNDEFINED)
async def test_an_undefined_role_gets_no_route_permission(enabled, role):
    user = SimpleNamespace(id="u-1", system_role=role, oauth_provider=None, oauth_id=None)
    assert await resolve_route_permissions(user, is_internal=False) == []


@pytest.mark.parametrize("role", UNDEFINED)
def test_an_undefined_role_sees_no_tools(enabled, role):
    @tool
    def web_search(query: str) -> str:
        """Search."""
        return query

    kept = filter_tools_by_authorization([web_search], provider=enabled, principal=Principal(user_id="u", role=role), fail_closed=True)
    assert kept == []


@pytest.mark.parametrize("role", UNDEFINED)
def test_an_undefined_role_may_use_no_model(enabled, role):
    user = SimpleNamespace(id="u-1", system_role=role, oauth_provider=None, oauth_id=None)
    assert model_use_allowed(user, "claude-opus-5-5", is_internal=False, fail_closed=True) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("role", UNDEFINED)
async def test_the_model_routes_show_an_undefined_role_nothing(enabled, role, monkeypatch):
    user = SimpleNamespace(id="u-1", system_role=role, oauth_provider=None, oauth_id=None)

    async def current_user(_request):
        return user

    monkeypatch.setattr(models_router, "get_optional_user_from_request", current_user)
    config = SimpleNamespace(
        models=[SimpleNamespace(name=n, model=n, display_name=n, description=None, supports_thinking=False, supports_reasoning_effort=False) for n in MODELS],
        authorization=AuthorizationConfig(enabled=True, fail_closed=True),
        token_usage=SimpleNamespace(enabled=False),
    )
    config.get_model_config = lambda name: next((m for m in config.models if m.name == name), None)
    request = SimpleNamespace(state=SimpleNamespace(), headers={})

    assert (await models_router.list_models(request, config)).models == []
    with pytest.raises(HTTPException) as denied:
        await models_router.get_model("claude-opus-5-5", request, config)
    assert denied.value.status_code == 403


def test_role_has_policy_tells_an_admin_which_roles_would_lock_a_user_out(enabled):
    assert role_has_policy("exec") is True
    assert role_has_policy("client") is False


def test_role_has_policy_is_true_when_authorization_is_off(monkeypatch):
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    assert role_has_policy("client") is True
