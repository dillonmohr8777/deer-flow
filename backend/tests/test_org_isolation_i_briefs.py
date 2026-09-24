"""M3 lane I: organization isolation for the personal morning brief
(``GET /api/briefs/today``). Mirrors test_org_isolation_h_clients.py's shape:
a cross-organization disjoint-results sweep, shared-workspace co-member
visibility, and org-switching for one human. Business-logic coverage
(activity assembly, due-today, waiting-on-you) lives in test_briefs_today.py;
this file only exercises the organization boundary.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from org_isolation_fixtures import ORG_A, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from test_briefs_today import NOW, _build_app, _create_client_with_assignment, _project, _thread  # noqa: F401

pytestmark = pytest.mark.asyncio

# Content in a shared workspace is stored under its password-less storage
# principal, not any individual member's user id (org_isolation_fixtures.py).
_STORAGE_USER_BY_ORG = {ORG_A: USER_A, ORG_S: STORAGE_S}


async def _seed_project_and_thread(session_factory, *, organization_id: str, project_id: str, thread_id: str, title: str) -> None:
    owner = _STORAGE_USER_BY_ORG[organization_id]
    async with session_factory() as session:
        session.add_all(
            [
                _project(id=project_id, user_id=owner, organization_id=organization_id, name=f"{title} project"),
                _thread(thread_id=thread_id, user_id=owner, project_id=project_id, organization_id=organization_id, display_name=title, created_at=NOW - timedelta(hours=1)),
            ]
        )
        await session.commit()


async def test_brief_never_crosses_private_organizations(org_world, monkeypatch):  # noqa: F811
    session_factory = org_world
    client = _build_app(session_factory, monkeypatch)
    async with client:
        await _create_client_with_assignment(client, auth_headers(USER_A), "A's client")
        await _seed_project_and_thread(session_factory, organization_id=ORG_A, project_id="proj-a", thread_id="thread-a", title="A's work")

        resp_a = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        # b, acting in b's own (disjoint) private organization: valid auth,
        # but none of a's data is visible.
        resp_b_own_org = await client.get("/api/briefs/today", headers=auth_headers(USER_B))
        # b, explicitly attempting to act inside a's organization: b has no
        # membership there, so AuthMiddleware fails closed before the route runs.
        resp_b_as_a = await client.get("/api/briefs/today", headers=auth_headers(USER_B, ORG_A))

    data_a, data_b_own_org = resp_a.json(), resp_b_own_org.json()
    assert [c["display_name"] for c in data_a["assigned_clients"]] == ["A's client"]
    assert any(item["thread_id"] == "thread-a" for item in data_a["activity"])

    assert resp_b_own_org.status_code == 200
    assert data_b_own_org["assigned_clients"] == []
    assert data_b_own_org["activity"] == []

    assert resp_b_as_a.status_code == 403


async def test_shared_workspace_co_member_sees_activity_but_not_unassigned_clients(org_world, monkeypatch):  # noqa: F811
    """a and c are both active members of shared workspace S: workspace-owned
    projects/threads are visible to both (content is stored under one shared
    principal), but the client roster stays actor-scoped (see briefs.py)."""
    session_factory = org_world
    client = _build_app(session_factory, monkeypatch)
    async with client:
        await _create_client_with_assignment(client, auth_headers(USER_A, ORG_S), "S client")
        await _seed_project_and_thread(session_factory, organization_id=ORG_S, project_id="proj-s", thread_id="thread-s", title="Shared work")

        resp_a = await client.get("/api/briefs/today", headers=auth_headers(USER_A, ORG_S))
        resp_c = await client.get("/api/briefs/today", headers=auth_headers(USER_C, ORG_S))

    data_a, data_c = resp_a.json(), resp_c.json()
    assert [c["display_name"] for c in data_a["assigned_clients"]] == ["S client"]
    assert data_c["assigned_clients"] == []  # c was never assigned to it

    assert any(item["thread_id"] == "thread-s" for item in data_a["activity"])
    assert any(item["thread_id"] == "thread-s" for item in data_c["activity"])


async def test_switching_active_organization_flips_brief_content(org_world, monkeypatch):  # noqa: F811
    """The same human (a) sees a's private work in a's own org, and only the
    shared workspace's work when acting inside S, never both at once."""
    session_factory = org_world
    client = _build_app(session_factory, monkeypatch)
    async with client:
        await _seed_project_and_thread(session_factory, organization_id=ORG_A, project_id="proj-private", thread_id="thread-private", title="A private")
        await _seed_project_and_thread(session_factory, organization_id=ORG_S, project_id="proj-shared", thread_id="thread-shared", title="A in S")

        resp_private = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        resp_shared = await client.get("/api/briefs/today", headers=auth_headers(USER_A, ORG_S))

    private_threads = {item["thread_id"] for item in resp_private.json()["activity"]}
    shared_threads = {item["thread_id"] for item in resp_shared.json()["activity"]}
    assert private_threads == {"thread-private"}
    assert shared_threads == {"thread-shared"}
