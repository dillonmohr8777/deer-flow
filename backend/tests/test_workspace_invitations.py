"""Security regressions for shared-workspace invitations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from app.gateway.auth.config import AuthConfig
from app.gateway.auth.password import hash_password_async
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import invitations
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow


def _request(*, user=None, source=None, cookies: dict[str, str] | None = None) -> Request:
    headers = []
    if cookies:
        headers.append((b"cookie", "; ".join(f"{quote(k)}={quote(v)}" for k, v in cookies.items()).encode()))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/invitations",
            "headers": headers,
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
async def test_wrong_existing_password_does_not_consume_invitation(invitation_db, monkeypatch):
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
    with pytest.raises(Exception) as wrong:
        await invitations.accept_invitation(
            invitations.AcceptInvitationRequest(token=created.token, password="wrong-password"),
            _request(),
            Response(),
        )
    assert getattr(wrong.value, "status_code", None) == 403
    async with invitation_db() as session:
        invitation = await session.get(InvitationRow, created.id)
        assert invitation is not None and invitation.consumed_at is None

    response = Response()
    await invitations.accept_invitation(
        invitations.AcceptInvitationRequest(token=created.token, password="Existing-password-123!"),
        _request(),
        response,
    )
    async with invitation_db() as session:
        user = await session.get(UserRow, "existing-user")
        assert user is not None and user.password_hash == password_hash


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
