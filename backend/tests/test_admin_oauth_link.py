"""Admin SSO link routes: ``PUT`` / ``DELETE /api/admin/users/{id}/oauth``.

The fallback for links the sign-in path will not make on its own. Router
functions are called directly with a fake request (the pattern
``test_admin_router.py`` uses), backed by the real ``LocalAuthProvider`` /
``SQLiteUserRepository`` and a real ``AuditEventRepository`` on an
in-memory database.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway.auth import user_provisioning
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from app.gateway.auth_disabled import AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.routers import admin as admin_router
from deerflow.config.auth_config import OIDCProviderConfig
from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

_SUBJECT = "google-subject-1"


@pytest_asyncio.fixture()
async def world(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [UserRow.__table__, OrganizationRow.__table__, OrganizationMemberRow.__table__, InvitationRow.__table__, AuditEventRow.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = LocalAuthProvider(SQLiteUserRepository(session_factory))
    monkeypatch.setattr(admin_router, "get_local_provider", lambda: provider)
    monkeypatch.setattr(user_provisioning, "get_session_factory", lambda: session_factory)
    google = OIDCProviderConfig(display_name="Google", issuer="https://accounts.google.com", client_id="momobot", link_existing_accounts=True)
    app_config = SimpleNamespace(auth=SimpleNamespace(oidc=SimpleNamespace(providers={"google": google})))
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: app_config)
    yield SimpleNamespace(db=session_factory, provider=provider, audit=AuditEventRepository(session_factory), google=google)
    await engine.dispose()


def _request(world, *, system_role: str = "admin", actor_id: str = "admin-1", auth_source: str = AUTH_SOURCE_SESSION):
    return SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id=actor_id, system_role=system_role), auth_source=auth_source),
        app=SimpleNamespace(state=SimpleNamespace(audit_repo=world.audit)),
        client=SimpleNamespace(host="198.51.100.7"),
        headers={"user-agent": "pytest"},
    )


async def _account(world, email: str = "member@example.com", *, password: bool = True, **fields):
    user = await world.provider.create_user(email=email, password="correct horse battery staple" if password else None)
    if fields:
        async with world.db() as session:
            await session.execute(update(UserRow).where(UserRow.id == str(user.id)).values(**fields))
            await session.commit()
    return await world.provider.get_user(str(user.id))


def _link_body(subject: str = _SUBJECT, provider: str = "google"):
    return admin_router.SetUserOAuthRequest(provider=provider, subject=subject)


async def _events(world):
    events, _ = await world.audit.list(organization_id=None, action_prefix="admin.user.oauth", limit=50)
    return events


# ── permission checks ───────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["user", "exec", "client"])
async def test_link_requires_admin(world, role):
    target = await _account(world)
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world, system_role=role))
    assert exc_info.value.status_code == 403
    assert (await world.provider.get_user(str(target.id))).oauth_id is None
    assert await _events(world) == []


@pytest.mark.parametrize("role", ["user", "exec", "client"])
async def test_unlink_requires_admin(world, role):
    target = await _account(world, oauth_provider="google", oauth_id=_SUBJECT)
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.unlink_user_oauth(str(target.id), _request(world, system_role=role))
    assert exc_info.value.status_code == 403
    assert (await world.provider.get_user(str(target.id))).oauth_id == _SUBJECT


async def test_link_refuses_a_personal_access_token(world):
    target = await _account(world)
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world, auth_source=AUTH_SOURCE_PAT))
    assert exc_info.value.status_code == 403
    assert (await world.provider.get_user(str(target.id))).oauth_id is None


async def test_admin_cannot_change_their_own_link(world):
    admin = await _account(world, "admin@example.com", oauth_provider="google", oauth_id="admin-subject")
    request = _request(world, actor_id=str(admin.id))
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.unlink_user_oauth(str(admin.id), request)
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(admin.id), _link_body(), request)
    assert exc_info.value.status_code == 400
    assert (await world.provider.get_user(str(admin.id))).oauth_id == "admin-subject"


async def test_link_refuses_an_unconfigured_provider(world):
    target = await _account(world)
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(target.id), _link_body(provider="github"), _request(world))
    assert exc_info.value.status_code == 400


async def test_link_body_rejects_blank_or_spaced_subjects():
    for subject in ("", " padded ", "with space"):
        with pytest.raises(ValidationError):
            admin_router.SetUserOAuthRequest(provider="google", subject=subject)
    with pytest.raises(ValidationError):
        admin_router.SetUserOAuthRequest(provider="google", subject=_SUBJECT, extra="field")


async def test_unknown_user_is_404(world):
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth("missing", _link_body(), _request(world))
    assert exc_info.value.status_code == 404


# ── link ────────────────────────────────────────────────────────────────


async def test_link_attaches_the_identity_and_the_next_sign_in_uses_it(world):
    target = await _account(world)

    response = await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world))

    assert response.oauth_provider == "google" and response.has_password is True
    assert response.token_version == target.token_version  # a fresh link ends no sessions
    (event,) = await _events(world)
    assert event["action"] == "admin.user.oauth_linked" and event["actor_user_id"] == "admin-1"
    assert event["target_id"] == str(target.id)
    assert event["details"] == {"provider": "google", "subject": _SUBJECT, "replaced_provider": None, "replaced_subject": None, "sessions_revoked": False}

    identity = OIDCIdentity(provider="google", subject=_SUBJECT, email="different@example.com", email_verified=True, name=None, claims={})
    result = await get_or_provision_oidc_user("google", world.google, identity, world.provider)
    assert str(result["user"].id) == str(target.id)


async def test_relinking_the_same_identity_is_a_no_op(world):
    target = await _account(world, oauth_provider="google", oauth_id=_SUBJECT)
    response = await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world))
    assert response.token_version == target.token_version
    assert await _events(world) == []


async def test_replacing_an_identity_ends_existing_sessions(world):
    target = await _account(world, oauth_provider="google", oauth_id="old-subject")

    response = await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world))

    assert response.token_version == target.token_version + 1
    stored = await world.provider.get_user(str(target.id))
    assert stored.oauth_id == _SUBJECT
    (event,) = await _events(world)
    assert event["details"] == {"provider": "google", "subject": _SUBJECT, "replaced_provider": "google", "replaced_subject": "old-subject", "sessions_revoked": True}


async def test_link_refuses_an_identity_another_account_holds(world):
    holder = await _account(world, "holder@example.com", oauth_provider="google", oauth_id=_SUBJECT)
    target = await _account(world)

    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world))

    assert exc_info.value.status_code == 409
    assert (await world.provider.get_user(str(target.id))).oauth_id is None
    assert (await world.provider.get_user(str(holder.id))).oauth_id == _SUBJECT
    assert await _events(world) == []


async def test_link_never_overwrites_a_sign_in_that_linked_meanwhile(world, monkeypatch):
    target = await _account(world)
    real_lookup = world.provider.get_user_by_oauth

    async def sign_in_links_meanwhile(provider, oauth_id):
        holder = await real_lookup(provider, oauth_id)
        # Between the admin's read and write, the person's own sign-in links sub A.
        await world.provider.link_oauth_identity_if_unlinked(str(target.id), "google", "subject-from-sign-in")
        return holder

    monkeypatch.setattr(world.provider, "get_user_by_oauth", sign_in_links_meanwhile)

    with pytest.raises(HTTPException) as exc_info:
        await admin_router.link_user_oauth(str(target.id), _link_body(), _request(world))

    assert exc_info.value.status_code == 409
    assert (await world.provider.get_user(str(target.id))).oauth_id == "subject-from-sign-in"
    assert await _events(world) == []


# ── unlink ──────────────────────────────────────────────────────────────


async def test_unlink_clears_the_identity_ends_sessions_and_audits(world):
    target = await _account(world, oauth_provider="google", oauth_id=_SUBJECT)

    response = await admin_router.unlink_user_oauth(str(target.id), _request(world))

    assert response.oauth_provider is None and response.token_version == target.token_version + 1
    stored = await world.provider.get_user(str(target.id))
    assert stored.oauth_provider is None and stored.oauth_id is None
    (event,) = await _events(world)
    assert event["action"] == "admin.user.oauth_unlinked" and event["target_id"] == str(target.id)
    assert event["details"] == {"provider": "google", "subject": _SUBJECT, "sessions_revoked": True}


async def test_unlink_without_a_link_is_409(world):
    target = await _account(world)
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.unlink_user_oauth(str(target.id), _request(world))
    assert exc_info.value.status_code == 409
    assert await _events(world) == []


async def test_unlink_then_sign_in_relinks_a_new_identity(world):
    # The relink path for a person whose Google account changed: unlink, then
    # their next verified sign-in links the new identity.
    target = await _account(world, password=False, oauth_provider="google", oauth_id="old-subject")
    unlinked = await admin_router.unlink_user_oauth(str(target.id), _request(world))
    assert unlinked.has_password is False

    async def no_mfa(user_id: str) -> bool:
        return False

    identity = OIDCIdentity(provider="google", subject="new-subject", email="member@example.com", email_verified=True, name=None, claims={})
    result = await get_or_provision_oidc_user("google", world.google, identity, world.provider, local_registration_open=lambda: False, mfa_enabled=no_mfa)

    assert result["linked"] is True and str(result["user"].id) == str(target.id)
    assert (await world.provider.get_user(str(target.id))).oauth_id == "new-subject"
