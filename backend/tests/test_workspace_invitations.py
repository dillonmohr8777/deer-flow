"""Security regressions for shared-workspace invitations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from app.gateway import deps
from app.gateway.auth.config import AuthConfig
from app.gateway.auth.jwt import create_access_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.password import hash_password_async
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.gateway.routers import invitations
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow


def _request(*, user=None, source=None, cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    if cookies:
        raw_headers.append((b"cookie", "; ".join(f"{quote(k)}={quote(v)}" for k, v in cookies.items()).encode()))
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode(), value.encode()))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/invitations",
            "headers": raw_headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
            "query_string": b"",
        }
    )
    if user is not None:
        request.state.user = user
    if source is not None:
        request.state.auth_source = source
    return request


# The double-submit pair a browser that went through a normal sign-in holds:
# the JS-readable csrf_token cookie, echoed back in X-CSRF-Token.
_CSRF = "invitation-csrf-double-submit"


def _signed_in(user_id: str, *, csrf_cookie: str | None = _CSRF, csrf_header: str | None = _CSRF) -> Request:
    """A request carrying a verified browser session for ``user_id``."""
    cookies = {CSRF_COOKIE_NAME: csrf_cookie} if csrf_cookie is not None else None
    headers = {CSRF_HEADER_NAME: csrf_header} if csrf_header is not None else None
    return _request(user=SimpleNamespace(id=user_id), source=AUTH_SOURCE_SESSION, cookies=cookies, headers=headers)


@pytest_asyncio.fixture()
async def invitation_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[
                    UserRow.__table__,
                    OrganizationRow.__table__,
                    OrganizationMemberRow.__table__,
                    InvitationRow.__table__,
                ],
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(invitations, "get_session_factory", lambda: session_factory)
    # The freeze (decision 1) has its own test; these exercise the unfrozen flow.
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(invitations_frozen=False))
    monkeypatch.setattr(
        "app.gateway.auth.config._auth_config",
        AuthConfig(jwt_secret="workspace-invitation-test-secret"),
    )
    yield session_factory
    await engine.dispose()


async def _seed_workspace(session_factory, *, owner_id: str = "owner-1") -> str:
    organization_id = "workspace-1"
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            session.add(
                OrganizationRow(
                    id=organization_id,
                    slug="momentum",
                    name="Momentum",
                    status="active",
                    storage_user_id="storage-owner",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                OrganizationMemberRow(
                    organization_id=organization_id,
                    user_id=owner_id,
                    role="owner",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
    return organization_id


async def _create(monkeypatch, session_factory, organization_id: str, *, owner_id: str = "owner-1", email: str = "Jesse@example.com", role: str = "member"):
    actor = SimpleNamespace(id=owner_id)
    monkeypatch.setattr(invitations, "get_current_user_from_request", lambda request: _async_value(actor))
    return await invitations.create_invitation(
        invitations.CreateInvitationRequest(organization_id=organization_id, email=email, role=role),
        _request(user=actor, source=AUTH_SOURCE_SESSION),
        Response(),
    )


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_new_recipient_is_created_and_token_is_single_use(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id)
    assert len(created.token) >= 32
    async with invitation_db() as session:
        stored = await session.get(InvitationRow, created.id)
        assert stored is not None and stored.token_hash != created.token and len(stored.token_hash) == 64

    inspected = await invitations.inspect_invitation(invitations.InvitationTokenRequest(token=created.token), Response())
    assert inspected.email == "jesse@example.com"
    assert inspected.workspace_name == "Momentum"
    assert inspected.requires_login is False

    response = Response()
    accepted = await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token, password="A-longer-new-password!"),
        _request(),
        response,
    )
    assert accepted.workspace_id == organization_id
    assert "access_token=" in response.headers.get("set-cookie", "")
    assert any(key == b"set-cookie" and b"deerflow_workspace=workspace-1" in value for key, value in response.raw_headers)

    async with invitation_db() as session:
        user = await session.scalar(select(UserRow).where(UserRow.email == "jesse@example.com"))
        assert user is not None
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": user.id})
        assert membership is not None and membership.role == "member" and membership.status == "active"
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is not None

    with pytest.raises(Exception) as replay:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token, password="A-longer-new-password!"),
            _request(),
            Response(),
        )
    assert getattr(replay.value, "status_code", None) == 403


def test_create_invitation_request_defaults_role_to_member():
    """Least privilege by default (#audit-admin): admin stays opt-in."""
    request = invitations.CreateInvitationRequest(organization_id="workspace-1", email="new@example.com")
    assert request.role == "member"


@pytest.mark.asyncio
async def test_inviter_can_explicitly_choose_admin_role(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id, email="chosen-admin@example.com", role="admin")

    accepted = await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token, password="A-longer-new-password!"),
        _request(),
        Response(),
    )
    assert accepted.workspace_id == organization_id
    async with invitation_db() as session:
        user = await session.scalar(select(UserRow).where(UserRow.email == "chosen-admin@example.com"))
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": user.id})
        assert membership is not None and membership.role == "admin"


