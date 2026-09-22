"""Focused regressions for shared-workspace identity propagation."""

from __future__ import annotations

from types import SimpleNamespace

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.services import inject_authenticated_user_context
from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    WorkspaceStorageContext,
    get_effective_actor_user_id,
    get_effective_user_id,
    get_workspace_actor_user_id,
    reset_current_user,
    reset_storage_context,
    resolve_config_user_id,
    resolve_user_id,
    set_current_user,
    set_storage_context,
    AUTO,
)


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            auth_source=AUTH_SOURCE_SESSION,
            user=SimpleNamespace(id="actor-1", system_role="user", oauth_provider=None, oauth_id=None),
            actor_user_id="actor-1",
            storage_user_id="momentum-storage",
            organization_id="momentum-workspace",
            organization_role="admin",
        )
    )


def test_authenticated_workspace_identity_replaces_forged_context_and_survives_worker_boundary():
    config = {
        "context": {
            "user_id": "forged-user",
            "actor_user_id": "forged-actor",
            "storage_user_id": "forged-storage",
            "organization_id": "forged-workspace",
            "organization_role": "owner",
        },
        "configurable": {
            "actor_user_id": "forged-actor",
            "storage_user_id": "forged-storage",
        },
    }

    inject_authenticated_user_context(config, _request())

    assert config["context"]["user_id"] == "actor-1"
    assert config["context"]["actor_user_id"] == "actor-1"
    assert config["context"]["storage_user_id"] == "momentum-storage"
    assert config["context"]["organization_id"] == "momentum-workspace"
    assert config["context"]["organization_role"] == "admin"
    assert "storage_user_id" not in config["configurable"]
    assert "actor_user_id" not in config["configurable"]

    runtime_context = _build_runtime_context("thread-1", "run-1", config["context"])
    assert runtime_context["storage_user_id"] == "momentum-storage"
    assert runtime_context["actor_user_id"] == "actor-1"
    assert runtime_context["organization_id"] == "momentum-workspace"
    assert runtime_context["organization_role"] == "admin"
    assert "__deerflow_authenticated_context" not in runtime_context


def test_worker_drops_unmarked_workspace_identity_fields():
    runtime_context = _build_runtime_context(
        "thread-1",
        "run-1",
        {
            "storage_user_id": "forged-storage",
            "actor_user_id": "forged-actor",
            "organization_id": "forged-workspace",
        },
    )
    assert "storage_user_id" not in runtime_context
    assert "actor_user_id" not in runtime_context
    assert "organization_id" not in runtime_context


def test_storage_context_keeps_authenticated_actor_separate_from_content_owner():
    actor_token = set_current_user(SimpleNamespace(id="actor-1"))
    storage_token = set_storage_context(
        WorkspaceStorageContext(
            actor_user_id="actor-1",
            organization_id="momentum-workspace",
            storage_user_id="momentum-storage",
            role="admin",
        )
    )
    try:
        assert get_effective_user_id() == "momentum-storage"
        assert resolve_user_id(AUTO) == "momentum-storage"
        assert get_workspace_actor_user_id() == "actor-1"
        assert get_effective_actor_user_id() == "actor-1"
    finally:
        reset_storage_context(storage_token)
        reset_current_user(actor_token)


def test_config_identity_stays_on_storage_principal_after_worker_consumes_marker():
    actor_token = set_current_user(SimpleNamespace(id="actor-1"))
    storage_token = set_storage_context(
        WorkspaceStorageContext(
            actor_user_id="actor-1",
            organization_id="momentum-workspace",
            storage_user_id="momentum-storage",
            role="admin",
        )
    )
    try:
        config = {"context": {}}
        inject_authenticated_user_context(config, _request())
        runtime_context = _build_runtime_context("thread-1", "run-1", config["context"])
        _install_runtime_context(config, runtime_context)
        assert AUTHENTICATED_CONTEXT_MARKER_KEY not in config["context"]
        assert resolve_config_user_id(config) == "momentum-storage"
    finally:
        reset_storage_context(storage_token)
        reset_current_user(actor_token)
