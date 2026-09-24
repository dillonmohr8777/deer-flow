"""Migration coverage for 0031_org_rebackfill: data-only re-backfill of NULL organization stamps."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import insert

import deerflow.persistence.models  # noqa: F401 -- registers ORM models
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

REVISION = "0031_org_rebackfill"
PREVIOUS = "0030_workspace_branding"

# a, b, c are real users. s is shared workspace S's storage principal. d has no
# organization row at all, and e's private organization is suspended.
A, B, C, S, D, E = "user-a", "user-b", "user-c", "storage-s", "user-d", "user-e"
ORG = {user: private_organization_id(user) for user in (A, B, C, S, E)}

EXPECTED = {
    ("projects", "id"): {"p-a": ORG[A], "p-b": ORG[B], "p-d": None},
    # The storage principal's rows land in S; a suspended organization is not stamped.
    ("agents", "id"): {"agent-s": ORG[S], "agent-e": None},
    ("threads_meta", "thread_id"): {
        "t-a": ORG[A],
        "t-s": ORG[S],
        "t-pa": ORG[A],  # inherits its project
        "t-conflict": None,  # its project belongs to b: a conflicting parent stays quarantined
        "t-ghost": None,  # owner is not a user
        "t-ownerless": None,
        "t-kept": "kept-org",  # an existing stamp is never rewritten
    },
    ("runs", "run_id"): {"r-a": ORG[A], "r-s": ORG[S], "r-cross": None, "r-no-thread": None},
    ("feedback", "feedback_id"): {"f-a": ORG[A], "f-cross": None},
}


def _stamps(db_path) -> dict:
    with closing(sqlite3.connect(db_path)) as raw:
        return {(table, key): dict(raw.execute(f"SELECT {key}, organization_id FROM {table}")) for table, key in EXPECTED}


def _identities(db_path) -> tuple[list, list]:
    with closing(sqlite3.connect(db_path)) as raw:
        return (
            raw.execute("SELECT id, slug, name, status, storage_user_id FROM organizations ORDER BY id").fetchall(),
            raw.execute("SELECT organization_id, user_id, role, status FROM organization_members ORDER BY organization_id, user_id").fetchall(),
        )


async def _seed(session_factory) -> None:
    thread = {"status": "idle", "metadata_json": {}}
    run = {"status": "success", "metadata_json": {}, "kwargs_json": {}}
    async with session_factory() as session, session.begin():
        # Core insert: the UserRow ORM object now also carries 0033's disabled_at.
        await session.execute(insert(UserRow.__table__), [{"id": user, "email": f"{user}@example.com", "system_role": "user", "needs_setup": False, "token_version": 0} for user in (A, B, C, S, D, E)])
        # Private organizations keep a NULL storage principal. A NOT IN exclusion
        # over that nullable column would match nothing and stamp no real user.
        for user in (A, B, C, E):
            session.add(OrganizationRow(id=ORG[user], slug=private_organization_slug(user), name="Private organization", status="suspended" if user == E else "active"))
            session.add(OrganizationMemberRow(organization_id=ORG[user], user_id=user, role="owner", status="active"))
        # S as workspaces.py creates it: s is the storage principal and never a member.
        session.add(OrganizationRow(id=ORG[S], slug=private_organization_slug(S), name="Shared S", status="active", storage_user_id=S))
        session.add(OrganizationMemberRow(organization_id=ORG[S], user_id=A, role="owner", status="active"))
        session.add(OrganizationMemberRow(organization_id=ORG[S], user_id=C, role="admin", status="revoked"))
        # Core insert(), not the ProjectRow ORM object: this seed runs against
        # the schema pinned at PREVIOUS (0030), and an ORM insert lists every
        # column the *current* model maps -- including any later migration's
        # addition (e.g. 0034's client_id) -- which 0030's table doesn't have
        # yet. Naming only the columns 0030 actually owns keeps this test
        # immune to future ProjectRow columns.
        await session.execute(insert(ProjectRow.__table__), [{"id": "p-a", "user_id": A, "name": "a"}, {"id": "p-b", "user_id": B, "name": "b"}, {"id": "p-d", "user_id": D, "name": "d"}])
        session.add_all(
            [
                AgentRow(id="agent-s", user_id=S, name="agent-s", config={}, soul=""),
                AgentRow(id="agent-e", user_id=E, name="agent-e", config={}, soul=""),
                ThreadMetaRow(thread_id="t-a", user_id=A, **thread),
                ThreadMetaRow(thread_id="t-s", user_id=S, **thread),
                ThreadMetaRow(thread_id="t-pa", user_id=A, project_id="p-a", **thread),
                ThreadMetaRow(thread_id="t-conflict", user_id=A, project_id="p-b", **thread),
                ThreadMetaRow(thread_id="t-ghost", user_id="ghost", **thread),
                ThreadMetaRow(thread_id="t-ownerless", user_id=None, **thread),
                ThreadMetaRow(thread_id="t-kept", user_id=A, organization_id="kept-org", **thread),
                RunRow(run_id="r-a", thread_id="t-a", user_id=A, **run),
                RunRow(run_id="r-s", thread_id="t-s", user_id=S, **run),
                RunRow(run_id="r-cross", thread_id="t-a", user_id=B, **run),
                RunRow(run_id="r-no-thread", thread_id="no-row", user_id=A, **run),
                FeedbackRow(feedback_id="f-a", run_id="r-a", thread_id="t-a", user_id=A, rating=1),
                FeedbackRow(feedback_id="f-cross", run_id="r-a", thread_id="t-a", user_id=B, rating=1),
            ]
        )


def test_0031_chains_into_the_single_head():
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


@pytest.mark.asyncio
async def test_0031_stamps_verified_rows_without_creating_identities_and_round_trips(tmp_path, caplog):
    db_path = tmp_path / "org-rebackfill.db"
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{db_path.as_posix()}", sqlite_dir=str(tmp_path))
    try:
        cfg = _get_alembic_config(get_engine())
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await _seed(get_session_factory())
        identities = _identities(db_path)

        caplog.set_level(logging.WARNING)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)

        assert _stamps(db_path) == EXPECTED
        # Data only: no organization or membership is created or changed. The
        # storage principal gains no membership (0027's user loop would have made
        # it S's active owner), c keeps its revoked admin row, e stays suspended.
        assert _identities(db_path) == identities
        with closing(sqlite3.connect(db_path)) as raw:
            assert raw.execute("SELECT COUNT(*) FROM organization_members WHERE user_id = ?", (S,)).fetchone() == (0,)
        # Every quarantined row is reported per table.
        messages = [record.getMessage() for record in caplog.records]
        for (table, _key), rows in EXPECTED.items():
            count = sum(organization_id is None for organization_id in rows.values())
            assert f"{REVISION}: {table} keeps {count} row(s) in NULL-organization quarantine" in messages

        # The downgrade is deliberately a no-op, so stamps survive it and a
        # second upgrade changes nothing.
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert _stamps(db_path) == EXPECTED
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert _stamps(db_path) == EXPECTED
        assert _identities(db_path) == identities
        with closing(sqlite3.connect(db_path)) as raw:
            assert raw.execute("SELECT version_num FROM alembic_version").fetchall() == [(REVISION,)]
    finally:
        await close_engine()
