"""f88: a scheduled task's assistant_id must respect client-agent visibility.

Every scheduled occurrence dispatches through
``services.launch_scheduled_thread_run`` -> ``start_run(..., is_internal_caller=True)``,
so ``services._require_run_agent_visible`` (f85's run-start check) never runs
for a scheduled run -- the scheduler acts through the task's organization
delegation, not a person's client scope. Without a check at create/PATCH
time, a member assigned to only one client could stamp another client's
fleet agent onto a scheduled task and have every future occurrence run that
agent's SOUL/knowledge/memory in their own thread. The check belongs in
``resolve_scheduled_task_assistant_id``, the one place both routes funnel
through; a foreign agent answers exactly like a missing one, matching
``agents.py``'s ``_require_visible_client_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_C, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import scheduled_tasks
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.persistence.agents import get_agent_store
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio

USER_D = "user-d"
TASK = {"title": "Daily digest", "prompt": "Summarize the day", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "UTC"}


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id* for this test only.

    Mirrors ``test_org_isolation_h_clients.py``'s helper of the same name: the
    finding's "member assigned only to client C1" is a real org member, not a
    ``client_contact`` invite-only role, which ``AuthMiddleware`` never treats
    as active membership.
    """
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


@pytest_asyncio.fixture()
async def world(org_world, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace(scheduler=SimpleNamespace(min_once_delay_seconds=60)))
    load_agents_api_config_from_dict({"enabled": True})

    await _add_plain_member(org_world, USER_D, ORG_S)
    client_repo = ClientRepository(org_world)
    with acting_as(USER_A, ORG_S):
        c1 = await client_repo.create(display_name="Client One")
        c2 = await client_repo.create(display_name="Client Two Secret")
        await client_repo.add_assignment(c1["id"], USER_D, "client_contact")

        owner_user_id = get_effective_user_id()
        store = get_agent_store()
        store.create("c1-agent", {"name": "c1-agent", "description": "stamped for c1", "client_id": c1["id"]}, "soul", user_id=owner_user_id)
        store.create("c2-agent", {"name": "c2-agent", "description": "stamped for c2", "client_id": c2["id"]}, "soul", user_id=owner_user_id)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(scheduled_tasks.router)
    app.state.thread_store = ThreadMetaRepository(org_world)
    app.state.scheduled_task_repo = ScheduledTaskRepository(org_world)
    app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(org_world)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, app=app, c1=c1, c2=c2)
    finally:
        load_agents_api_config_from_dict({})


async def _create(world, actor, **overrides) -> httpx.Response:
    return await world.client.post("/api/scheduled-tasks", json=TASK | overrides, headers=auth_headers(actor, ORG_S))


async def test_create_refuses_an_unassigned_members_foreign_client_agent(world):
    response = await _create(world, USER_D, assistant_id="c2-agent")

    assert response.status_code == 422
    assert "Unknown assistant_id" in response.json()["detail"]


async def test_create_allows_an_assigned_members_own_client_agent(world):
    response = await _create(world, USER_D, assistant_id="c1-agent")

    assert response.status_code == 200, response.text
    assert response.json()["assistant_id"] == "c1-agent"


async def test_create_allows_org_owner_and_admin_to_name_either_client_agent(world):
    for actor in (USER_A, USER_C):
        response = await _create(world, actor, assistant_id="c2-agent")
        assert response.status_code == 200, (actor, response.text)
        assert response.json()["assistant_id"] == "c2-agent"


async def test_patch_refuses_an_unassigned_members_foreign_client_agent(world):
    created = await _create(world, USER_D, assistant_id="c1-agent")
    task_id = created.json()["id"]

    response = await world.client.patch(
        f"/api/scheduled-tasks/{task_id}",
        json={"assistant_id": "c2-agent"},
        headers=auth_headers(USER_D, ORG_S),
    )

    assert response.status_code == 422
    assert "Unknown assistant_id" in response.json()["detail"]
    unchanged = await world.client.get(f"/api/scheduled-tasks/{task_id}", headers=auth_headers(USER_D, ORG_S))
    assert unchanged.json()["assistant_id"] == "c1-agent"


async def test_patch_allows_an_org_admin_to_move_to_a_foreign_client_agent(world):
    created = await _create(world, USER_A, assistant_id="c1-agent")
    task_id = created.json()["id"]

    response = await world.client.patch(
        f"/api/scheduled-tasks/{task_id}",
        json={"assistant_id": "c2-agent"},
        headers=auth_headers(USER_C, ORG_S),
    )

    assert response.status_code == 200, response.text
    assert response.json()["assistant_id"] == "c2-agent"