@pytest.mark.asyncio
async def test_member_role_cannot_create_invitation(invitation_db, monkeypatch):
    """Least privilege: a plain "member" (not owner/admin) cannot invite others."""
    organization_id = await _seed_workspace(invitation_db)
    now = datetime.now(UTC)
    async with invitation_db() as session:
        async with session.begin():
            session.add(
                OrganizationMemberRow(
                    organization_id=organization_id,
                    user_id="member-user",
                    role="member",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
    actor = SimpleNamespace(id="member-user")
    monkeypatch.setattr(invitations, "get_current_user_from_request", lambda request: _async_value(actor))
    with pytest.raises(Exception) as unauthorized:
        await invitations.create_invitation(
            invitations.CreateInvitationRequest(organization_id=organization_id, email="blocked@example.com"),
            _request(user=actor, source=AUTH_SOURCE_SESSION),
            Response(),
        )
    assert getattr(unauthorized.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_new_recipient_requires_twelve_char_non_common_password(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id, email="new@example.com")
    with pytest.raises(Exception) as short:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token, password="short"),
            _request(),
            Response(),
        )
    assert getattr(short.value, "status_code", None) == 422
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None


@pytest.mark.asyncio
async def test_existing_password_account_must_sign_in_then_accept(invitation_db, monkeypatch):
    """Sign in, then accept. /accept never takes an existing account's
    password: that would be a login that hands out a session cookie without
    the account's MFA step. Only the account's own verified session accepts.
    """
    organization_id = await _seed_workspace(invitation_db)
    now = datetime.now(UTC)
    password_hash = await hash_password_async("Existing-password-123!")
    async with invitation_db() as session:
        async with session.begin():
            session.add(
                UserRow(
                    id="existing-user",
                    email="existing@example.com",
                    password_hash=password_hash,
                    system_role="user",
                    needs_setup=False,
                    token_version=0,
                    created_at=now,
                )
            )
    created = await _create(monkeypatch, invitation_db, organization_id, email="existing@example.com")

    # No session: refused whether the password is right, wrong or absent,
    # no session cookie is issued, and the token stays usable.
    for password in ("Existing-password-123!", "wrong-password", ""):
        response = Response()
        with pytest.raises(Exception) as refused:
            await invitations.accept_invitation(
                invitations.AcceptInvitationRequest(token=created.token, password=password),
                _request(),
                response,
            )
        assert getattr(refused.value, "status_code", None) == 403, password
        assert "access_token=" not in response.headers.get("set-cookie", "")
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None

    # The same account's own session accepts, with no password in the body.
    accepted = await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token),
        _signed_in("existing-user"),
        Response(),
    )
    assert accepted.workspace_id == organization_id
    async with invitation_db() as session:
        user = await session.get(UserRow, "existing-user")
        assert user is not None and user.password_hash == password_hash
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": "existing-user"})
        assert membership is not None and membership.role == "member" and membership.status == "active"
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is not None


@pytest.mark.asyncio
async def test_expired_invitation_is_forbidden_and_not_consumed(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id, email="expired@example.com")
    async with invitation_db() as session:
        async with session.begin():
            await session.execute(update(InvitationRow).where(InvitationRow.id == created.id).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))

    with pytest.raises(Exception) as expired:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token, password="A-longer-new-password!"),
            _request(),
            Response(),
        )
    assert getattr(expired.value, "status_code", None) == 403
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None


