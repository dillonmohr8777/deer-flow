"""M3 gap: organization isolation for the Lark/Feishu integration router.

``app/gateway/routers/integrations.py`` never accepts an organization or user
id from the request -- every handler resolves the caller's storage principal
via ``get_effective_user_id()`` and every Lark credential/auth-state path is
keyed by that id alone (see the router's module docstring). That makes
isolation a resolution property, not a DB-row filter: there is no request
parameter through which one organization could even name another's bucket.

This proves the property holds end to end through the actual router
functions (not just ``lark_cli``'s path helpers), using two private
organizations' storage principals (``acting_as`` from
``org_isolation_fixtures`` -- no database needed, Lark storage is
filesystem-only):

1. Reading status as org B never surfaces org A's app_id/config.
2. Overwriting credentials as org B ("config/credentials") never touches
   org A's on-disk config -- each organization gets its own directory.
3. Completing org A's OAuth/app-registration flow as org B, even quoting
   org A's real device_code/generation, fails closed: the generation is
   checked against org B's *own* (unstarted) flow-state file, so it raises
   ``LarkFlowSupersededError`` (409) rather than ever reading or mutating
   org A's flow.
4. None of org B's attempts change what org A subsequently sees.

There is no "remove integration" endpoint on this router (grep confirms it),
so that part of the isolation gate does not apply here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as  # noqa: F401

from app.gateway.routers import integrations as integrations_router
from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli
from deerflow.runtime.user_context import get_effective_user_id


def _config(skills_root: Path):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


def _patch_paths(monkeypatch, base_dir: Path) -> None:
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=base_dir))


def _stub_out_the_real_cli(monkeypatch) -> None:
    """Replace the two spots that shell out to the real lark-cli binary.

    Mirrors ``test_set_lark_app_credentials_validates_switches_and_revokes_prior_auth``
    in ``test_lark_cli_integration.py``: validation is a no-op, and "save"
    writes the config.json shape ``read_lark_app_config`` expects, into the
    *caller's own* directory (keyed by the ``user_id`` lark_cli passes in).
    """
    monkeypatch.setattr(lark_cli, "_validate_lark_app_credentials_with_cli", lambda **_kwargs: None)

    def _save(user_id: str, *, app_id: str, app_secret: str, brand: str) -> None:
        config_dir = lark_cli.lark_cli_config_dir(user_id)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            f'{{"apps":[{{"appId":"{app_id}","appSecret":"{app_secret}","brand":"{brand}"}}]}}',
            encoding="utf-8",
        )

    monkeypatch.setattr(lark_cli, "_save_lark_app_config_with_cli", _save)


async def _switch_credentials(app_id: str, app_secret: str, config) -> object:
    body = integrations_router.LarkConfigCredentialsRequest(app_id=app_id, app_secret=app_secret, brand="feishu")
    return await integrations_router.switch_lark_app_credentials(None, body, config)


@pytest.mark.asyncio
async def test_lark_status_read_is_isolated_across_organizations(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    _stub_out_the_real_cli(monkeypatch)

    with acting_as(USER_A, ORG_A):
        result = await _switch_credentials("org-a-app", "org-a-secret", config)
        assert result.status.app_id == "org-a-app"

    # Org B has never configured anything: status must show org A's app_id
    # nowhere, not even a masked hint of it.
    with acting_as(USER_B, ORG_B):
        status = await integrations_router.get_lark_status(None, config)
        assert status.app_configured is False
        assert status.app_id is None


@pytest.mark.asyncio
async def test_lark_config_overwrite_never_touches_another_organization(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    _stub_out_the_real_cli(monkeypatch)

    with acting_as(USER_A, ORG_A):
        await _switch_credentials("org-a-app", "org-a-secret", config)

    # Org B "overwrites" its own credentials -- this must land in B's own
    # bucket, not clobber A's.
    with acting_as(USER_B, ORG_B):
        result = await _switch_credentials("org-b-app", "org-b-secret", config)
        assert result.status.app_id == "org-b-app"

    with acting_as(USER_A, ORG_A):
        still_a = await integrations_router.get_lark_status(None, config)
        assert still_a.app_id == "org-a-app"


@pytest.mark.asyncio
async def test_lark_oauth_completion_denies_cross_organization_generation(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    _stub_out_the_real_cli(monkeypatch)

    with acting_as(USER_A, ORG_A):
        await _switch_credentials("org-a-app", "org-a-secret", config)
        # A real generation from org A's own flow state (as if org A had
        # actually started a config/auth flow).
        storage_principal_a = get_effective_user_id()
        with lark_cli._lark_credential_lock(storage_principal_a):
            real_generation = lark_cli._advance_lark_flow_generation_locked(storage_principal_a)

    # Org B tries to complete org A's flow by quoting A's real generation.
    # Resolution denies this before any file is even opened for A: the
    # generation is checked against B's own (never-advanced) flow-state
    # file, which fails closed with a 409, not by reading/mutating A's data.
    with acting_as(USER_B, ORG_B):
        body = integrations_router.LarkConfigCompleteRequest(
            device_code="stolen-device-code",
            generation=real_generation,
            brand="feishu",
        )
        with pytest.raises(HTTPException) as excinfo:
            await integrations_router.complete_lark_app_config(None, body, config)
        assert excinfo.value.status_code == 409

    # Org A's config is untouched by B's attempt.
    with acting_as(USER_A, ORG_A):
        still_a = await integrations_router.get_lark_status(None, config)
        assert still_a.app_id == "org-a-app"


def test_lark_router_never_accepts_a_caller_supplied_identity() -> None:
    """Pin the resolution-not-filtering isolation boundary documented in the
    router's module docstring: no Lark request model carries a user or
    organization id field an attacker could use to name another org's bucket.
    """
    request_models = [
        integrations_router.LarkAuthStartRequest,
        integrations_router.LarkConfigStartRequest,
        integrations_router.LarkConfigCompleteRequest,
        integrations_router.LarkConfigCredentialsRequest,
        integrations_router.LarkAuthCompleteRequest,
    ]
    forbidden = {"user_id", "organization_id", "owner_user_id", "storage_user_id"}
    for model in request_models:
        fields = set(model.model_fields.keys())
        assert not (fields & forbidden), f"{model.__name__} must not accept an identity field: {fields & forbidden}"
