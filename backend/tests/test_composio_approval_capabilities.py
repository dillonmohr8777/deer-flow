"""Capability presentation agrees with actual authenticated route authority."""

import pytest
from org_isolation_fixtures import auth_headers
from org_isolation_fixtures import org_world_pooled as org_world  # noqa: F401
from sqlalchemy import update
from test_composio_admin_oversight import ADMIN, FOREIGN, FOREIGN_ORG, MEMBER, ORG, OWNER, STORAGE, acting, propose
from test_composio_admin_oversight import world as world
from test_composio_approval_handoff import transport as transport

from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.user.model import UserRow


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer,approve", [(MEMBER, True), (OWNER, True), (ADMIN, False)])
async def test_composio_capabilities_match_self_owner_admin_actual_decisions(world, transport, reviewer, approve):
    factory, repo, client = world
    row = await propose(repo)
    head = auth_headers(reviewer, ORG)
    response = await client.get(f"/api/approvals/{row['id']}", headers=head)
    assert response.status_code == 200
    data = response.json()
    assert data["capabilities"]["approve"] is approve
    assert data["capabilities"]["reject"] is True and data["capabilities"]["edit"] is False
    assert data["proposer"]["user_id"] == MEMBER and "@" not in data["proposer"]["display_name"]
    assert set(data["proposer"]) == {"user_id", "display_name"}
    assert data["workspace"] == {"id": ORG, "name": "Shared QA"}
    assert (await client.patch(f"/api/approvals/{row['id']}", headers=head, json={"title": "Changed"})).status_code in {403, 404, 422}
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=head)
    assert result.status_code == (200 if approve else 403)
    if approve:
        assert len(transport.calls) == 1 and result.json()["status"] == "executed"
        assert result.json()["capabilities"] == {"approve": False, "reject": False, "edit": False, "reason": "Action already decided"}
    else:
        assert transport.calls == []
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=head)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer,organization", [(MEMBER, ORG), (FOREIGN, FOREIGN_ORG)])
async def test_member_other_and_foreign_rows_remain_invisible(world, transport, reviewer, organization):
    factory, repo, client = world
    row = await propose(repo, actor=OWNER)
    head = auth_headers(reviewer, organization)
    assert (await client.get(f"/api/approvals/{row['id']}", headers=head)).status_code == 404
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=head)).status_code == 404
    assert transport.calls == []


@pytest.mark.asyncio
async def test_revoked_proposer_disables_approve_but_owner_can_reject(world, transport):
    factory, repo, client = world
    row = await propose(repo)
    async with factory() as session, session.begin():
        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == MEMBER, OrganizationMemberRow.organization_id == ORG).values(status="revoked"))
    head = auth_headers(OWNER, ORG)
    response = await client.get(f"/api/approvals/{row['id']}", headers=head)
    assert response.json()["capabilities"]["approve"] is False
    assert response.json()["capabilities"]["reject"] is True
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=head)).status_code == 404
    assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=head)).status_code == 200
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer,allowed", [(MEMBER, False), (OWNER, True)])
async def test_generic_action_capabilities_preserve_reviewer_policy(world, reviewer, allowed):
    factory, repo, client = world
    with acting(reviewer):
        row = await repo.create(action_type="other", target="draft", payload={"text": "Draft only"}, user_id=STORAGE, organization_id=ORG)
    head = auth_headers(reviewer, ORG)
    data = (await client.get(f"/api/approvals/{row['id']}", headers=head)).json()
    assert [data["capabilities"][key] for key in ("approve", "reject", "edit")] == [allowed] * 3
    assert data["proposer"] is None  # Generic row ownership is not human provenance.
    assert (await client.patch(f"/api/approvals/{row['id']}", json={"title": "Reviewed"}, headers=head)).status_code == (200 if allowed else 403)
    assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=head)).status_code == (200 if allowed else 403)


@pytest.mark.asyncio
async def test_current_disabled_actor_gets_no_capabilities_or_decision(world, transport):
    from datetime import UTC, datetime

    factory, repo, client = world
    row = await propose(repo)
    async with factory() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == OWNER).values(disabled_at=datetime.now(UTC)))
    head = auth_headers(OWNER, ORG)
    assert (await client.get(f"/api/approvals/{row['id']}", headers=head)).status_code == 403
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=head)).status_code == 403
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("contact_actor,unrelated", [(MEMBER, False), (OWNER, False), (MEMBER, True), (OWNER, True)])
async def test_capabilities_match_canonical_bound_contact_exclusion(world, transport, contact_actor, unrelated):
    from uuid import UUID

    from app.gateway.invitation_policy import validate_customer_workspace
    from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
    from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
    from deerflow.persistence.organizations.model import OrganizationRow

    factory, repo, client = world
    agency_storage, bound_client, other_client = [str(UUID(int=value)) for value in (2001, 2002, 2003)]
    agency = private_organization_id(agency_storage)
    async with factory() as session, session.begin():
        session.add(UserRow(id=agency_storage, email="synthetic-agency@example.test", system_role="user"))
        session.add(OrganizationRow(id=agency, slug=private_organization_slug(agency_storage), name="Agency", storage_user_id=agency_storage, status="active"))
        session.add(OrganizationMemberRow(organization_id=agency, user_id=OWNER, role="owner", status="active"))
        session.add_all([ClientRow(id=identifier, organization_id=agency, display_name="Synthetic", status="active") for identifier in (bound_client, other_client)])
        await session.execute(update(UserRow).where(UserRow.id == OWNER).values(system_role="admin"))
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG).values(customer_client_id=bound_client))
        session.add(ClientAssignmentRow(client_id=other_client if unrelated else bound_client, user_id=contact_actor, organization_id=agency, role="client_contact"))
        await session.flush()
        canonical = await validate_customer_workspace(session, organization=await session.get(OrganizationRow, ORG), actor_id=OWNER)
        assert canonical.id == bound_client
    row = await propose(repo)
    head = auth_headers(OWNER, ORG)
    data = (await client.get(f"/api/approvals/{row['id']}", headers=head)).json()
    assert data["capabilities"]["approve"] is unrelated
    assert data["capabilities"]["reject"] is True and data["capabilities"]["edit"] is False
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=head)).status_code == (200 if unrelated else 404)
    assert len(transport.calls) == int(unrelated)
