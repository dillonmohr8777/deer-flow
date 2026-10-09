"""Invite-gated SSO auto-create (``auto_create_requires_invitation``).

With the flag on, a first SSO login may create an account only for a verified
email that holds a pending workspace invitation: not consumed, not expired, in
an active shared workspace, issued by someone who is still an active owner or
admin there. Anything else gets the same 403 as ``auto_create_users: false``.

Runs the real provisioning function, ``LocalAuthProvider`` and
``SQLiteUserRepository`` against a disposable in-memory database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway.auth import user_provisioning
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from deerflow.config.auth_config import OIDCProviderConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

_WORKSPACE = "workspace-1"
_ISSUER = "owner-1"
_INVITED = "invitee@example.com"


@pytest_asyncio.fixture()
async def db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[UserRow.__table__, OrganizationRow.__table__, OrganizationMemberRow.__table__, InvitationRow.__table__],
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(user_provisioning, "get_session_factory", lambda: session_factory)
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            session.add(OrganizationRow(id=_WORKSPACE, slug="momentum", name="Momentum", status="active", storage_user_id="storage-owner", created_at=now, updated_at=now))
            session.add(OrganizationMemberRow(organization_id=_WORKSPACE, user_id=_ISSUER, role="owner", status="active", created_at=now, updated_at=now))
    yield session_factory
    await engine.dispose()


async def _invite(session_factory, email: str = _INVITED, *, invitation_id: str = "invite-1") -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            session.add(
                InvitationRow(
                    id=invitation_id,
                    token_hash=f"digest-{invitation_id}",
                    organization_id=_WORKSPACE,
                    email=email,
                    role="member",
                    created_by=_ISSUER,
                    expires_at=now + timedelta(hours=48),
                    created_at=now,
                    updated_at=now,
                )
            )


def _config(**overrides) -> OIDCProviderConfig:
    return OIDCProviderConfig(display_name="Google", issuer="https://accounts.google.com", client_id="momobot", **overrides)


def _identity(email: str = _INVITED, *, subject: str = "google-subject-1", email_verified: bool = True) -> OIDCIdentity:
    return OIDCIdentity(provider="google", subject=subject, email=email, email_verified=email_verified, name="Jesse", claims={})


def _provider(session_factory) -> LocalAuthProvider:
    return LocalAuthProvider(SQLiteUserRepository(session_factory))


async def _user_count(session_factory) -> int:
    async with session_factory() as session:
        return len((await session.scalars(select(UserRow.id))).all())


async def _auto_create_disabled_error(session_factory) -> HTTPException:
    """The refusal ``auto_create_users: false`` gives, to compare against."""
    with pytest.raises(HTTPException) as disabled:
        await get_or_provision_oidc_user("google", _config(auto_create_users=False), _identity("nobody@example.com", subject="nobody"), _provider(session_factory))
    return disabled.value


def test_flag_defaults_off():
    assert _config().auto_create_requires_invitation is False


@pytest.mark.asyncio
async def test_invited_email_is_created(db):
    await _invite(db)
    result = await get_or_provision_oidc_user("google", _config(auto_create_requires_invitation=True), _identity(), _provider(db))
    assert result["created"] is True
    assert result["user"].email == _INVITED and result["user"].oauth_provider == "google"
    assert await _user_count(db) == 1


@pytest.mark.asyncio
async def test_invitation_email_matches_case_insensitively(db):
    await _invite(db, "Invitee@Example.COM")
    result = await get_or_provision_oidc_user("google", _config(auto_create_requires_invitation=True), _identity("INVITEE@example.com"), _provider(db))
    assert result["created"] is True
    assert result["user"].email == _INVITED


@pytest.mark.asyncio
async def test_uninvited_email_gets_the_auto_create_disabled_403(db):
    await _invite(db)  # someone else's invitation does not help
    expected = await _auto_create_disabled_error(db)
    with pytest.raises(HTTPException) as refused:
        await get_or_provision_oidc_user("google", _config(auto_create_requires_invitation=True), _identity("stranger@example.com"), _provider(db))
    assert refused.value.status_code == 403
    assert (refused.value.status_code, refused.value.detail) == (expected.status_code, expected.detail)
    assert await _user_count(db) == 0


async def _expire(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(InvitationRow).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))


async def _consume(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(InvitationRow).values(consumed_at=datetime.now(UTC)))


async def _revoke_issuer(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == _ISSUER).values(status="revoked"))


async def _demote_issuer(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == _ISSUER).values(role="member"))


async def _deactivate_workspace(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(update(OrganizationRow).where(OrganizationRow.id == _WORKSPACE).values(status="archived"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spoil",
    [_expire, _consume, _revoke_issuer, _demote_issuer, _deactivate_workspace],
    ids=["expired", "consumed", "issuer-revoked", "issuer-demoted-to-member", "workspace-inactive"],
)
async def test_an_invitation_that_is_no_longer_pending_does_not_count(db, spoil):
    await _invite(db)
    await spoil(db)
    expected = await _auto_create_disabled_error(db)
    with pytest.raises(HTTPException) as refused:
        await get_or_provision_oidc_user("google", _config(auto_create_requires_invitation=True), _identity(), _provider(db))
    assert (refused.value.status_code, refused.value.detail) == (expected.status_code, expected.detail)
    assert await _user_count(db) == 0


@pytest.mark.asyncio
async def test_an_unverified_email_never_matches_an_invitation(db):
    """Even where require_verified_email is relaxed, an invitation is matched
    only against an email the provider verified."""
    await _invite(db)
    with pytest.raises(HTTPException) as refused:
        await get_or_provision_oidc_user(
            "google",
            _config(auto_create_requires_invitation=True, require_verified_email=False),
            _identity(email_verified=False),
            _provider(db),
        )
    assert refused.value.status_code == 403
    assert await _user_count(db) == 0


@pytest.mark.asyncio
async def test_no_database_fails_closed(db, monkeypatch):
    await _invite(db)
    monkeypatch.setattr(user_provisioning, "get_session_factory", lambda: None)
    with pytest.raises(HTTPException) as refused:
        await get_or_provision_oidc_user("google", _config(auto_create_requires_invitation=True), _identity(), _provider(db))
    assert refused.value.status_code == 403
    assert await _user_count(db) == 0


@pytest.mark.asyncio
async def test_flag_off_keeps_open_auto_create(db):
    result = await get_or_provision_oidc_user("google", _config(), _identity("stranger@example.com"), _provider(db))
    assert result["created"] is True
    assert result["user"].email == "stranger@example.com"


@pytest.mark.asyncio
async def test_an_account_it_created_keeps_signing_in_after_the_invitation_is_used(db):
    """The gate is for creating accounts only. Once the invitee has accepted
    (invitation consumed), their linked SSO identity still signs in."""
    await _invite(db)
    config = _config(auto_create_requires_invitation=True)
    first = await get_or_provision_oidc_user("google", config, _identity(), _provider(db))
    await _consume(db)
    again = await get_or_provision_oidc_user("google", config, _identity(), _provider(db))
    assert again["created"] is False
    assert str(again["user"].id) == str(first["user"].id)
