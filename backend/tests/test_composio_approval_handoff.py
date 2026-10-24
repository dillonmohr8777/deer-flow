"""Real UUID users, auth middleware and durable SQLite; MCP transport is synthetic."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from org_isolation_fixtures import auth_headers
from org_isolation_fixtures import org_world_pooled as org_world  # noqa: F401
from sqlalchemy import update
from test_composio_admin_oversight import (
    ADMIN,
    FOREIGN,
    FOREIGN_ORG,
    MEMBER,
    ORG,
    OWNER,
    USERS,
    acting,
    propose,
    world,  # noqa: F401
)

from app.gateway.approval_adapters import execute_approved
from app.gateway.invitation_policy import validate_customer_workspace
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.composio_approval_authority import bind_composio_authority, current_composio_authority, prepare_composio_authority
from deerflow.mcp.interceptors import compose_tool_interceptors
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import get_current_user


@pytest.fixture
def transport(monkeypatch):
    state = SimpleNamespace(
        calls=[],
        custom=None,
        error=None,
        discovery=None,
        config=ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "composio-me": {
                        "type": "http",
                        "url": "https://example.invalid/mcp",
                        "headers": {"x-consumer-api-key": "discovery-only"},
                        "user_auth": {"enabled": True, "header": "X-CONSUMER-API-KEY", "users": {actor: f"fake-binding-{actor}" for actor in USERS}},
                    }
                },
            }
        ),
    )
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: state.config)

    class FakeClient:
        def __init__(self, connections, *, tool_interceptors, **kwargs):
            self.connections = connections
            self.tool_interceptors = tool_interceptors
            self.callbacks = None
            state.client = self

        async def get_tools(self, *, server_name):
            if state.discovery is not None:
                await state.discovery()

            async def upstream(request):
                state.calls.append((str(get_current_user().id), request))
                if state.error:
                    raise state.error
                return "synthetic destination receipt"

            async def call(runtime=None, **arguments):
                chain = [*self.tool_interceptors]
                if state.custom:
                    chain.insert(-1, state.custom)
                return await compose_tool_interceptors(chain, upstream)(MCPToolCallRequest(server_name=server_name, name="GMAIL_SEND_EMAIL", args=arguments, runtime=runtime))

            name = f"{server_name}_GMAIL_SEND_EMAIL" if state.config.mcp_servers[server_name].tool_name_prefix else "GMAIL_SEND_EMAIL"
            return [SimpleNamespace(name=name, coroutine=call)]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [True, False])
@pytest.mark.parametrize("timeout", [0.01, None])
async def test_discovery_bound_and_explicit_none_on_both_prefix_paths(world, transport, monkeypatch, prefix, timeout):  # noqa: F811
    _, repo, client = world
    server = transport.config.mcp_servers["composio-me"]
    server.tool_name_prefix = prefix
    server.session_init_timeout = timeout
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    bounds = []

    def bounded_discovery(awaitable, *, timeout):
        bounds.append(timeout)
        return asyncio.wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr("app.gateway.composio_approval_adapter.asyncio", SimpleNamespace(to_thread=asyncio.to_thread, wait_for=bounded_discovery))

    async def discovery():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def unprefixed_discovery(*args, **kwargs):
        assert kwargs["tool_name_prefix"] is False
        return await transport.client.get_tools(server_name=kwargs["server_name"])

    transport.discovery = discovery
    monkeypatch.setattr("langchain_mcp_adapters.tools.load_mcp_tools", unprefixed_discovery)
    row = await propose(repo)
    task = asyncio.create_task(client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(OWNER, ORG)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if timeout is None:
            assert not task.done()
            release.set()
        result = await asyncio.wait_for(task, 1)
        assert result.status_code == 200
        with acting(OWNER):
            stored = await repo.get_composio_for_org(row["id"])
        if timeout is None:
            assert bounds == []
            assert result.json()["status"] == "executed"
            assert len(transport.calls) == 1 and not cancelled.is_set()
        else:
            assert bounds == [timeout]
            assert cancelled.is_set() and transport.calls == []
            assert result.json()["status"] == "failed"
            assert result.json()["error"] == "Current scoped Composio transport is unavailable"
            assert stored["execution_result"] == {} and stored["executed_at"] is None
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer", [MEMBER, OWNER])
async def test_self_or_owner_approves_once_with_proposer_binding_and_audit(world, transport, reviewer):  # noqa: F811
    sf, repo, client = world
    row = await propose(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, ORG))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "executed"
    assert result.json()["decided_by"] == reviewer
    assert len(transport.calls) == 1
    decider, request = transport.calls[0]
    assert decider == reviewer
    assert request.headers == {"x-consumer-api-key": f"fake-binding-{MEMBER}"}
    assert request.args == row["payload"]["arguments"]
    assert request.runtime.context["actor_user_id"] == reviewer
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, ORG))).status_code == 409
    assert len(transport.calls) == 1
    events, _ = await AuditEventRepository(sf).list(organization_id=ORG)
    decisions = [event for event in events if event["action"] in {"approvals.approved", "approvals.executed"}]
    assert len(decisions) == 2
    for event in decisions:
        assert event["actor_user_id"] == reviewer
        assert event["details"]["decided_by"] == reviewer
        assert event["details"]["proposer_user_id"] == MEMBER
        assert event["details"]["organization_id"] == ORG
        assert event["details"]["action_id"] == row["id"]
    assert current_composio_authority() is None


@pytest.mark.asyncio
async def test_member_cannot_approve_another_or_foreign_org(world, transport):  # noqa: F811
    _, repo, client = world
    row = await propose(repo, OWNER)
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(MEMBER, ORG))).status_code == 404
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(FOREIGN, FOREIGN_ORG))).status_code == 404
    assert transport.calls == []


@pytest.mark.asyncio
async def test_admin_retains_oversight_and_reject_but_cannot_approve_another(world, transport):  # noqa: F811
    _, repo, client = world
    row = await propose(repo)
    headers = auth_headers(ADMIN, ORG)
    assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).status_code == 200
    assert row["id"] in [item["id"] for item in (await client.get("/api/approvals", headers=headers)).json()["approvals"]]
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=headers)
    assert result.status_code == 403 and "owner" in result.json()["detail"]
    with acting(ADMIN):
        assert await repo.get_composio_for_approval(row["id"]) is None
        assert await repo.decide_composio(row["id"], approve=True) is None
        stored = await repo.get_composio_for_org(row["id"])
        assert stored["status"] == "pending" and stored["execution_result"] is None
    assert transport.calls == []
    rejected = await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)
    assert rejected.status_code == 200 and rejected.json()["decided_by"] == ADMIN
    assert rejected.json()["status"] == "rejected" and transport.calls == []


@pytest.mark.asyncio
async def test_admin_can_still_approve_own_proposal(world, transport):  # noqa: F811
    _, repo, client = world
    row = await propose(repo, actor=ADMIN)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(ADMIN, ORG))
    assert result.status_code == 200 and result.json()["status"] == "executed"
    assert len(transport.calls) == 1
    assert transport.calls[0][0] == ADMIN
    assert transport.calls[0][1].headers == {"x-consumer-api-key": f"fake-binding-{ADMIN}"}


@pytest.mark.asyncio
async def test_owner_downgrade_blocks_crossactor_cas_before_decision(world, transport):  # noqa: F811
    sf, repo, _ = world
    row = await propose(repo)
    with acting(OWNER):
        await prepare_composio_authority(row, repo)
        async with sf() as session, session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == OWNER).values(role="admin"))
        assert await repo.decide_composio(row["id"], approve=True) is None
        assert (await repo.get_composio_for_org(row["id"]))["status"] == "pending"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_owner_downgrade_after_scope_read_still_blocks_decision_cas(world, transport, monkeypatch):  # noqa: F811
    from deerflow.persistence.approvals import sql

    sf, repo, _ = world
    row = await propose(repo)
    resolve = sql.active_organization_for_user
    changed = False

    async def revoke_after_scope_read(session, actor, organization):
        nonlocal changed
        scoped = await resolve(session, actor, organization)
        if actor == OWNER and not changed:
            changed = True
            async with sf() as writer, writer.begin():
                await writer.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == OWNER).values(role="admin"))
        return scoped

    monkeypatch.setattr(sql, "active_organization_for_user", revoke_after_scope_read)
    with acting(OWNER):
        assert await repo.decide_composio(row["id"], approve=True) is None
        assert (await repo.get_composio_for_org(row["id"]))["status"] == "pending"
    assert changed and transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contact_actor,reviewer,relation,allowed",
    [
        (MEMBER, MEMBER, "bound", False),
        (MEMBER, OWNER, "bound", False),
        (OWNER, OWNER, "bound", False),
        (MEMBER, MEMBER, "unrelated", True),
        (MEMBER, OWNER, "unrelated", True),
        (OWNER, OWNER, "unrelated", True),
        (MEMBER, OWNER, "current", False),
    ],
)
async def test_bound_customer_contact_exclusion_uses_real_canonical_client(world, transport, contact_actor, reviewer, relation, allowed):  # noqa: F811
    sf, repo, client = world
    agency_storage, bound_client_id, unrelated_client_id = [str(UUID(int=value)) for value in (1001, 1002, 1003)]
    agency_id = private_organization_id(agency_storage)
    async with sf() as session, session.begin():
        session.add(UserRow(id=agency_storage, email="agency-storage@example.test", system_role="user"))
        session.add(OrganizationRow(id=agency_id, slug=private_organization_slug(agency_storage), name="Synthetic Agency", storage_user_id=agency_storage, status="active"))
        session.add(OrganizationMemberRow(organization_id=agency_id, user_id=OWNER, role="owner", status="active"))
        session.add_all([ClientRow(id=client_id, organization_id=agency_id, display_name=f"Synthetic {client_id}", status="active") for client_id in (bound_client_id, unrelated_client_id)])
        await session.execute(update(UserRow).where(UserRow.id == OWNER).values(system_role="admin"))
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG).values(customer_client_id=bound_client_id))
        session.add(ClientAssignmentRow(client_id=unrelated_client_id if relation == "unrelated" else bound_client_id, user_id=contact_actor, organization_id=ORG if relation == "current" else agency_id, role="client_contact"))
        await session.flush()
        customer = await session.get(OrganizationRow, ORG)
        canonical = await validate_customer_workspace(session, organization=customer, actor_id=OWNER)
        assert canonical.id == bound_client_id and canonical.organization_id == agency_id
        assert customer.id != agency_id and customer.storage_user_id != agency_storage
    row = await propose(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, ORG))
    if allowed:
        assert result.status_code == 200 and result.json()["status"] == "executed"
        assert len(transport.calls) == 1
        assert transport.calls[0][0] == reviewer
        assert transport.calls[0][1].headers == {"x-consumer-api-key": f"fake-binding-{MEMBER}"}
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, ORG))).status_code == 409
        assert len(transport.calls) == 1
    else:
        assert result.status_code == 404
        assert transport.calls == []
        with acting(OWNER):
            assert (await repo.get_composio_for_org(row["id"]))["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["membership", "disabled", "client", "client_contact", "client_membership", "binding", "public"])
async def test_revoked_or_unsupported_proposer_has_no_approval_or_upstream(world, transport, revocation):  # noqa: F811
    sf, repo, client = world
    row = await propose(repo)
    if revocation in {"membership", "disabled", "client", "client_contact", "client_membership"}:
        async with sf() as session, session.begin():
            if revocation == "membership":
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == MEMBER).values(status="inactive"))
            elif revocation == "client_membership":
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == MEMBER).values(role="client"))
            elif revocation == "client_contact":
                session.add(ClientAssignmentRow(client_id="synthetic-client", user_id=MEMBER, organization_id=ORG, role="client_contact"))
            else:
                await session.execute(update(UserRow).where(UserRow.id == MEMBER).values(**({"disabled_at": datetime.now(UTC)} if revocation == "disabled" else {"system_role": "client"})))
    elif revocation == "binding":
        del transport.config.mcp_servers["composio-me"].user_auth.users[MEMBER]
    else:
        transport.config.mcp_servers["composio-me"].user_auth = None
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(OWNER, ORG))
    assert result.status_code in {404, 409}
    assert transport.calls == []
    with acting(ADMIN):
        assert (await repo.get_composio_for_org(row["id"]))["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite", ["payload", "header", "duplicate_header", "runtime", "server", "membership", "binding", "decider_membership", "owner_downgrade"])
async def test_final_boundary_rechecks_authority_after_custom_interceptor(world, transport, rewrite):  # noqa: F811
    sf, repo, client = world
    row = await propose(repo)

    async def custom(request, handler):
        if rewrite == "payload":
            request = request.override(args={"body": "different"})
        elif rewrite == "header":
            request = request.override(headers={"x-consumer-api-key": "wrong-binding"})
        elif rewrite == "duplicate_header":
            request = request.override(headers={**request.headers, "X-CONSUMER-API-KEY": "wrong-binding"})
        elif rewrite == "runtime":
            request = request.override(runtime=SimpleNamespace(tool_call_id="call-1", context={"thread_id": "wrong", "run_id": "wrong"}))
        elif rewrite == "server":
            request = request.override(server_name="public")
        elif rewrite in {"membership", "decider_membership"}:
            async with sf() as session, session.begin():
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == (MEMBER if rewrite == "membership" else OWNER)).values(status="inactive"))
        elif rewrite == "owner_downgrade":
            async with sf() as session, session.begin():
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == OWNER).values(role="admin"))
        else:
            transport.config.mcp_servers["composio-me"].user_auth.users[MEMBER] = "new-binding"
        return await handler(request)

    transport.custom = custom
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(OWNER, ORG))
    assert result.status_code == 200
    assert result.json()["execution_result"]["state"] == "outcome_unknown"
    assert transport.calls == []
    with acting(ADMIN):
        stored = await repo.get_composio_for_org(row["id"])
    assert stored["execution_result"]["state"] == "outcome_unknown"
    assert current_composio_authority() is None


@pytest.mark.asyncio
async def test_timeout_and_cancellation_hold_claim_and_reset_authority(world, transport):  # noqa: F811
    _, repo, _ = world
    for call_id, failure in [("timeout", TimeoutError("secret-provider-error")), ("cancel", asyncio.CancelledError())]:
        row = await propose(repo, call_id=call_id)
        transport.error = failure
        with acting(OWNER):
            authority = await prepare_composio_authority(row, repo)
            approved = await repo.decide_composio(row["id"], approve=True)
            with bind_composio_authority(authority):
                if isinstance(failure, asyncio.CancelledError):
                    with pytest.raises(asyncio.CancelledError):
                        await execute_approved(approved)
                else:
                    result = await execute_approved(approved)
                    assert result.status == "approved" and "secret-provider-error" not in str(result)
                assert (await execute_approved(approved)).detail["state"] == "outcome_unknown"
            assert (await repo.get_composio_for_org(row["id"]))["execution_result"]["state"] == "outcome_unknown"
        assert current_composio_authority() is None
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_missing_or_argument_shaped_authority_never_impersonates(world, transport):  # noqa: F811
    _, repo, _ = world
    row = await propose(repo)
    with acting(OWNER):
        approved = await repo.decide_composio(row["id"], approve=True)
        assert (await execute_approved({**approved, "authority": {"proposer": MEMBER}})).status == "failed"
        with pytest.raises(ToolException):
            with bind_composio_authority({"proposer": MEMBER}):
                pass
    assert transport.calls == []


@pytest.mark.asyncio
async def test_concurrent_approve_has_one_winner_and_one_attempt(world, transport):  # noqa: F811
    _, repo, client = world
    row = await propose(repo)
    results = await asyncio.gather(*(client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(OWNER, ORG)) for _ in range(3)))
    assert sorted(result.status_code for result in results) == [200, 409, 409]
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_self_decline_is_audited_without_connection_or_execution(world, transport):  # noqa: F811
    sf, repo, client = world
    row = await propose(repo)
    transport.config.mcp_servers.clear()
    result = await client.post(f"/api/approvals/{row['id']}/reject", headers=auth_headers(MEMBER, ORG))
    assert result.status_code == 200 and result.json()["status"] == "rejected"
    assert transport.calls == []
    events, _ = await AuditEventRepository(sf).list(organization_id=ORG)
    assert [event for event in events if event["action"] == "approvals.rejected"][0]["details"]["proposer_user_id"] == MEMBER
