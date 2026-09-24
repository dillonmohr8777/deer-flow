"""Migration coverage for 0032_org_delegation_backfill: delegations for existing internal callers."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.script import ScriptDirectory

import deerflow.persistence.models  # noqa: F401 -- registers ORM models
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.user.model import UserRow

REVISION = "0032_org_delegation_backfill"
PREVIOUS = "0031_org_rebackfill"

# a and c are real users; s is shared workspace S's storage principal (a owns S,
# c is an admin there); b's private organization has lost b's membership.
A, B, C, S = "user-a", "user-b", "user-c", "storage-s"
ORG = {user: private_organization_id(user) for user in (A, B, C, S)}


async def _seed(session_factory) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        for user in (A, B, C, S):
            session.add(UserRow(id=user, email=f"{user}@example.com", system_role="user", needs_setup=False, token_version=0))
        for user in (A, B, C):
            session.add(OrganizationRow(id=ORG[user], slug=private_organization_slug(user), name="Private organization", status="active"))
            session.add(OrganizationMemberRow(organization_id=ORG[user], user_id=user, role="owner", status="revoked" if user == B else "active"))
        session.add(OrganizationRow(id=ORG[S], slug=private_organization_slug(S), name="Shared S", status="active", storage_user_id=S))
        session.add(OrganizationMemberRow(organization_id=ORG[S], user_id=A, role="owner", status="active"))
        session.add(OrganizationMemberRow(organization_id=ORG[S], user_id=C, role="admin", status="active"))
        for task_id, owner, organization_id in (("task-a", A, ORG[A]), ("task-s", S, ORG[S]), ("task-b", B, ORG[B]), ("task-quarantined", A, None)):
            session.add(ScheduledTaskRow(id=task_id, user_id=owner, organization_id=organization_id, title="t", prompt="p", schedule_type="cron", schedule_spec={"cron": "0 9 * * *"}, timezone="UTC", created_at=now, updated_at=now))
        session.add(McpTaskRow(id="mcp-s", user_id=S, organization_id=ORG[S], thread_id="t-s", server_name="srv", driver_name="drv", remote_task_id="remote", task_name="job", status="working", created_at=now, updated_at=now))
        for connection_id, status in (("conn-a", "connected"), ("conn-a-revoked", "revoked")):
            session.add(ChannelConnectionRow(id=connection_id, owner_user_id=A, organization_id=ORG[A], provider="slack", external_account_id=connection_id, status=status))


def _delegations(db_path) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as raw:
        return raw.execute("SELECT subject_type, subject_id, organization_id, owner_user_id, status FROM organization_delegations ORDER BY subject_type, subject_id").fetchall()


def test_0032_chains_into_the_single_head():
    """0032 has no fork: exactly one head, and it descends from 0032.

    Not "0032 IS the head" -- a later lane (0034_clients and beyond) chains
    past it legitimately, matching 0031's own single-head test's
    ``len(...) == 1`` style rather than pinning the exact head id.
    """
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {rev.revision for rev in script.walk_revisions(base=PREVIOUS, head=heads[0])}
    assert script.get_revision(REVISION).down_revision == PREVIOUS


@pytest.mark.asyncio
async def test_0032_grants_resolvable_delegations_and_round_trips(tmp_path):
    db_path = tmp_path / "delegation-backfill.db"
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{db_path.as_posix()}", sqlite_dir=str(tmp_path))
    try:
        cfg = _get_alembic_config(get_engine())
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await _seed(get_session_factory())
        # A delegation that already exists is kept, not duplicated.
        existing = await OrganizationDelegationRepository(get_session_factory()).grant(organization_id=ORG[A], subject_type="scheduled_task", subject_id="task-a", owner_user_id=A, scopes=["runs:create"])

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        expected = [
            ("channel_connection", "conn-a", ORG[A], A, "active"),
            ("mcp_task", "mcp-s", ORG[S], A, "active"),  # S's storage principal is never a member: S's owner
            ("scheduled_task", "task-a", ORG[A], A, "active"),
            ("scheduled_task", "task-s", ORG[S], A, "active"),
        ]
        # task-b (owner lost membership), task-quarantined (no organization) and the revoked connection get none.
        assert _delegations(db_path) == expected
        delegations = OrganizationDelegationRepository(get_session_factory())
        for subject_type, subject_id, organization_id, owner, _status in expected:
            resolved = await delegations.resolve_active_delegation(subject_type=subject_type, subject_id=subject_id, organization_id=organization_id, scope="runs:create")
            assert resolved is not None and resolved.owner_user_id == owner
        channel = await delegations.resolve_active_delegation(subject_type="channel_connection", subject_id="conn-a", organization_id=ORG[A], scope="threads:write")
        assert channel is not None and channel.id.startswith("dlg0032-")
        assert (await delegations.resolve_active_delegation(subject_type="scheduled_task", subject_id="task-a", organization_id=ORG[A], scope="runs:create")).id == existing

        # Downgrade deletes exactly the dlg0032- rows; a second upgrade recreates them identically.
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert _delegations(db_path) == [("scheduled_task", "task-a", ORG[A], A, "active")]
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert _delegations(db_path) == expected
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert _delegations(db_path) == expected
        with closing(sqlite3.connect(db_path)) as raw:
            assert raw.execute("SELECT version_num FROM alembic_version").fetchall() == [(REVISION,)]
    finally:
        await close_engine()