@pytest.mark.asyncio
async def test_non_member_cannot_create_invitation(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    now = datetime.now(UTC)
    async with invitation_db() as session:
        async with session.begin():
            session.add(
                OrganizationMemberRow(
                    organization_id=organization_id,
                    user_id="ordinary-user",
                    role="user",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
    actor = SimpleNamespace(id="ordinary-user")
    monkeypatch.setattr(invitations, "get_current_user_from_request", lambda request: _async_value(actor))
    with pytest.raises(Exception) as unauthorized:
        await invitations.create_invitation(
            invitations.CreateInvitationRequest(organization_id=organization_id, email="blocked@example.com"),
            _request(user=actor, source=AUTH_SOURCE_SESSION),
            Response(),
        )
    assert getattr(unauthorized.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_owner_can_revoke_pending_invitation(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id, email="revoked@example.com")
    actor = SimpleNamespace(id="owner-1")
    monkeypatch.setattr(invitations, "get_current_user_from_request", lambda request: _async_value(actor))
    await invitations.revoke_invitation(created.id, _request(user=actor, source=AUTH_SOURCE_SESSION))
    with pytest.raises(Exception) as revoked:
        await invitations.inspect_invitation(invitations.InvitationTokenRequest(token=created.token), Response())
    assert getattr(revoked.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_revoked_issuer_cannot_consume_pending_invitation(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    created = await _create(monkeypatch, invitation_db, organization_id, email="new@example.com")
    async with invitation_db() as session:
        async with session.begin():
            member = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": "owner-1"})
            assert member is not None
            member.status = "inactive"
    with pytest.raises(Exception) as revoked:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token, password="A-longer-new-password!"),
            _request(),
            Response(),
        )
    assert getattr(revoked.value, "status_code", None) == 403
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None


async def _add_user(session_factory, user_id: str, email: str, *, password: str | None = None, oauth_provider: str | None = None) -> None:
    now = datetime.now(UTC)
    password_hash = await hash_password_async(password) if password else None
    async with session_factory() as session:
        async with session.begin():
            session.add(
                UserRow(
                    id=user_id,
                    email=email,
                    password_hash=password_hash,
                    oauth_provider=oauth_provider,
                    oauth_id=f"{oauth_provider}-{user_id}" if oauth_provider else None,
                    system_role="user",
                    needs_setup=False,
                    token_version=0,
                    created_at=now,
                )
            )


@pytest.mark.asyncio
async def test_inspect_says_only_whether_the_invited_email_has_an_account(invitation_db, monkeypatch):
    """The page needs new vs existing, nothing more. How an existing account
    signs in (password or SSO) is not the token holder's business."""
    assert "sign_in" not in invitations.InspectInvitationResponse.model_fields
    organization_id = await _seed_workspace(invitation_db)
    await _add_user(invitation_db, "pw-user", "pw@example.com", password="Existing-password-123!")
    await _add_user(invitation_db, "sso-user", "sso@example.com", oauth_provider="google")

    expected = {"new@example.com": False, "pw@example.com": True, "sso@example.com": True}
    for email, requires_login in expected.items():
        created = await _create(monkeypatch, invitation_db, organization_id, email=email)
        inspected = await invitations.inspect_invitation(invitations.InvitationTokenRequest(token=created.token), Response())
        assert inspected.requires_login is requires_login, email
        assert set(inspected.model_dump()) == {"email", "workspace_name", "expires_at", "requires_login"}, email


@pytest.mark.asyncio
async def test_sso_account_accepts_with_its_session_and_no_password(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    await _add_user(invitation_db, "sso-user", "sso@example.com", oauth_provider="google")
    created = await _create(monkeypatch, invitation_db, organization_id, email="sso@example.com")

    # Not signed in: refused, whatever password is sent, and nothing is consumed.
    for password in ("", "anything-at-all"):
        with pytest.raises(Exception) as anonymous:
            await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=created.token, password=password), _request(), Response())
        assert getattr(anonymous.value, "status_code", None) == 403

    # Signed in as somebody else: still refused.
    with pytest.raises(Exception) as someone_else:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token),
            _request(user=SimpleNamespace(id="owner-1"), source=AUTH_SOURCE_SESSION),
            Response(),
        )
    assert getattr(someone_else.value, "status_code", None) == 403
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None

    # Signed in as the invited SSO account: no password needed.
    accepted = await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token),
        _signed_in("sso-user"),
        Response(),
    )
    assert accepted.workspace_id == organization_id
    async with invitation_db() as session:
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": "sso-user"})
        assert membership is not None and membership.status == "active"
        user = await session.get(UserRow, "sso-user")
        assert user is not None and user.password_hash is None


