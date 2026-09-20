"""Backfill verified private organization ownership without enabling tenant reads.

Revision ID: 0027_organization_backfill
Revises: 0026_organization_foundation

The digest routine is deliberately duplicated from runtime identity creation.
Changing either algorithm requires a new migration; existing identifiers must
never be recomputed by a later helper revision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0027_organization_backfill"
down_revision: str | Sequence[str] | None = "0026_organization_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE_TABLES = (
    "agents",
    "projects",
    "project_documents",
    "threads_meta",
    "runs",
    "scheduled_tasks",
    "scheduled_task_runs",
    "subagent_batches",
    "channel_connections",
    "channel_oauth_states",
    "channel_conversations",
    "mcp_tasks",
    "feedback",
)


def _private_organization_id(user_id: str) -> str:
    return f"private-{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:48]}"


def _private_organization_slug(user_id: str) -> str:
    return f"personal-{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:20]}"


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _stamp(bind, table: str, key: str, value: str, organization_id: str) -> None:
    bind.execute(
        sa.text(f"UPDATE {table} SET organization_id = :organization_id WHERE {key} = :value AND organization_id IS NULL"),
        {"organization_id": organization_id, "value": value},
    )


def _organization_for(owner_id: str | None, users: dict[str, str]) -> str | None:
    if owner_id is None:
        return None
    return users.get(str(owner_id))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "users"):
        return
    now = datetime.now(UTC)
    users: dict[str, str] = {}
    for (user_id,) in bind.execute(sa.text("SELECT id FROM users WHERE id IS NOT NULL")):
        user_id = str(user_id)
        organization_id = _private_organization_id(user_id)
        users[user_id] = organization_id
        organization = bind.execute(sa.text("SELECT id FROM organizations WHERE id = :id"), {"id": organization_id}).first()
        if organization is None:
            bind.execute(
                sa.text("INSERT INTO organizations (id, slug, name, status, created_at, updated_at) VALUES (:id, :slug, :name, :status, :now, :now)"),
                {"id": organization_id, "slug": _private_organization_slug(user_id), "name": "Private organization", "status": "active", "now": now},
            )
        member = bind.execute(
            sa.text("SELECT organization_id FROM organization_members WHERE organization_id = :organization_id AND user_id = :user_id"),
            {"organization_id": organization_id, "user_id": user_id},
        ).first()
        if member is None:
            bind.execute(
                sa.text("INSERT INTO organization_members (organization_id, user_id, role, status, created_at, updated_at) VALUES (:organization_id, :user_id, 'owner', 'active', :now, :now)"),
                {"organization_id": organization_id, "user_id": user_id, "now": now},
            )

    # Directly owned rows.
    for table, key in (("agents", "id"), ("projects", "id"), ("channel_connections", "id"), ("channel_oauth_states", "state_hash")):
        if not _has_table(bind, table):
            continue
        owner_column = "owner_user_id" if table.startswith("channel_") else "user_id"
        for row_id, owner_id in bind.execute(sa.text(f"SELECT {key}, {owner_column} FROM {table} WHERE organization_id IS NULL")):
            organization_id = _organization_for(owner_id, users)
            if organization_id is not None:
                _stamp(bind, table, key, str(row_id), organization_id)

    project_orgs = {str(row.id): (str(row.user_id) if row.user_id is not None else None, row.organization_id) for row in bind.execute(sa.text("SELECT id, user_id, organization_id FROM projects"))} if _has_table(bind, "projects") else {}
    if _has_table(bind, "project_documents"):
        for document_id, project_id, owner_id in bind.execute(sa.text("SELECT id, project_id, user_id FROM project_documents WHERE organization_id IS NULL")):
            project = project_orgs.get(str(project_id))
            if project is not None and project[0] == (str(owner_id) if owner_id is not None else None) and project[1] is not None:
                _stamp(bind, "project_documents", "id", str(document_id), str(project[1]))

    # Threads inherit projects when attached, otherwise their audit owner.
    thread_orgs: dict[str, tuple[str | None, str | None]] = {}
    if _has_table(bind, "threads_meta"):
        for thread_id, owner_id, project_id, organization_id in bind.execute(sa.text("SELECT thread_id, user_id, project_id, organization_id FROM threads_meta")):
            owner = str(owner_id) if owner_id is not None else None
            resolved = organization_id
            if resolved is None and project_id is None:
                resolved = _organization_for(owner, users)
                if resolved is not None:
                    _stamp(bind, "threads_meta", "thread_id", str(thread_id), resolved)
            elif resolved is None and project_id is not None:
                project = project_orgs.get(str(project_id))
                if project is not None and project[0] == owner and project[1] is not None:
                    resolved = project[1]
                    _stamp(bind, "threads_meta", "thread_id", str(thread_id), str(resolved))
            thread_orgs[str(thread_id)] = (owner, str(resolved) if resolved is not None else None)

    run_orgs: dict[str, tuple[str | None, str | None, str]] = {}
    if _has_table(bind, "runs"):
        for run_id, thread_id, owner_id, organization_id in bind.execute(sa.text("SELECT run_id, thread_id, user_id, organization_id FROM runs")):
            owner = str(owner_id) if owner_id is not None else None
            thread = thread_orgs.get(str(thread_id))
            resolved = organization_id
            if resolved is None and thread is not None and thread[0] == owner and thread[1] is not None:
                resolved = thread[1]
                _stamp(bind, "runs", "run_id", str(run_id), str(resolved))
            run_orgs[str(run_id)] = (owner, str(resolved) if resolved is not None else None, str(thread_id))

    task_orgs: dict[str, tuple[str, str | None, str | None]] = {}
    if _has_table(bind, "scheduled_tasks"):
        for task_id, owner_id, thread_id, organization_id in bind.execute(sa.text("SELECT id, user_id, thread_id, organization_id FROM scheduled_tasks")):
            owner = str(owner_id) if owner_id is not None else None
            resolved = organization_id
            if resolved is None and thread_id is None:
                resolved = _organization_for(owner, users)
            elif resolved is None:
                thread = thread_orgs.get(str(thread_id))
                if thread is not None and thread[0] == owner:
                    resolved = thread[1]
            if resolved is not None:
                _stamp(bind, "scheduled_tasks", "id", str(task_id), str(resolved))
            task_orgs[str(task_id)] = (str(thread_id) if thread_id is not None else "", owner, str(resolved) if resolved is not None else None)
    if _has_table(bind, "scheduled_task_runs"):
        for row_id, task_id, thread_id in bind.execute(sa.text("SELECT id, task_id, thread_id FROM scheduled_task_runs WHERE organization_id IS NULL")):
            task = task_orgs.get(str(task_id))
            if task is not None and task[0] == str(thread_id) and task[2] is not None:
                _stamp(bind, "scheduled_task_runs", "id", str(row_id), task[2])

    if _has_table(bind, "subagent_batches"):
        for batch_id, owner_id, thread_id, run_id in bind.execute(sa.text("SELECT id, user_id, thread_id, run_id FROM subagent_batches WHERE organization_id IS NULL")):
            thread = thread_orgs.get(str(thread_id))
            run = run_orgs.get(str(run_id)) if run_id is not None else None
            if thread is not None and thread[0] == str(owner_id) and thread[1] is not None and (run is None or (run[0] == str(owner_id) and run[1] == thread[1] and run[2] == str(thread_id))):
                _stamp(bind, "subagent_batches", "id", str(batch_id), thread[1])

    connection_orgs: dict[str, tuple[str, str | None]] = {}
    if _has_table(bind, "channel_connections"):
        for connection_id, owner_id, organization_id in bind.execute(sa.text("SELECT id, owner_user_id, organization_id FROM channel_connections")):
            connection_orgs[str(connection_id)] = (str(owner_id), str(organization_id) if organization_id is not None else None)
    if _has_table(bind, "channel_conversations"):
        for conversation_id, connection_id, owner_id in bind.execute(sa.text("SELECT id, connection_id, owner_user_id FROM channel_conversations WHERE organization_id IS NULL")):
            connection = connection_orgs.get(str(connection_id))
            if connection is not None and connection[0] == str(owner_id) and connection[1] is not None:
                _stamp(bind, "channel_conversations", "id", str(conversation_id), connection[1])

    if _has_table(bind, "mcp_tasks"):
        for task_id, owner_id, thread_id, run_id in bind.execute(sa.text("SELECT id, user_id, thread_id, run_id FROM mcp_tasks WHERE organization_id IS NULL")):
            thread = thread_orgs.get(str(thread_id))
            run = run_orgs.get(str(run_id)) if run_id is not None else None
            if thread is not None and thread[0] == str(owner_id) and thread[1] is not None and (run is None or (run[0] == str(owner_id) and run[1] == thread[1] and run[2] == str(thread_id))):
                _stamp(bind, "mcp_tasks", "id", str(task_id), thread[1])
    if _has_table(bind, "feedback"):
        for feedback_id, owner_id, thread_id, run_id in bind.execute(sa.text("SELECT feedback_id, user_id, thread_id, run_id FROM feedback WHERE organization_id IS NULL")):
            thread = thread_orgs.get(str(thread_id))
            run = run_orgs.get(str(run_id))
            if thread is not None and run is not None and thread[0] == (str(owner_id) if owner_id is not None else None) and thread[1] is not None and run[0] == thread[0] and run[1] == thread[1] and run[2] == str(thread_id):
                _stamp(bind, "feedback", "feedback_id", str(feedback_id), thread[1])


def downgrade() -> None:
    """Remove only the deterministic private-org data stamped by this revision.

    This intentionally leaves the 0026 nullable schema and any unrelated
    organization identities untouched. Resource rows return to the legacy
    NULL quarantine rather than attempting to reconstruct a different owner.
    """
    bind = op.get_bind()
    if not _has_table(bind, "users"):
        return
    private_ids: list[str] = []
    for (user_id,) in bind.execute(sa.text("SELECT id FROM users WHERE id IS NOT NULL")):
        user_id = str(user_id)
        organization_id = _private_organization_id(user_id)
        row = bind.execute(
            sa.text("SELECT id FROM organizations WHERE id = :id AND slug = :slug AND name = 'Private organization'"),
            {"id": organization_id, "slug": _private_organization_slug(user_id)},
        ).first()
        if row is not None:
            private_ids.append(organization_id)
    for organization_id in private_ids:
        for table in _RESOURCE_TABLES:
            if _has_table(bind, table):
                bind.execute(sa.text(f"UPDATE {table} SET organization_id = NULL WHERE organization_id = :organization_id"), {"organization_id": organization_id})
        bind.execute(sa.text("DELETE FROM organization_members WHERE organization_id = :organization_id"), {"organization_id": organization_id})
        bind.execute(sa.text("DELETE FROM organizations WHERE id = :organization_id"), {"organization_id": organization_id})
