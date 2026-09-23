"""M3 lane 0: organization delegations deny by default; membership re-check for streams."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from org_isolation_fixtures import ORG_A, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, org_world  # noqa: F401
from sqlalchemy import update

from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationDelegationRow, OrganizationMemberRow, OrganizationRow

SUBJECT = {"subject_type": "scheduled_task", "subject_id": "task-1"}


async def _grant(repo, **overrides):
    values = {"organization_id": ORG_S, **SUBJECT, "owner_user_id": USER_C, "scopes": ["runs:create", "threads:read"]}
    return await repo.grant(**(values | overrides))


async def _resolve(repo, *, organization_id=ORG_S, scope="runs:create", subject_id="task-1"):
    return await repo.resolve_active_delegation(subject_type="scheduled_task", subject_id=subject_id, organization_id=organization_id, scope=scope)


async def _set_status(session_factory, row, key, status):
    async with session_factory() as session, session.begin():
        await session.execute(update(row).filter_by(**key).values(status=status))


@pytest.mark.asyncio
async def test_delegation_resolves_owner_membership_and_narrowed_scopes(org_world):  # noqa: F811
    repo = OrganizationDelegationRepository(org_world)
    delegation_id = await _grant(repo)

    active = await _resolve(repo)

    assert active is not None
    assert (active.id, active.owner_user_id, active.subject_type, active.subject_id) == (delegation_id, USER_C, "scheduled_task", "task-1")
    # The owner's validated membership travels with the delegation, so a launcher
    # can act in the workspace without a second lookup.
    assert (active.organization.id, active.organization.role, active.organization.storage_user_id) == (ORG_S, "admin", STORAGE_S)
    assert active.scopes == frozenset({"runs:create", "threads:read"})


@pytest.mark.asyncio
async def test_delegation_denies_missing_revoked_expired_and_out_of_scope(org_world):  # noqa: F811
    repo = OrganizationDelegationRepository(org_world)
    assert await _resolve(repo) is None  # nothing granted

    await _grant(repo)
    assert await _resolve(repo) is not None  # positive control for the denials below
    assert await _resolve(repo, scope="threads:delete") is None
    assert await _resolve(repo, organization_id=ORG_A) is None
    assert await _resolve(repo, subject_id="task-2") is None

    assert await repo.revoke(**SUBJECT) == 1
    assert await _resolve(repo) is None
    assert await repo.revoke(**SUBJECT) == 0

    await _grant(repo, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert await _resolve(repo) is None


@pytest.mark.asyncio
async def test_delegation_dies_with_its_owners_membership_or_organization(org_world):  # noqa: F811
    repo = OrganizationDelegationRepository(org_world)
    await _grant(repo)
    await _set_status(org_world, OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_C}, "revoked")
    assert await _resolve(repo) is None

    await _grant(repo, owner_user_id=USER_A)
    assert await _resolve(repo) is not None
    await _set_status(org_world, OrganizationRow, {"id": ORG_S}, "suspended")
    assert await _resolve(repo) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [USER_B, STORAGE_S])
async def test_grant_refuses_owners_without_active_membership(org_world, owner):  # noqa: F811
    # b is an outsider. The storage principal is never a member, so it can never own a delegation.
    repo = OrganizationDelegationRepository(org_world)
    with pytest.raises(PermissionError):
        await _grant(repo, owner_user_id=owner)
    assert await _resolve(repo) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [[], "runs:create", ["runs:create", ""]])
async def test_grant_requires_explicit_scopes(org_world, scopes):  # noqa: F811
    with pytest.raises(ValueError):
        await _grant(OrganizationDelegationRepository(org_world), scopes=scopes)


@pytest.mark.asyncio
async def test_new_grant_supersedes_the_subjects_previous_delegation(org_world):  # noqa: F811
    repo = OrganizationDelegationRepository(org_world)
    first = await _grant(repo)
    second = await _grant(repo, owner_user_id=USER_A)

    active = await _resolve(repo)

    assert (active.id, active.owner_user_id) == (second, USER_A)
    async with org_world() as session:
        assert (await session.get(OrganizationDelegationRow, first)).status == "revoked"


@pytest.mark.asyncio
async def test_two_active_delegations_for_one_subject_deny(org_world):  # noqa: F811
    # No unique index backs "one active delegation per subject"; a concurrent-grant
    # race can leave two, and resolution must not pick an owner between them.
    repo = OrganizationDelegationRepository(org_world)
    await _grant(repo)
    async with org_world() as session, session.begin():
        session.add(OrganizationDelegationRow(id="racing-grant", organization_id=ORG_S, **SUBJECT, owner_user_id=USER_A, scopes=["runs:create"], status="active"))
    assert await _resolve(repo) is None


@pytest.mark.asyncio
async def test_membership_recheck_for_open_streams(org_world):  # noqa: F811
    repo = OrganizationDelegationRepository(org_world)
    assert await repo.is_membership_active(user_id=USER_A, organization_id=ORG_S)
    assert await repo.is_membership_active(user_id=USER_C, organization_id=ORG_S)
    assert not await repo.is_membership_active(user_id=USER_B, organization_id=ORG_S)
    assert not await repo.is_membership_active(user_id=STORAGE_S, organization_id=ORG_S)
    # A missing organization must not fall back to the caller's private organization.
    assert not await repo.is_membership_active(user_id=USER_A, organization_id=None)
    assert not await repo.is_membership_active(user_id=USER_A, organization_id="")

    await _set_status(org_world, OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_C}, "revoked")
    assert not await repo.is_membership_active(user_id=USER_C, organization_id=ORG_S)
    await _set_status(org_world, OrganizationRow, {"id": ORG_S}, "suspended")
    assert not await repo.is_membership_active(user_id=USER_A, organization_id=ORG_S)
