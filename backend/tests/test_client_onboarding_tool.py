"""Tests for the ``onboard_client_workspace`` tool (Momentum welcome lane).

Mirrors ``test_project_document_tools.py``'s harness style: real SQLite repos
and a real per-user filesystem layout under a temp ``DEER_FLOW_HOME``, plus
the ``set_memory_config``/``reset_memory_manager`` precedent from
``test_memory_isolation.py`` for an isolated DeerMem instance per test. The
tool's own ``runtime.context`` carries only ``user_id`` (never
``storage_user_id``/``organization_id``), matching what
``subagents/executor.py`` actually threads through for a batch-task item --
that gap is exactly what the tool's internal ``set_storage_context``
reconstruction (via ``private_organization_id``) exists to close, so
``test_scoping_is_by_the_calling_identity_not_visible_to_a_different_one``
exercises that mechanism directly rather than mocking it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context
from deerflow.tools.builtins.client_onboarding_tool import onboard_client_workspace

pytestmark = pytest.mark.anyio

_USER = "u1"
_OTHER_USER = "u2"


async def _seed_organization(session_factory, *, user_id: str) -> None:
    """Insert the active ``organizations``/``organization_members`` rows a real signup would have created.

    ``private_organization_for_user`` (which the tool calls, matching
    ``ProjectRepository.create``/``ScheduledTaskRepository.create``) requires
    a live organization row, not just the deterministic id -- an unseeded id
    is exactly the "no active organization" case in production, not a
    stand-in for one. The membership row is likewise what
    ``ScheduledTaskRepository.create``'s launch-delegation grant requires of
    its ``delegation_owner_user_id``.
    """
    from datetime import UTC, datetime

    from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow

    now = datetime.now(UTC)
    organization_id = private_organization_id(user_id)
    async with session_factory() as session:
        session.add(OrganizationRow(id=organization_id, slug=private_organization_slug(user_id), name="Private organization", status="active", created_at=now, updated_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="owner", status="active", created_at=now, updated_at=now))
        await session.commit()


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Real SQLite repos, a real per-user projects layout, and an isolated DeerMem instance."""
    import deerflow.config.paths as paths_mod
    from deerflow.agents.memory.manager import reset_memory_manager
    from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    for user_id in (_USER, _OTHER_USER):
        await _seed_organization(sf, user_id=user_id)

    orig_memory_config = get_memory_config()
    set_memory_config(MemoryConfig(manager_class="deermem", backend_config={"storage_path": str(tmp_path / "memory")}))
    reset_memory_manager()

    yield SimpleNamespace(
        sf=sf,
        clients=ClientRepository(sf),
        projects=ProjectRepository(sf),
        documents=ProjectDocumentRepository(sf),
        scheduled_tasks=ScheduledTaskRepository(sf),
    )

    set_memory_config(orig_memory_config)
    reset_memory_manager()
    await close_engine()


def _runtime(*, user_id: str = _USER) -> SimpleNamespace:
    return SimpleNamespace(context={"user_id": user_id})


async def _seed_client(client_repo: ClientRepository, *, user_id: str, display_name: str = "Deborah Mara") -> dict:
    """Seed a client under *user_id*'s organization, the same way the tool itself scopes writes."""
    token = set_storage_context(WorkspaceStorageContext(actor_user_id=user_id, organization_id=private_organization_id(user_id), storage_user_id=user_id))
    try:
        return await client_repo.create(display_name=display_name)
    finally:
        reset_storage_context(token)


def _call(runtime, **kwargs):
    kwargs.setdefault("project_name", "Deborah Mara")
    kwargs.setdefault("brief_markdown", "# Deborah Mara\n\nRetainer client since 2024.")
    kwargs.setdefault("memory_facts", ["Prefers email over Slack", "Renews every January", "Point of contact is Beth"])
    kwargs.setdefault("scheduled_task_prompt", "Write this week's report for Deborah Mara.")
    return onboard_client_workspace.coroutine(runtime=runtime, **kwargs)


class TestHappyPath:
    async def test_creates_project_document_facts_and_paused_task(self, env):
        client = await _seed_client(env.clients, user_id=_USER)

        result = json.loads(await _call(_runtime(), client_id=client["id"]))

        assert result["status"] == "ok"
        assert result["client_id"] == client["id"]
        assert result["project_created"] is True
        assert len(result["fact_ids"]) == 3

        project = await env.projects.get(result["project_id"], user_id=_USER)
        assert project is not None
        assert project["client_id"] == client["id"]
        assert project["name"] == "Deborah Mara"

        document = await env.documents.get(result["document_id"], user_id=_USER)
        assert document is not None
        assert document["name"] == "Client Brief.md"

        task = await env.scheduled_tasks.get(result["scheduled_task_id"], user_id=_USER)
        assert task is not None
        assert task["status"] == "paused"
        assert task["schedule_type"] == "cron"
        assert task["prompt"] == "Write this week's report for Deborah Mara."

    async def test_second_call_updates_the_same_project_instead_of_duplicating(self, env):
        client = await _seed_client(env.clients, user_id=_USER)
        first = json.loads(await _call(_runtime(), client_id=client["id"], project_name="Deborah Mara"))
        second = json.loads(await _call(_runtime(), client_id=client["id"], project_name="Deborah Mara (renamed)"))

        assert second["project_created"] is False
        assert second["project_id"] == first["project_id"]
        project = await env.projects.get(first["project_id"], user_id=_USER)
        assert project["name"] == "Deborah Mara (renamed)"
        # Only ever one project for this client.
        assert len([p for p in await env.projects.list(user_id=_USER) if p["client_id"] == client["id"]]) == 1


class TestValidation:
    async def test_rejects_unknown_client_id(self, env):
        result = json.loads(await _call(_runtime(), client_id="nope"))
        assert "error" in result
        assert await env.projects.list(user_id=_USER) == []

    async def test_scoping_is_by_the_calling_identity_not_visible_to_a_different_one(self, env):
        """A client seeded under u1's organization is unknown to a u2 runtime.

        This is the exact gap subagent/batch execution leaves open (no ambient
        organization context) that the tool closes by reconstructing
        WorkspaceStorageContext from the resolved storage user id.
        """
        client = await _seed_client(env.clients, user_id=_USER)
        result = json.loads(await _call(_runtime(user_id=_OTHER_USER), client_id=client["id"]))
        assert "error" in result
        assert await env.projects.list(user_id=_OTHER_USER) == []

    async def test_rejects_empty_memory_facts(self, env):
        client = await _seed_client(env.clients, user_id=_USER)
        result = json.loads(await _call(_runtime(), client_id=client["id"], memory_facts=["   ", ""]))
        assert "error" in result
        assert await env.projects.list(user_id=_USER) == []

    async def test_rejects_too_many_memory_facts(self, env):
        client = await _seed_client(env.clients, user_id=_USER)
        result = json.loads(await _call(_runtime(), client_id=client["id"], memory_facts=[f"fact {i}" for i in range(9)]))
        assert "error" in result

    async def test_rejects_blank_brief(self, env):
        client = await _seed_client(env.clients, user_id=_USER)
        result = json.loads(await _call(_runtime(), client_id=client["id"], brief_markdown="   "))
        assert "error" in result
