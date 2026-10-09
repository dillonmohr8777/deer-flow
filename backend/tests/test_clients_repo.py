"""ClientRepository unit tests (Momentum Phase 2 item 2): CRUD, assignments,
linked-project counts, and the registry-import upsert. Cross-organization
denial is covered at the HTTP layer by test_org_isolation_h_clients.py; these
tests exercise repository behaviour the router doesn't expose directly.
"""

from __future__ import annotations

import pytest
from org_isolation_fixtures import ORG_A, USER_A, USER_B, acting_as, org_world  # noqa: F401

from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.projects import ProjectRepository
from deerflow.persistence.projects.model import ProjectRow

pytestmark = pytest.mark.asyncio


async def test_create_get_list_scoped_by_organization(org_world):  # noqa: F811
    session_factory = org_world
    repo = ClientRepository(session_factory)

    with acting_as(USER_A):
        created = await repo.create(display_name="Acme", aliases=["ACME"], email_domains=["acme.com"])
        assert created["organization_id"] == ORG_A
        assert created["status"] == "active"

        fetched = await repo.get(created["id"])
        assert fetched is not None
        assert fetched["display_name"] == "Acme"
        assert (await repo.list())[0]["id"] == created["id"]

    with acting_as(USER_B):
        # A foreign client is invisible to a different organization.
        assert await repo.get(created["id"]) is None
        assert await repo.list() == []


async def test_patch_and_archive_are_organization_scoped(org_world):  # noqa: F811
    session_factory = org_world
    repo = ClientRepository(session_factory)

    with acting_as(USER_A):
        created = await repo.create(display_name="Acme")
        patched = await repo.patch(created["id"], notes="VIP account")
        assert patched["notes"] == "VIP account"
        archived = await repo.set_status(created["id"], "inactive")
        assert archived["status"] == "inactive"

    with acting_as(USER_B):
        assert await repo.patch(created["id"], notes="hijacked") is None
        assert await repo.set_status(created["id"], "prospect") is None


async def test_assignments_upsert_list_and_remove(org_world):  # noqa: F811
    session_factory = org_world
    repo = ClientRepository(session_factory)

    with acting_as(USER_A):
        created = await repo.create(display_name="Acme")
        added = await repo.add_assignment(created["id"], USER_A, "account_manager")
        assert added["role"] == "account_manager"

        # Re-assigning the same (client, user) pair upserts the role rather
        # than creating a second row -- "unique per client+user" (composite PK).
        updated = await repo.add_assignment(created["id"], USER_A, "contributor")
        assert updated["role"] == "contributor"
        assert len(await repo.list_assignments(created["id"])) == 1

        assert [c["id"] for c in await repo.list_mine()] == [created["id"]]

        assert await repo.remove_assignment(created["id"], USER_A) is True
        assert await repo.list_assignments(created["id"]) == []
        assert await repo.list_mine() == []

    with acting_as(USER_B):
        # A foreign client's assignments cannot be mutated cross-organization.
        assert await repo.add_assignment(created["id"], USER_B, "contributor") is None


async def test_list_assignments_none_for_missing_or_foreign_client(org_world):  # noqa: F811
    session_factory = org_world
    repo = ClientRepository(session_factory)

    with acting_as(USER_A):
        assert await repo.list_assignments("does-not-exist") is None
        created = await repo.create(display_name="Acme")

    with acting_as(USER_B):
        assert await repo.list_assignments(created["id"]) is None


async def test_project_counts(org_world):  # noqa: F811
    session_factory = org_world
    client_repo = ClientRepository(session_factory)
    project_repo = ProjectRepository(session_factory)

    with acting_as(USER_A):
        client = await client_repo.create(display_name="Acme")
        other_client = await client_repo.create(display_name="Globex")
        project = await project_repo.create(name="Acme launch")

        # No dedicated "assign project to client" API exists yet (Phase 2
        # item 2 only adds the column); link it directly at the ORM layer.
        async with session_factory() as session:
            row = await session.get(ProjectRow, project["id"])
            row.client_id = client["id"]
            await session.commit()

        counts = await client_repo.project_counts([client["id"], other_client["id"]])
        assert counts.get(client["id"]) == 1
        assert other_client["id"] not in counts
        assert await client_repo.project_counts([]) == {}


async def test_registry_upsert_creates_then_updates_never_deletes(org_world):  # noqa: F811
    session_factory = org_world
    repo = ClientRepository(session_factory)

    with acting_as(USER_A):
        outcome, row = await repo.upsert_by_registry_id(registry_id="acme-hcm", display_name="Acme HCM", aliases=["Acme"])
        assert outcome == "created"
        assert row["registry_id"] == "acme-hcm"

        outcome2, row2 = await repo.upsert_by_registry_id(registry_id="acme-hcm", display_name="Acme HCM Renamed", aliases=["Acme", "AHCM"])
        assert outcome2 == "updated"
        assert row2["id"] == row["id"]
        assert row2["display_name"] == "Acme HCM Renamed"

        # Never duplicated, never deleted.
        assert [c["id"] for c in await repo.list()] == [row["id"]]
