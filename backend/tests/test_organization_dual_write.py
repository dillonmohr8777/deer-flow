"""Focused Gate 2 private-organization write coverage."""

import uuid

import pytest
from sqlalchemy import func, select

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.organizations.resolution import active_private_organization_for_user
from deerflow.persistence.user.model import UserRow


def test_private_organization_identity_is_stable_and_non_sensitive():
    user_id = "2f1a0a64-0d14-4d27-b4b2-f824d510be78"

    assert private_organization_id(user_id) == private_organization_id(user_id)
    assert private_organization_id(user_id) != private_organization_id("other-user")
    assert user_id not in private_organization_id(user_id)
    assert user_id not in private_organization_slug(user_id)


@pytest.mark.asyncio
async def test_user_creation_atomically_creates_private_organization(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{(tmp_path / 'users.db').as_posix()}", sqlite_dir=str(tmp_path))
    try:
        repository = SQLiteUserRepository(get_session_factory())
        user = User(id=uuid.uuid4(), email="org-owner@example.com", password_hash="hash")
        await repository.create_user(user)
        organization_id = private_organization_id(str(user.id))
        session_factory = get_session_factory()
        async with session_factory() as session:
            organization = await session.get(OrganizationRow, organization_id)
            membership = await session.get(OrganizationMemberRow, (organization_id, str(user.id)))
            assert organization is not None
            assert organization.slug == private_organization_slug(str(user.id))
            assert membership is not None
            assert membership.role == "owner"
            assert membership.status == "active"
            assert await active_private_organization_for_user(session, str(user.id)) == organization_id

        with pytest.raises(ValueError, match="Email already registered"):
            await repository.create_user(User(id=uuid.uuid4(), email="org-owner@example.com", password_hash="hash"))
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(UserRow)) == 1
            assert await session.scalar(select(func.count()).select_from(OrganizationRow)) == 1
            assert await session.scalar(select(func.count()).select_from(OrganizationMemberRow)) == 1
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_private_organization_resolution_requires_active_membership(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{(tmp_path / 'membership.db').as_posix()}", sqlite_dir=str(tmp_path))
    try:
        repository = SQLiteUserRepository(get_session_factory())
        user = User(id=uuid.uuid4(), email="inactive-member@example.com", password_hash="hash")
        await repository.create_user(user)
        organization_id = private_organization_id(str(user.id))
        session_factory = get_session_factory()
        async with session_factory() as session:
            membership = await session.get(OrganizationMemberRow, (organization_id, str(user.id)))
            assert membership is not None
            membership.status = "inactive"
            await session.commit()
        async with session_factory() as session:
            assert await active_private_organization_for_user(session, str(user.id)) is None
    finally:
        await close_engine()
