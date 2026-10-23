"""Real UUID users, auth middleware and durable SQLite; MCP transport is synthetic."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

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
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.composio_approval_authority import bind_composio_authority, current_composio_authority, prepare_composio_authority
from deerflow.mcp.interceptors import compose_tool_interceptors
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.model import OrganizationMemberRow
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
    task = asyncio.create_task(client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(ADMIN, ORG)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if timeout is None:
            assert not task.done()
            release.set()
        result = await asyncio.wait_for(task, 1)
        assert result.status_code == 200
        with acting(ADMIN):
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
@pytest.mark.parametrize("reviewer", [MEMBER, OWNER, ADMIN])
async def test_self_or_admin_approves_once_with_proposer_binding_and_audit(world, transport, reviewer):  # noqa: F811
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
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(ADMIN, ORG))
    assert result.status_code in {404, 409}
    assert transport.calls == []
    with acting(ADMIN):
        assert (await repo.get_composio_for_org(row["id"]))["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite", ["payload", "header", "duplicate_header", "runtime", "server", "membership", "binding", "decider_membership"])
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
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG, OrganizationMemberRow.user_id == (MEMBER if rewrite == "membership" else ADMIN)).values(status="inactive"))
        else:
            transport.config.mcp_servers["composio-me"].user_auth.users[MEMBER] = "new-binding"
        return await handler(request)

    transport.custom = custom
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(ADMIN, ORG))
    assert result.status_code == 200
    assert result.json()["execution_result"]["state"] == "outcome_unknown"
    assert transport.calls == []
    with acting(OWNER):
        stored = await repo.get_composio_for_org(row["id"])
    assert stored["execution_result"]["state"] == "outcome_unknown"
    assert current_composio_authority() is None


@pytest.mark.asyncio
async def test_timeout_and_cancellation_hold_claim_and_reset_authority(world, transport):  # noqa: F811
    _, repo, _ = world
    for call_id, failure in [("timeout", TimeoutError("secret-provider-error")), ("cancel", asyncio.CancelledError())]:
        row = await propose(repo, call_id=call_id)
        transport.error = failure
        with acting(ADMIN):
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
    with acting(ADMIN):
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
    results = await asyncio.gather(*(client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(ADMIN, ORG)) for _ in range(3)))
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
