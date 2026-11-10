"""Linking an SSO identity onto an existing local account (``link_existing_accounts``).

A first SSO login whose provider-verified email matches exactly one active
local account with no SSO identity, no two-factor authentication, on a
deployment without open self-registration, links to that account and signs
into it. Every other case keeps the 409 the login always got.

Runs the real provisioning function, ``LocalAuthProvider`` and
``SQLiteUserRepository`` against a disposable in-memory database; the
callback tests run the real OAuth callback with only the provider network
calls stubbed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.gateway.auth import user_provisioning
from app.gateway.auth.config import AuthConfig
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.user_provisioning import ExistingAccountConflict, get_or_provision_oidc_user
from app.gateway.routers import auth as auth_router
from deerflow.config.auth_config import OIDCProviderConfig
from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user_mfa import UserMfaRepository, UserMfaRow

pytestmark = pytest.mark.asyncio

_EMAIL = "member@example.com"
_SUBJECT = "google-subject-1"


@pytest_asyncio.fixture()
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [UserRow.__table__, OrganizationRow.__table__, OrganizationMemberRow.__table__, InvitationRow.__table__, AuditEventRow.__table__, UserMfaRow.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(user_provisioning, "get_session_factory", lambda: session_factory)
    yield session_factory
    await engine.dispose()


def _config(**overrides) -> OIDCProviderConfig:
    values = {"link_existing_accounts": True, "auto_create_requires_invitation": True}
    values.update(overrides)
    return OIDCProviderConfig(display_name="Google", issuer="https://accounts.google.com", client_id="momobot", **values)


def _identity(email: str = _EMAIL, *, subject: str = _SUBJECT, email_verified: bool = True) -> OIDCIdentity:
    return OIDCIdentity(provider="google", subject=subject, email=email, email_verified=email_verified, name="Member", claims={})


def _provider(session_factory) -> LocalAuthProvider:
    return LocalAuthProvider(SQLiteUserRepository(session_factory))


def _registration_closed() -> bool:
    return False


def _registration_open() -> bool:
    return True


async def _no_mfa(user_id: str) -> bool:
    return False


async def _password_account(session_factory, email: str = _EMAIL, **fields):
    user = await _provider(session_factory).create_user(email=email, password="correct horse battery staple")
    if fields:
        async with session_factory() as session:
            await session.execute(update(UserRow).where(UserRow.id == str(user.id)).values(**fields))
            await session.commit()
    return user


async def _row(session_factory, user_id) -> UserRow:
    async with session_factory() as session:
        return await session.get(UserRow, str(user_id))


async def _user_count(session_factory) -> int:
    async with session_factory() as session:
        return len((await session.scalars(select(UserRow.id))).all())


async def _provision(session_factory, *, config=None, identity=None, registration=_registration_closed, mfa=_no_mfa):
    return await get_or_provision_oidc_user(
        "google",
        config or _config(),
        identity or _identity(),
        _provider(session_factory),
        local_registration_open=registration,
        mfa_enabled=mfa,
    )


async def _refusal(session_factory, **kwargs) -> ExistingAccountConflict:
    with pytest.raises(ExistingAccountConflict) as exc_info:
        await _provision(session_factory, **kwargs)
    assert exc_info.value.status_code == 409
    # The public message is identical for every refusal, so a login cannot
    # probe why an account would not link.
    assert exc_info.value.detail == "An account with this email already exists. Contact your administrator to link it to your SSO account."
    return exc_info.value


async def test_flag_defaults_off():
    assert OIDCProviderConfig(display_name="G", issuer="https://accounts.google.com", client_id="c").link_existing_accounts is False


# ── happy path ──────────────────────────────────────────────────────────


async def test_verified_email_links_the_one_matching_password_account(db):
    account = await _password_account(db)
    before = await _row(db, account.id)

    result = await _provision(db)

    assert result["created"] is False and result["linked"] is True
    assert str(result["user"].id) == str(account.id)
    row = await _row(db, account.id)
    assert (row.oauth_provider, row.oauth_id) == ("google", _SUBJECT)
    # The password keeps working and existing sessions are not ended.
    assert row.password_hash == before.password_hash
    assert row.token_version == before.token_version
    assert await _user_count(db) == 1

    # The next sign-in resolves by the linked identity, not by email.
    again = await _provision(db, config=_config(link_existing_accounts=False))
    assert str(again["user"].id) == str(account.id)
    assert again == {"user": again["user"], "created": False}


async def test_linked_account_me_reports_has_password(db, monkeypatch):
    await _password_account(db)
    await _provision(db)
    # Next sign-in resolves the linked account by its identity.
    linked = (await _provision(db, config=_config(link_existing_accounts=False)))["user"]
    assert linked.oauth_provider == "google"

    async def _current_user(request):
        return linked

    monkeypatch.setattr(auth_router, "get_current_user_from_request", _current_user)
    request = SimpleNamespace(state=SimpleNamespace(auth=SimpleNamespace(permissions=[])), app=SimpleNamespace(state=SimpleNamespace(mfa_repo=None)))

    me = await auth_router.get_me(request)

    assert me.oauth_provider == "google"
    assert me.has_password is True


async def test_link_matches_the_email_case_insensitively(db):
    account = await _password_account(db)
    result = await _provision(db, identity=_identity("Member@Example.COM"))
    assert str(result["user"].id) == str(account.id)
    assert (await _row(db, account.id)).oauth_id == _SUBJECT


# ── every refusal keeps the account untouched ───────────────────────────


async def _assert_unlinked(session_factory, user_id) -> None:
    row = await _row(session_factory, user_id)
    assert row.oauth_provider is None and row.oauth_id is None


async def test_unverified_email_is_refused(db):
    account = await _password_account(db)
    refusal = await _refusal(db, config=_config(require_verified_email=False), identity=_identity(email_verified=False))
    assert refusal.reason == "email_unverified" and refusal.user_id == str(account.id)
    await _assert_unlinked(db, account.id)


async def test_unverified_email_is_refused_before_any_lookup_by_default(db):
    account = await _password_account(db)
    with pytest.raises(HTTPException) as exc_info:
        await _provision(db, identity=_identity(email_verified=False))
    assert exc_info.value.status_code == 403
    await _assert_unlinked(db, account.id)


async def test_account_linked_to_a_different_subject_is_refused(db):
    account = await _password_account(db, oauth_provider="google", oauth_id="someone-else")
    refusal = await _refusal(db)
    assert refusal.reason == "already_linked"
    row = await _row(db, account.id)
    assert row.oauth_id == "someone-else"


async def test_account_linked_to_another_provider_is_refused(db):
    account = await _password_account(db, oauth_provider="keycloak", oauth_id="kc-subject")
    assert (await _refusal(db)).reason == "already_linked"
    row = await _row(db, account.id)
    assert (row.oauth_provider, row.oauth_id) == ("keycloak", "kc-subject")


async def test_disabled_account_is_refused(db):
    account = await _password_account(db, disabled_at=datetime.now(UTC))
    assert (await _refusal(db)).reason == "disabled"
    await _assert_unlinked(db, account.id)


async def test_more_than_one_matching_account_is_refused(db):
    # A pre-normalisation database can hold two rows differing only in case;
    # create_user refuses that now, so insert the legacy row directly.
    account = await _password_account(db)
    async with db() as session:
        session.add(UserRow(id=str(uuid4()), email="Member@example.com", password_hash=None, system_role="user", created_at=datetime.now(UTC)))
        await session.commit()

    assert (await _refusal(db)).reason == "multiple_accounts"
    await _assert_unlinked(db, account.id)
    async with db() as session:
        assert (await session.scalars(select(UserRow.id).where(UserRow.oauth_id.is_not(None)))).all() == []


async def test_account_with_two_factor_enabled_is_refused(db):
    account = await _password_account(db)
    checked: list[str] = []

    async def mfa_on(user_id: str) -> bool:
        checked.append(user_id)
        return True

    assert (await _refusal(db, mfa=mfa_on)).reason == "mfa_enabled"
    assert checked == [str(account.id)]
    await _assert_unlinked(db, account.id)


async def test_linking_off_keeps_the_existing_refusal(db):
    account = await _password_account(db)
    assert (await _refusal(db, config=_config(link_existing_accounts=False))).reason == "linking_off"
    await _assert_unlinked(db, account.id)


async def test_open_self_registration_refuses_the_link(db):
    # A self-registered account never proved it owns its email: linking the
    # real owner's Google identity onto it would share the account with
    # whoever registered it.
    account = await _password_account(db)
    assert (await _refusal(db, registration=_registration_open)).reason == "self_registration_open"
    await _assert_unlinked(db, account.id)


async def test_callers_that_pass_no_link_checks_never_link(db):
    account = await _password_account(db)
    with pytest.raises(ExistingAccountConflict) as exc_info:
        await get_or_provision_oidc_user("google", _config(), _identity(), _provider(db))
    assert exc_info.value.reason == "self_registration_open"
    with pytest.raises(ExistingAccountConflict) as exc_info:
        await get_or_provision_oidc_user("google", _config(), _identity(), _provider(db), local_registration_open=_registration_closed)
    assert exc_info.value.reason == "mfa_enabled"
    await _assert_unlinked(db, account.id)


async def test_non_ascii_email_that_folds_onto_an_account_is_refused(db):
    account = await _password_account(db, email="kim@example.com")
    # U+212A KELVIN SIGN lowercases to ASCII "k".
    assert (await _refusal(db, identity=_identity("\u212aim@example.com"))).reason == "non_ascii_email"
    await _assert_unlinked(db, account.id)


async def test_account_that_changes_after_the_checks_is_not_overwritten(db):
    account = await _password_account(db)

    async def link_elsewhere_meanwhile(user_id: str) -> bool:
        async with db() as session:
            await session.execute(update(UserRow).where(UserRow.id == user_id).values(oauth_provider="google", oauth_id="raced-subject"))
            await session.commit()
        return False

    assert (await _refusal(db, mfa=link_elsewhere_meanwhile)).reason == "account_changed"
    assert (await _row(db, account.id)).oauth_id == "raced-subject"


async def test_account_disabled_after_the_checks_is_not_linked(db):
    account = await _password_account(db)

    async def disable_meanwhile(user_id: str) -> bool:
        async with db() as session:
            await session.execute(update(UserRow).where(UserRow.id == user_id).values(disabled_at=datetime.now(UTC)))
            await session.commit()
        return False

    assert (await _refusal(db, mfa=disable_meanwhile)).reason == "account_changed"
    await _assert_unlinked(db, account.id)


async def test_identity_linked_to_another_account_meanwhile_is_refused(db):
    account = await _password_account(db)
    other = await _password_account(db, email="other@example.com")

    async def same_identity_lands_elsewhere(user_id: str) -> bool:
        async with db() as session:
            await session.execute(update(UserRow).where(UserRow.id == str(other.id)).values(oauth_provider="google", oauth_id=_SUBJECT))
            await session.commit()
        return False

    assert (await _refusal(db, mfa=same_identity_lands_elsewhere)).reason == "identity_linked_elsewhere"
    await _assert_unlinked(db, account.id)


async def test_linked_account_cannot_enroll_app_level_mfa_afterwards(db):
    # Linking keeps the password, but SSO sign-ins skip TOTP, so enabling MFA
    # after the link would be bypassed by every later Google login.
    account = await _password_account(db)
    linked = (await _provision(db))["user"]
    assert linked.password_hash is not None

    with pytest.raises(HTTPException) as exc_info:
        auth_router._refuse_sso_mfa(await _provider(db).get_user(str(account.id)))
    assert exc_info.value.status_code == 400

    # An unlinked password account can still enroll.
    other = await _password_account(db, email="other@example.com")
    auth_router._refuse_sso_mfa(await _provider(db).get_user(str(other.id)))


# ── repository ──────────────────────────────────────────────────────────


async def test_link_returns_the_snapshot_taken_with_the_update(db):
    account = await _password_account(db)

    def racing_session_factory():
        session = db()
        real_commit = session.commit

        async def commit_then_admin_replaces_identity():
            await real_commit()
            async with db() as other:
                await other.execute(update(UserRow).where(UserRow.id == str(account.id)).values(oauth_provider="google", oauth_id="replacement", token_version=UserRow.token_version + 1))
                await other.commit()

        session.commit = commit_then_admin_replaces_identity
        return session

    linked = await SQLiteUserRepository(racing_session_factory).link_oauth_identity_if_unlinked(str(account.id), "google", _SUBJECT)

    # The callback sees the state its own link produced, not the replacement's
    # bumped token_version / identity, so it cannot mint a session that
    # outlives the replacement's revocation.
    assert linked.oauth_id == _SUBJECT and linked.token_version == 0
    row = await _row(db, account.id)
    assert row.oauth_id == "replacement" and row.token_version == 1


async def test_count_users_by_email_is_case_insensitive(db):
    await _password_account(db)
    repo = SQLiteUserRepository(db)
    assert await repo.count_users_by_email("MEMBER@example.com") == 1
    assert await repo.count_users_by_email("nobody@example.com") == 0


async def test_set_oauth_identity_refuses_an_identity_held_elsewhere_and_bumps_sessions(db):
    account = await _password_account(db)
    other = await _password_account(db, email="other@example.com", oauth_provider="google", oauth_id=_SUBJECT)
    repo = SQLiteUserRepository(db)

    with pytest.raises(ValueError):
        await repo.set_oauth_identity(str(account.id), "google", _SUBJECT, expected_provider=None, expected_oauth_id=None, revoke_sessions=False)
    await _assert_unlinked(db, account.id)

    cleared = await repo.set_oauth_identity(str(other.id), None, None, expected_provider="google", expected_oauth_id=_SUBJECT, revoke_sessions=True)
    assert cleared.oauth_provider is None and cleared.token_version == 1
    with pytest.raises(ValueError):
        await repo.set_oauth_identity(str(other.id), "google", None, expected_provider=None, expected_oauth_id=None, revoke_sessions=False)


async def test_set_oauth_identity_is_compare_and_set(db):
    account = await _password_account(db, oauth_provider="google", oauth_id="current-subject")
    repo = SQLiteUserRepository(db)

    # The caller read a stale identity: nothing is written, sessions are untouched.
    assert await repo.set_oauth_identity(str(account.id), "google", "new-subject", expected_provider=None, expected_oauth_id=None, revoke_sessions=True) is None
    row = await _row(db, account.id)
    assert row.oauth_id == "current-subject" and row.token_version == 0
    assert await repo.set_oauth_identity(str(uuid4()), None, None, expected_provider=None, expected_oauth_id=None, revoke_sessions=True) is None

    updated = await repo.set_oauth_identity(str(account.id), "google", "new-subject", expected_provider="google", expected_oauth_id="current-subject", revoke_sessions=True)
    assert updated.oauth_id == "new-subject" and updated.token_version == 1


# ── the OAuth callback audits every link and refusal ────────────────────


def _callback_request(audit_repo, mfa_repo) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(audit_repo=audit_repo, mfa_repo=mfa_repo))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/callback/google",
            "headers": [(b"host", b"momobot.example"), (b"x-forwarded-proto", b"https"), (b"user-agent", b"pytest")],
            "query_string": b"",
            "scheme": "https",
            "server": ("momobot.example", 443),
            "client": ("203.0.113.9", 4321),
            "app": app,
        }
    )


@pytest.fixture()
def callback_world(db, monkeypatch):
    provider_config = _config()
    app_config = SimpleNamespace(
        auth=SimpleNamespace(
            local=SimpleNamespace(allow_registration=False),
            oidc=SimpleNamespace(enabled=True, frontend_base_url="https://momobot.example", providers={"google": provider_config}),
        )
    )
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: app_config)
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="oidc-link-existing-account-test-secret"))
    monkeypatch.setattr(auth_router, "get_state_cookie", lambda request, provider_id: SimpleNamespace(state="s", code_verifier="v", nonce="n", next_path="/workspace", remember_me=False))
    monkeypatch.setattr(auth_router, "_resolve_oidc_redirect_uri", lambda *args: "https://momobot.example/api/v1/auth/callback/google")
    monkeypatch.setattr(auth_router, "_get_oidc_service", lambda: SimpleNamespace(discover=AsyncMock(return_value={}), authenticate_callback=AsyncMock(return_value=_identity())))
    monkeypatch.setattr(auth_router, "get_local_provider", lambda: _provider(db))
    return SimpleNamespace(db=db, app_config=app_config, audit=AuditEventRepository(db), mfa=UserMfaRepository(db))


async def _events(audit_repo):
    events, _ = await audit_repo.list(organization_id=None, action_prefix="auth.oauth.", actor_user_id=None, since=None, until=None, limit=50, cursor=None)
    return events


async def test_callback_signs_into_the_linked_account_and_audits_the_link(callback_world):
    account = await _password_account(callback_world.db)

    response = await auth_router.oauth_callback(_callback_request(callback_world.audit, callback_world.mfa), "google", code="c", state="s")

    assert "/auth/callback?next=" in response.headers["location"]
    cookies = [value.decode() for key, value in response.raw_headers if key == b"set-cookie"]
    assert any(cookie.startswith("access_token=") for cookie in cookies)
    (event,) = await _events(callback_world.audit)
    assert event["action"] == "auth.oauth.linked" and event["outcome"] == "success"
    assert event["target_id"] == str(account.id) and event["actor_user_id"] == str(account.id)
    assert event["details"] == {"provider": "google", "subject": _SUBJECT, "via": "verified_email"}
    assert event["ip"] == "203.0.113.9"


async def test_callback_refusal_redirects_with_the_existing_error_and_audits_the_reason(callback_world):
    account = await _password_account(callback_world.db)
    await callback_world.mfa.start_enrollment(str(account.id), "encrypted-secret")
    await callback_world.mfa.confirm_enrollment(str(account.id), [])

    response = await auth_router.oauth_callback(_callback_request(callback_world.audit, callback_world.mfa), "google", code="c", state="s")

    assert response.headers["location"] == "https://momobot.example/login?error=sso_account_exists"
    cookies = [value.decode() for key, value in response.raw_headers if key == b"set-cookie"]
    assert not any(cookie.startswith("access_token=") for cookie in cookies)
    (event,) = await _events(callback_world.audit)
    assert event["action"] == "auth.oauth.link_refused" and event["outcome"] == "denied"
    assert event["target_id"] == str(account.id) and event["actor_user_id"] is None
    assert event["details"] == {"provider": "google", "reason": "mfa_enabled", "subject": _SUBJECT}
    await _assert_unlinked(callback_world.db, account.id)


async def test_callback_reads_the_deployment_registration_setting(callback_world):
    account = await _password_account(callback_world.db)
    callback_world.app_config.auth.local.allow_registration = True

    response = await auth_router.oauth_callback(_callback_request(callback_world.audit, callback_world.mfa), "google", code="c", state="s")

    assert response.headers["location"].endswith("/login?error=sso_account_exists")
    (event,) = await _events(callback_world.audit)
    assert event["details"]["reason"] == "self_registration_open"
    await _assert_unlinked(callback_world.db, account.id)
