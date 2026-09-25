from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import features


def _app_with_config(
    *,
    agents_api_enabled: bool,
    browser_enabled: bool = False,
    browser_extra: dict | None = None,
    mcp_tasks_available: bool = False,
    subagent_batches_available: bool = False,
    subagent_batch_repo_available: bool | None = None,
    conversation_references_enabled: bool = False,
    knowledge_base_enabled: bool = False,
    scope_selection_enabled: bool = False,
    knowledge_search_provider: str | None = None,
    private_workspace_enabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.state.mcp_tasks_available = mcp_tasks_available
    app.state.subagent_batches_available = subagent_batches_available
    if subagent_batch_repo_available is None:
        subagent_batch_repo_available = subagent_batches_available
    app.state.subagent_batch_repo = object() if subagent_batch_repo_available else None
    app.include_router(features.router)
    tools = []
    if browser_enabled:
        tools.append(SimpleNamespace(name="browser_navigate", use="deerflow.community.browser:browser_navigate_tool", model_extra=browser_extra or {}))
    if conversation_references_enabled:
        tools.append(SimpleNamespace(name="read_conversation", use="deerflow.tools.conversation:read_conversation", model_extra={}))
    fake_config = SimpleNamespace(
        agents_api=SimpleNamespace(enabled=agents_api_enabled),
        tools=tools,
        subagent_runtime=SimpleNamespace(max_running=3),
        knowledge_base=SimpleNamespace(
            enabled=knowledge_base_enabled,
            scope_selection_enabled=scope_selection_enabled,
        ),
        private_workspace=SimpleNamespace(enabled=private_workspace_enabled),
    )
    search_tool = SimpleNamespace(use=knowledge_search_provider) if knowledge_search_provider is not None else None
    fake_config.get_tool_config = lambda name: search_tool if name == "knowledge_search" else None
    app.dependency_overrides[get_config] = lambda: fake_config
    return app


def test_features_reports_agents_api_enabled() -> None:
    with TestClient(_app_with_config(agents_api_enabled=True)) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json() == {
        "agents_api": {"enabled": True},
        "browser_control": {"enabled": False},
        "mcp_tasks": {"enabled": False},
        "subagent_batches": {
            "enabled": False,
            "repository_available": False,
            "worker_running": False,
            "max_running": 3,
        },
        "conversation_references": {"enabled": False, "max_references": 3},
        "knowledge_base": {
            "scope_selection_enabled": False,
        },
        "desk": {"enabled": False},
        "momentum_internal": {"enabled": False},
    }


def test_features_reports_agents_api_disabled() -> None:
    with TestClient(_app_with_config(agents_api_enabled=False)) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json() == {
        "agents_api": {"enabled": False},
        "browser_control": {"enabled": False},
        "mcp_tasks": {"enabled": False},
        "subagent_batches": {
            "enabled": False,
            "repository_available": False,
            "worker_running": False,
            "max_running": 3,
        },
        "conversation_references": {"enabled": False, "max_references": 3},
        "knowledge_base": {
            "scope_selection_enabled": False,
        },
        "desk": {"enabled": False},
        "momentum_internal": {"enabled": False},
    }


def test_features_reports_conversation_references_when_the_tool_is_configured() -> None:
    with TestClient(_app_with_config(agents_api_enabled=True, conversation_references_enabled=True)) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["conversation_references"] == {"enabled": True, "max_references": 3}


def test_features_enables_scope_selection_only_for_exact_ragflow_provider() -> None:
    with TestClient(
        _app_with_config(
            agents_api_enabled=True,
            knowledge_base_enabled=True,
            scope_selection_enabled=True,
            knowledge_search_provider=("deerflow.community.ragflow.tools:knowledge_search_tool"),
        )
    ) as client:
        response = client.get("/api/features")

    assert response.status_code == 200
    assert response.json()["knowledge_base"]["scope_selection_enabled"] is True


@pytest.mark.parametrize(
    ("knowledge_base_enabled", "provider"),
    [
        (False, "deerflow.community.ragflow.tools:knowledge_search_tool"),
        (True, "deerflow.community.lightrag.tools:knowledge_search_tool"),
        (True, "custom.provider:knowledge_search_tool"),
        (True, None),
    ],
)
def test_features_scope_selection_fails_closed(
    knowledge_base_enabled: bool,
    provider: str | None,
) -> None:
    with TestClient(
        _app_with_config(
            agents_api_enabled=True,
            knowledge_base_enabled=knowledge_base_enabled,
            scope_selection_enabled=True,
            knowledge_search_provider=provider,
        )
    ) as client:
        response = client.get("/api/features")

    assert response.status_code == 200
    assert response.json()["knowledge_base"]["scope_selection_enabled"] is False


def test_features_reports_mcp_tasks_startup_capability() -> None:
    with TestClient(_app_with_config(agents_api_enabled=True, mcp_tasks_available=True)) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["mcp_tasks"] == {"enabled": True}


def test_features_reports_subagent_batch_startup_capability() -> None:
    with TestClient(
        _app_with_config(
            agents_api_enabled=True,
            subagent_batches_available=True,
        )
    ) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["subagent_batches"] == {
        "enabled": True,
        "repository_available": True,
        "worker_running": True,
        "max_running": 3,
    }


def test_features_distinguishes_batch_history_from_worker_availability() -> None:
    with TestClient(
        _app_with_config(
            agents_api_enabled=True,
            subagent_batches_available=False,
            subagent_batch_repo_available=True,
        )
    ) as client:
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["subagent_batches"] == {
        "enabled": False,
        "repository_available": True,
        "worker_running": False,
        "max_running": 3,
    }


def test_features_reports_browser_control_enabled_when_configured_and_runtime_available() -> None:
    with (
        patch("app.gateway.browser_capability.importlib.util.find_spec", return_value=object()),
        TestClient(_app_with_config(agents_api_enabled=True, browser_enabled=True)) as client,
    ):
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["browser_control"] == {"enabled": True}


def test_features_reports_browser_control_disabled_when_runtime_missing() -> None:
    with (
        patch("app.gateway.browser_capability.importlib.util.find_spec", return_value=None),
        TestClient(_app_with_config(agents_api_enabled=True, browser_enabled=True)) as client,
    ):
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["browser_control"] == {"enabled": False}


def test_features_reports_browser_control_disabled_for_unguarded_cdp() -> None:
    with (
        patch("app.gateway.browser_capability.importlib.util.find_spec", return_value=object()),
        TestClient(
            _app_with_config(
                agents_api_enabled=True,
                browser_enabled=True,
                browser_extra={"cdp_url": "http://127.0.0.1:9222"},
            ),
        ) as client,
    ):
        response = client.get("/api/features")
    assert response.status_code == 200
    assert response.json()["browser_control"] == {"enabled": False}


def test_features_reports_desk_only_for_a_private_workspace() -> None:
    with TestClient(_app_with_config(agents_api_enabled=True, private_workspace_enabled=True)) as client:
        assert client.get("/api/features").json()["desk"] == {"enabled": True}
    with TestClient(_app_with_config(agents_api_enabled=True)) as client:
        assert client.get("/api/features").json()["desk"] == {"enabled": False}


def test_desk_is_off_for_a_default_client_facing_config() -> None:
    """A MomoBot config that never mentions private_workspace must not show Desk."""
    from deerflow.config.app_config import AppConfig

    assert AppConfig.model_fields["private_workspace"].default_factory().enabled is False


def _app_as(role: str | None, organization_id: str | None, *, internal_enabled: bool) -> FastAPI:
    """A features app whose requests carry *role* the way AuthMiddleware stamps it."""
    app = _app_with_config(agents_api_enabled=True)
    base = app.dependency_overrides[get_config]()
    base.momentum_internal = SimpleNamespace(enabled=internal_enabled, organization_slugs=["momentum"])
    app.dependency_overrides[get_config] = lambda: base

    @app.middleware("http")
    async def _stamp(request, call_next):
        request.state.organization_id = organization_id
        request.state.organization_role = role
        return await call_next(request)

    return app


_SLUGS = {"org-momentum": "momentum", "org-client": "acme-co"}


@pytest.mark.parametrize(
    ("role", "organization_id", "internal_enabled", "expected"),
    [
        ("owner", "org-momentum", True, True),
        ("admin", "org-momentum", True, True),
        ("member", "org-momentum", True, True),
        ("client", "org-momentum", True, False),
        (None, None, True, False),
        # The owner of a client workspace on the same instance.
        ("owner", "org-client", True, False),
        ("owner", "org-momentum", False, False),
    ],
)
def test_momentum_internal_is_staff_in_the_configured_workspace_only(monkeypatch, role, organization_id, internal_enabled, expected) -> None:
    async def _slug(org_id: str) -> str | None:
        return _SLUGS.get(org_id)

    monkeypatch.setattr("app.gateway.momentum_internal._organization_slug", _slug)
    with TestClient(_app_as(role, organization_id, internal_enabled=internal_enabled)) as client:
        assert client.get("/api/features").json()["momentum_internal"] == {"enabled": expected}
