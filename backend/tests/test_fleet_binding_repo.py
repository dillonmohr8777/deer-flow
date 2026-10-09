"""FleetBindingRepository unit tests (fleet foundation item 3): create, lookup,
listing, organization scoping, and the idempotent unique-per-(client,template)
guarantee. HTTP-layer stamping behavior (idempotent return, authorization,
scheduled task creation) is covered by test_fleet_stamping_router.py.
"""

from __future__ import annotations

import pytest
from org_isolation_fixtures import ORG_A, USER_A, USER_B, acting_as, org_world  # noqa: F401

from deerflow.persistence.fleet import FleetBindingExistsError, FleetBindingRepository

pytestmark = pytest.mark.asyncio


async def test_create_get_list_scoped_by_organization(org_world):  # noqa: F811
    session_factory = org_world
    repo = FleetBindingRepository(session_factory)

    with acting_as(USER_A):
        created = await repo.create(
            client_id="client-1",
            template_id="weekly-client-report",
            template_version="1",
            agent_name="acme-weekly-client-report",
            agent_owner_user_id=USER_A,
        )
        assert created["organization_id"] == ORG_A
        assert created["client_id"] == "client-1"
        assert created["agent_name"] == "acme-weekly-client-report"
        assert created["scheduled_task_id"] is None

        fetched = await repo.get_by_client_and_template("client-1", "weekly-client-report")
        assert fetched is not None
        assert fetched["id"] == created["id"]

        assert (await repo.list_by_client("client-1"))[0]["id"] == created["id"]

    with acting_as(USER_B):
        # A foreign binding is invisible to a different organization.
        assert await repo.get_by_client_and_template("client-1", "weekly-client-report") is None
        assert await repo.list_by_client("client-1") == []


async def test_duplicate_client_and_template_raises(org_world):  # noqa: F811
    repo = FleetBindingRepository(org_world)

    with acting_as(USER_A):
        await repo.create(
            client_id="client-1",
            template_id="weekly-client-report",
            template_version="1",
            agent_name="acme-weekly-client-report",
            agent_owner_user_id=USER_A,
        )
        with pytest.raises(FleetBindingExistsError):
            await repo.create(
                client_id="client-1",
                template_id="weekly-client-report",
                template_version="1",
                agent_name="acme-weekly-client-report-2",
                agent_owner_user_id=USER_A,
            )


async def test_same_client_different_templates_both_stamp(org_world):  # noqa: F811
    repo = FleetBindingRepository(org_world)

    with acting_as(USER_A):
        await repo.create(client_id="client-1", template_id="weekly-client-report", template_version="1", agent_name="acme-weekly-client-report", agent_owner_user_id=USER_A)
        await repo.create(client_id="client-1", template_id="review-replies", template_version="1", agent_name="acme-review-replies", agent_owner_user_id=USER_A)

        bindings = await repo.list_by_client("client-1")
        assert {b["template_id"] for b in bindings} == {"weekly-client-report", "review-replies"}


async def test_list_by_client_excludes_other_clients(org_world):  # noqa: F811
    repo = FleetBindingRepository(org_world)

    with acting_as(USER_A):
        await repo.create(client_id="client-1", template_id="weekly-client-report", template_version="1", agent_name="acme-weekly-client-report", agent_owner_user_id=USER_A)
        await repo.create(client_id="client-2", template_id="weekly-client-report", template_version="1", agent_name="globex-weekly-client-report", agent_owner_user_id=USER_A)

        assert [b["client_id"] for b in await repo.list_by_client("client-1")] == ["client-1"]
        assert [b["client_id"] for b in await repo.list_by_client("client-2")] == ["client-2"]