@pytest.mark.asyncio
async def test_empty_password_never_creates_or_unlocks_a_password_account(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    await _add_user(invitation_db, "pw-user", "pw@example.com", password="Existing-password-123!")
    fresh = await _create(monkeypatch, invitation_db, organization_id, email="brand-new@example.com")
    existing = await _create(monkeypatch, invitation_db, organization_id, email="pw@example.com")

    with pytest.raises(Exception) as new_account:
        await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=fresh.token), _request(), Response())
    assert getattr(new_account.value, "status_code", None) == 422

    with pytest.raises(Exception) as password_account:
        await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=existing.token), _request(), Response())
    assert getattr(password_account.value, "status_code", None) == 403

    async with invitation_db() as session:
        assert await session.scalar(select(UserRow).where(UserRow.email == "brand-new@example.com")) is None
        for invitation_id in (fresh.id, existing.id):
            invitation = await session.get(InvitationRow, invitation_id)
            assert invitation is not None and invitation.consumed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("csrf_cookie", "csrf_header"),
    [(_CSRF, "a-different-value"), (_CSRF, None), (None, _CSRF), (None, None)],
    ids=["mismatch", "header-missing", "cookie-missing", "both-missing"],
)
async def test_session_accept_refuses_a_missing_or_mismatched_csrf_pair(invitation_db, monkeypatch, csrf_cookie, csrf_header):
    """/accept stays CSRF-exempt at the middleware so a brand-new recipient
    (no session yet, so no csrf cookie) can accept. Accepting through an
    existing session rides ambient cookies, so the handler itself requires
    the double-submit pair, before anything is consumed."""
    organization_id = await _seed_workspace(invitation_db)
    await _add_user(invitation_db, "pw-user", "pw@example.com", password="Existing-password-123!")
    created = await _create(monkeypatch, invitation_db, organization_id, email="pw@example.com")

    with pytest.raises(Exception) as refused:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token),
            _signed_in("pw-user", csrf_cookie=csrf_cookie, csrf_header=csrf_header),
            Response(),
        )
    assert getattr(refused.value, "status_code", None) == 403
    assert "CSRF" in str(getattr(refused.value, "detail", ""))
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None
        assert await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": "pw-user"}) is None


@pytest.mark.asyncio
async def test_session_accept_with_a_matching_csrf_pair_joins_the_workspace(invitation_db, monkeypatch):
    organization_id = await _seed_workspace(invitation_db)
    await _add_user(invitation_db, "pw-user", "pw@example.com", password="Existing-password-123!")
    created = await _create(monkeypatch, invitation_db, organization_id, email="pw@example.com")

    response = Response()
    accepted = await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token),
        _signed_in("pw-user", csrf_cookie=_CSRF, csrf_header=_CSRF),
        response,
    )
    assert accepted.workspace_id == organization_id
    assert any(key == b"set-cookie" and b"deerflow_workspace=workspace-1" in value for key, value in response.raw_headers)
    async with invitation_db() as session:
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": "pw-user"})
        assert membership is not None and membership.role == "member" and membership.status == "active"
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("account", ["password", "google"])
async def test_accept_verifies_a_real_access_token_cookie_like_production(invitation_db, monkeypatch, account):
    """Production path: AuthMiddleware skips this public route, so nothing
    stamps request.state. The handler has to verify the access_token cookie
    itself (signature, user lookup, token_version), and only the invited
    account's own verified session may accept."""
    import jwt as pyjwt

    organization_id = await _seed_workspace(invitation_db)
    invitee_id, other_id = str(uuid4()), str(uuid4())
    if account == "password":
        await _add_user(invitation_db, invitee_id, "invitee@example.com", password="Existing-password-123!")
    else:
        await _add_user(invitation_db, invitee_id, "invitee@example.com", oauth_provider="google")
    await _add_user(invitation_db, other_id, "someone-else@example.com", password="Another-password-456!")
    created = await _create(monkeypatch, invitation_db, organization_id, email="invitee@example.com")
    # _create stubs the user resolver for the inviter. Put the real cookie
    # pipeline back, reading the real user table.
    monkeypatch.setattr(invitations, "get_current_user_from_request", deps.get_current_user_from_request)
    monkeypatch.setattr(deps, "get_local_provider", lambda: LocalAuthProvider(SQLiteUserRepository(invitation_db)))

    def cookie_request(access_token: str) -> Request:
        return _request(
            cookies={ACCESS_TOKEN_COOKIE_NAME: access_token, CSRF_COOKIE_NAME: _CSRF},
            headers={CSRF_HEADER_NAME: _CSRF},
        )

    forged = pyjwt.encode(
        {"sub": invitee_id, "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC), "ver": 0},
        "not-the-gateway-secret-but-long-enough-for-hs256",
        algorithm="HS256",
    )
    refused_cookies = {
        "someone else's session": create_access_token(other_id),
        "a forged signature naming the invitee": forged,
        "a revoked token version": create_access_token(invitee_id, token_version=1),
        "junk": "not-a-jwt",
    }
    for label, access_token in refused_cookies.items():
        with pytest.raises(Exception) as refused:
            await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=created.token), cookie_request(access_token), Response())
        assert getattr(refused.value, "status_code", None) == 403, label
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None

    request = cookie_request(create_access_token(invitee_id))
    assert getattr(request.state, "auth_source", None) is None and getattr(request.state, "user", None) is None
    accepted = await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=created.token), request, Response())
    assert accepted.workspace_id == organization_id
    async with invitation_db() as session:
        membership = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": invitee_id})
        assert membership is not None and membership.status == "active"
        assert await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": other_id}) is None
