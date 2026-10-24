"""Credential-free Composio session isolation and durable first-use fencing."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient as RealMcpClient
from org_isolation_fixtures import auth_headers
from org_isolation_fixtures import org_world_pooled as org_world  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_composio_admin_oversight import MEMBER as PROPOSER
from test_composio_admin_oversight import ORG as APPROVAL_ORG
from test_composio_admin_oversight import OWNER as REVIEWER
from test_composio_admin_oversight import acting as approval_actor
from test_composio_admin_oversight import world  # noqa: F401

from app.gateway.auth.models import User
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.base import Base
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER,
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    PRIVATE_MCP_SESSION_CONTEXT_KEY,
    PRIVATE_MCP_SESSION_MARKER,
    WorkspaceStorageContext,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
STORAGE = "33333333-3333-4333-8333-333333333333"
ORG = private_organization_id(STORAGE)


@contextmanager
def actor(actor_id=A, role="user", **overrides):
    from deerflow.mcp.composio_sessions import bind_composio_context, reset_composio_context

    user = User(id=UUID(actor_id), email=f"{actor_id}@example.com", system_role=role)
    user_token = set_current_user(user)
    storage_token = set_storage_context(WorkspaceStorageContext(actor_id, ORG, STORAGE, "member"))
    context = {
        AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
        PRIVATE_MCP_SESSION_CONTEXT_KEY: PRIVATE_MCP_SESSION_MARKER,
        "actor_user_id": actor_id,
        "user_id": actor_id,
        "storage_user_id": STORAGE,
        "organization_id": ORG,
        "user_role": role,
        "is_internal": False,
        **overrides,
    }
    token = bind_composio_context(context, thread_id="thread", run_id="run")
    runtime = SimpleNamespace(context={**context, "thread_id": "thread", "run_id": "run"}, tool_call_id="call")
    runtime.context.pop(AUTHENTICATED_CONTEXT_MARKER_KEY, None)
    runtime.context.pop(PRIVATE_MCP_SESSION_CONTEXT_KEY, None)
    try:
        yield runtime
    finally:
        reset_composio_context(token)
        reset_storage_context(storage_token)
        reset_current_user(user_token)


@pytest_asyncio.fixture
async def repo(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sessions.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([UserRow(id=value, email=f"{value}@example.com") for value in (A, B, STORAGE)])
        session.add(OrganizationRow(id=ORG, slug="synthetic-shared", name="Synthetic shared", status="active", storage_user_id=STORAGE))
        session.add_all([OrganizationMemberRow(organization_id=ORG, user_id=value, role="owner" if value == A else "member", status="active") for value in (A, B)])
        for value in (A, B):
            session.add(OrganizationRow(id=private_organization_id(value), slug="private-" + value, name="Synthetic private", status="active"))
            session.add(OrganizationMemberRow(organization_id=private_organization_id(value), user_id=value, role="owner", status="active"))
        await session.commit()
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: sessions)
    yield UserPreferencesRepository(sessions)
    await engine.dispose()


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setenv("COMPOSIO_TEST_KEY", "synthetic-project-key")
    config = ExtensionsConfig.model_validate({"composioMe": {"enabled": True, "project_key_env": "COMPOSIO_TEST_KEY", "toolkits": ["gmail"]}})
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    return config


def response(session_id, owner=A, **overrides):
    return {
        "session_id": session_id,
        "config": {"user_id": f"momobot-{owner}", "toolkits": {"enabled": ["gmail"]}},
        "mcp": {"type": "http", "url": f"https://backend.composio.dev/tool_router/v3/{session_id}/mcp"},
        **overrides,
    }


@pytest.mark.asyncio
async def test_two_real_uuid_actors_share_storage_but_never_sessions(repo, policy):
    from deerflow.mcp.composio_sessions import resolve_actor_session

    requests = []
    owners = {}

    def upstream(request):
        import json

        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            owner = body["user_id"].removeprefix("momobot-")
            assert body["toolkits"] == {"enable": ["gmail"]}
            session_id = "trs_" + owner[:8]
            owners[session_id] = owner
            return httpx.Response(200, json={"session_id": session_id})
        session_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=response(session_id, owners[session_id]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        for owner in (A, B, A):
            with actor(owner) as runtime:
                resolved = await resolve_actor_session(runtime, policy, repository=repo, http_client=client)
                assert resolved.actor_user_id == owner
                assert resolved.session_id == "trs_" + owner[:8]
    assert [request.method for request in requests].count("POST") == 2
    for owner in (A, B):
        stored = await repo.get(owner)
        assert "synthetic-project-key" not in str(stored)
        assert "https" not in str(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"channel_name": "slack"}, {"non_interactive": True}, {"is_internal": True}, {PRIVATE_MCP_SESSION_CONTEXT_KEY: True}, {AUTHENTICATED_CONTEXT_MARKER_KEY: True}, {"actor_user_id": B}])
async def test_forged_or_nonweb_context_has_zero_http(repo, policy, overrides):
    from langchain_core.tools import ToolException

    from deerflow.mcp.composio_sessions import resolve_actor_session

    requests = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        with actor(**overrides) as runtime, pytest.raises(ToolException):
            await resolve_actor_session(runtime, policy, repository=repo, http_client=client)
    assert requests == []


@pytest.fixture
def upstream(policy, monkeypatch):
    from langchain_core.tools import StructuredTool
    from langchain_mcp_adapters.interceptors import MCPToolCallRequest
    from mcp.types import CallToolResult

    from deerflow.mcp import composio_sessions as sessions
    from deerflow.mcp.interceptors import compose_tool_interceptors

    state = SimpleNamespace(requests=[], calls=[], discoveries=[], owners={}, error=None, mutate=None, interceptor=None)

    def api(request):
        state.requests.append(request)
        if state.error:
            raise state.error
        if request.method == "POST":
            owner = json.loads(request.content)["user_id"].removeprefix("momobot-")
            session_id = "trs_" + owner[:8]
            state.owners[session_id] = owner
            return httpx.Response(200, json={"session_id": session_id})
        session_id = request.url.path.rsplit("/", 1)[-1]
        body = response(session_id, state.owners[session_id])
        if state.mutate:
            body = state.mutate(body)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(sessions, "_api_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(api)))

    class Client:
        def __init__(self, connections, *, tool_interceptors, **kwargs):
            self.connections, self.interceptors = connections, tool_interceptors
            state.client = self

        async def get_tools(self, *, server_name):
            session_id = self.connections[server_name]["url"].split("/")[-2]
            owner = state.owners[session_id]
            state.discoveries.append(owner)
            tools = []
            for raw_name in sessions.ROUTER_TOOLS:

                async def call(runtime=None, _name=raw_name, **arguments):
                    async def execute(request):
                        from deerflow.runtime.user_context import get_current_user

                        assert str(get_current_user().id) == request.runtime.context["actor_user_id"]
                        state.calls.append((owner, request))
                        return state.result if hasattr(state, "result") else {"owner": owner}

                    chain = [*self.interceptors]
                    if state.interceptor:
                        chain.insert(-1, state.interceptor)
                    result = await compose_tool_interceptors(chain, execute)(MCPToolCallRequest(server_name=server_name, name=_name, args=arguments, runtime=runtime))
                    if getattr(state, "convert_result", False):
                        from langchain_mcp_adapters.tools import _convert_call_tool_result

                        return _convert_call_tool_result(result)
                    return (result.structuredContent if isinstance(result, CallToolResult) else result), None

                schema = {
                    "type": "object",
                    "properties": {"field_" + owner[:8]: {"type": "string", "default": "private-" + owner, "description": "https://backend.composio.dev/private?token=synthetic-project-key"}},
                    "additionalProperties": True,
                }
                tools.append(StructuredTool(name=f"{server_name}_{raw_name}", description="Synthetic router", args_schema=schema, coroutine=call, response_format="content_and_artifact"))
            return tools

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", Client)
    return state


@pytest.mark.asyncio
async def test_reused_compiled_wrapper_introspects_and_executes_only_current_actor(repo, policy, upstream):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.mcp.composio_sessions import composio_tools

    with actor(A) as runtime:
        wrapper = composio_tools(runtime.context, policy)[0]
    assert upstream.requests == []
    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("tools", ToolNode([wrapper], handle_tool_errors=False))
    graph_builder.add_edge(START, "tools")
    graph_builder.add_edge("tools", END)
    graph = graph_builder.compile()
    with actor(B) as runtime:
        state = {"messages": [AIMessage(content="", tool_calls=[{"name": wrapper.name, "args": {"tool_name": "COMPOSIO_SEARCH_TOOLS"}, "id": "inspect"}])]}
        result = await graph.ainvoke(state, context=runtime.context)
        text = result["messages"][-1].content
        assert "field_22222222" in text and "field_11111111" not in text
        assert "private-" not in text and "synthetic-project-key" not in text and "https://" not in text
        assert upstream.calls == []
        result = await wrapper.coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments={"tools": [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}]}, runtime=runtime)
        assert result[0]["owner"] == B
    assert [call[0] for call in upstream.calls] == [B]
    assert set(upstream.owners.values()) == {B}


@pytest.mark.asyncio
async def test_mandatory_write_gate_keeps_exact_inner_payload_and_zero_execution(repo, policy, upstream):
    from deerflow.mcp.composio_sessions import composio_tools

    arguments = {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"body": "Exact synthetic draft"}}]}
    with actor(A) as runtime:
        result = await composio_tools(runtime.context, policy)[0].coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments=arguments, runtime=runtime)
        stored = (await PendingActionRepository(repo.sessions).list())[0]
    assert result[0]["status"] == "pending_approval" and upstream.calls == []
    assert stored["payload"]["tool_name"] == "COMPOSIO_MULTI_EXECUTE_TOOL"
    assert stored["payload"]["arguments"] == arguments
    assert stored["user_id"] == A
    assert "synthetic-project-key" not in str(stored) and "https" not in str(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disabled", "client_contact", "bound_contact", "inactive", "client", "missing_key"])
async def test_current_actor_classifier_and_missing_project_key_deny_before_http(repo, policy, upstream, monkeypatch, failure):
    from datetime import UTC, datetime

    from langchain_core.tools import ToolException
    from sqlalchemy import update

    from deerflow.mcp.composio_sessions import resolve_actor_session

    async with repo.sessions() as session, session.begin():
        if failure == "disabled":
            await session.execute(update(UserRow).where(UserRow.id == A).values(disabled_at=datetime.now(UTC)))
        elif failure == "client":
            await session.execute(update(UserRow).where(UserRow.id == A).values(system_role="client"))
        elif failure == "inactive":
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == A).values(status="inactive"))
        elif failure in {"client_contact", "bound_contact"}:
            session.add(ClientRow(id="exact-bound-client", organization_id="synthetic-agency", display_name="Synthetic", status="active"))
            if failure == "bound_contact":
                await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG).values(customer_client_id="exact-bound-client"))
            session.add(ClientAssignmentRow(client_id="exact-bound-client", user_id=A, organization_id=ORG if failure == "client_contact" else "synthetic-agency", role="client_contact"))
    if failure == "missing_key":
        monkeypatch.delenv("COMPOSIO_TEST_KEY")
    with actor(A) as runtime, pytest.raises(ToolException):
        await resolve_actor_session(runtime, policy)
    assert upstream.requests == [] and upstream.calls == []


@pytest.mark.asyncio
async def test_concurrent_first_use_has_one_creator_and_held_unknown_never_replays(repo, policy, upstream, monkeypatch):
    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def create(request):
        requests.append(request)
        entered.set()
        await release.wait()
        raise httpx.ReadTimeout("synthetic secret endpoint must not escape")

    monkeypatch.setattr(sessions, "_api_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(create)))
    with actor(A) as runtime:
        first = asyncio.create_task(sessions.resolve_actor_session(runtime, policy))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(ToolException, match="held"):
                await sessions.resolve_actor_session(runtime, policy)
        finally:
            release.set()
        with pytest.raises(ToolException, match="held"):
            await first
        with pytest.raises(ToolException, match="held"):
            await sessions.resolve_actor_session(runtime, policy)
    assert len(requests) == 1
    assert (await repo.get(A))[sessions.SESSION_KEY]["state"] == "uncertain"


async def approval_proposal(repo):
    with approval_actor(PROPOSER):
        return await repo.create(
            action_type="composio_tool_call",
            target="composio-me",
            payload={"server_name": "composio-me", "tool_name": "COMPOSIO_MULTI_EXECUTE_TOOL", "arguments": {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"body": "Exact synthetic draft"}}]}, "tool_call_id": "approval-call"},
            user_id=PROPOSER,
            organization_id=APPROVAL_ORG,
            thread_id="thread",
            run_id="run",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer", [PROPOSER, REVIEWER])
async def test_dynamic_self_and_owner_approval_use_proposer_existing_session_once(world, policy, upstream, reviewer):  # noqa: F811
    from langchain_core.tools import ToolException

    from deerflow.mcp.composio_sessions import SESSION_KEY, current_composio_context

    factory, repo, client = world
    preferences = UserPreferencesRepository(factory)
    await preferences.reserve_key(PROPOSER, SESSION_KEY, {"state": "ready", "session_id": "trs_proposer"})
    await preferences.reserve_key(REVIEWER, SESSION_KEY, {"state": "ready", "session_id": "trs_decider"})
    upstream.owners.update({"trs_proposer": PROPOSER, "trs_decider": REVIEWER})
    row = await approval_proposal(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, APPROVAL_ORG))
    assert result.status_code == 200 and result.json()["status"] == "executed", result.text
    assert len(upstream.calls) == 1 and upstream.calls[0][0] == PROPOSER
    assert upstream.calls[0][1].runtime.context["actor_user_id"] == reviewer
    assert upstream.calls[0][1].args == row["payload"]["arguments"]
    assert all(request.method == "GET" and request.url.path.endswith("/trs_proposer") for request in upstream.requests)
    count = len(upstream.requests)
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(reviewer, APPROVAL_ORG))).status_code == 409
    assert len(upstream.calls) == 1 and len(upstream.requests) == count
    with pytest.raises(ToolException):
        current_composio_context(approval=True)


@pytest.mark.asyncio
async def test_dynamic_approval_without_proposer_reference_never_creates_or_uses_owner(world, policy, upstream):  # noqa: F811
    from deerflow.mcp.composio_sessions import SESSION_KEY

    factory, repo, client = world
    await UserPreferencesRepository(factory).reserve_key(REVIEWER, SESSION_KEY, {"state": "ready", "session_id": "trs_decider"})
    upstream.owners["trs_decider"] = REVIEWER
    row = await approval_proposal(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(REVIEWER, APPROVAL_ORG))
    assert result.status_code == 409
    assert upstream.requests == [] and upstream.calls == []
    with approval_actor(PROPOSER):
        assert (await repo.get(row["id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_dynamic_approved_revocation_fences_transport_and_retains_unknown(world, policy, upstream):  # noqa: F811
    from sqlalchemy import update

    from deerflow.mcp.composio_sessions import SESSION_KEY

    factory, repo, client = world
    await UserPreferencesRepository(factory).reserve_key(PROPOSER, SESSION_KEY, {"state": "ready", "session_id": "trs_proposer"})
    upstream.owners["trs_proposer"] = PROPOSER

    async def revoke(request, handler):
        async with factory() as session, session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == APPROVAL_ORG, OrganizationMemberRow.user_id == PROPOSER).values(status="inactive"))
        return await handler(request)

    upstream.interceptor = revoke
    row = await approval_proposal(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(REVIEWER, APPROVAL_ORG))
    assert result.status_code == 200 and result.json()["execution_result"]["state"] == "outcome_unknown"
    assert upstream.calls == []
    with approval_actor(REVIEWER):
        assert (await repo.get_composio_for_org(row["id"]))["execution_result"]["state"] == "outcome_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_source", ["pat", "internal", "auth_disabled"])
async def test_dynamic_approval_rejects_non_session_origin_before_decision(world, policy, upstream, auth_source):  # noqa: F811
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    factory, repo, client = world
    app = client._transport.app

    async def origin(request, call_next):
        request.state.auth_source = auth_source
        return await call_next(request)

    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=origin))
    row = await approval_proposal(repo)
    result = await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(REVIEWER, APPROVAL_ORG))
    assert result.status_code == 403
    assert upstream.requests == [] and upstream.calls == []
    with approval_actor(PROPOSER):
        assert (await repo.get(row["id"]))["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_shape", ["versioned", "unversioned"])
@pytest.mark.parametrize(
    "change",
    ["wrong_owner", "wrong_id", "wrong_toolkits", "foreign_origin", "userinfo", "fragment", "query", "port", "wrong_session_path", "encoded_separator", "encoded_session", "extra_path"],
)
async def test_stored_lookup_never_replaces_or_forwards_unverified_endpoint(repo, policy, upstream, endpoint_shape, change):
    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    await repo.reserve_key(A, sessions.SESSION_KEY, {"state": "ready", "session_id": "trs_saved"})
    upstream.owners["trs_saved"] = A

    path = f"/tool_router/{'v3/' if endpoint_shape == 'versioned' else ''}trs_saved/mcp"

    def mutate(body):
        if change == "wrong_owner":
            body["config"]["user_id"] = f"momobot-{B}"
        elif change == "wrong_id":
            body["session_id"] = "trs_other"
        elif change == "wrong_toolkits":
            body["config"]["toolkits"]["enabled"] = ["gmail", "slack"]
        else:
            body["mcp"]["url"] = {
                "foreign_origin": f"https://app.composio.dev{path}",
                "userinfo": f"https://secret@backend.composio.dev{path}",
                "fragment": f"https://backend.composio.dev{path}#secret",
                "query": f"https://backend.composio.dev{path}?token=secret",
                "port": f"https://backend.composio.dev:8443{path}",
                "wrong_session_path": f"https://backend.composio.dev/tool_router/{'v3/' if endpoint_shape == 'versioned' else ''}trs_other/mcp",
                "encoded_separator": f"https://backend.composio.dev/tool_router{'/v3' if endpoint_shape == 'versioned' else ''}%2ftrs_saved/mcp",
                "encoded_session": f"https://backend.composio.dev/tool_router/{'v3/' if endpoint_shape == 'versioned' else ''}trs%5fsaved/mcp",
                "extra_path": f"https://backend.composio.dev{path}/extra",
            }[change]
        return body

    upstream.mutate = mutate
    with actor(A) as runtime:
        for _ in range(2):
            with pytest.raises(ToolException):
                await sessions.load_current_composio_tool("COMPOSIO_SEARCH_TOOLS", runtime, policy)
    assert len(upstream.requests) == 2 and all(request.method == "GET" for request in upstream.requests)
    assert upstream.discoveries == []
    assert (await repo.get(A))[sessions.SESSION_KEY]["session_id"] == "trs_saved"


@pytest.mark.asyncio
async def test_actual_unversioned_endpoint_is_preserved_across_create_and_reload(repo, policy, upstream):
    from deerflow.mcp import composio_sessions as sessions

    session_id = "trs_11111111"
    endpoint = f"https://backend.composio.dev/tool_router/{session_id}/mcp"
    upstream.mutate = lambda body: {**body, "mcp": {"type": "http", "url": endpoint}}
    with actor(A) as runtime:
        created = await sessions._resolve_transport(runtime, policy, repository=repo)
        reloaded = await sessions._resolve_transport(runtime, policy, repository=repo)

    assert created[0] == reloaded[0]
    assert created[1] == reloaded[1] == endpoint
    assert [request.method for request in upstream.requests] == ["POST", "GET", "GET"]
    stored = (await repo.get(A))[sessions.SESSION_KEY]
    assert stored == {"state": "ready", "session_id": session_id}
    assert endpoint not in str(stored) and "synthetic-project-key" not in str(stored)


@pytest.mark.asyncio
async def test_existing_get_failure_and_cancelled_create_never_create_replacements(repo, policy, upstream):
    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    await repo.reserve_key(A, sessions.SESSION_KEY, {"state": "ready", "session_id": "trs_saved"})
    upstream.owners["trs_saved"] = A
    upstream.error = httpx.ReadTimeout("synthetic credential endpoint")
    with actor(A) as runtime:
        for _ in range(2):
            with pytest.raises(ToolException):
                await sessions.resolve_actor_session(runtime, policy)
    assert [request.method for request in upstream.requests] == ["GET", "GET"]


@pytest.mark.asyncio
async def test_legacy_actor_membership_only_skips_new_session(repo, policy, upstream):
    from langchain_core.tools import ToolException

    from deerflow.config.extensions_config import McpServerConfig, McpUserScopedAuthConfig
    from deerflow.mcp.composio_sessions import composio_tools, resolve_actor_session

    class MembershipOnly(dict):
        def get(self, *args):
            raise AssertionError("Legacy credential value read")

        def __getitem__(self, key):
            raise AssertionError("Legacy credential value read")

        def values(self):
            raise AssertionError("Legacy credential values read")

    auth = McpUserScopedAuthConfig.model_construct(enabled=True, users=MembershipOnly({A: "unread-synthetic"}))
    policy.mcp_servers["composio-sean"] = McpServerConfig.model_construct(enabled=True, type="http", user_auth=auth)
    with actor(A) as runtime:
        assert composio_tools(runtime.context, policy) == []
        with pytest.raises(ToolException, match="unavailable"):
            await resolve_actor_session(runtime, policy)
    assert upstream.requests == []


def test_disabled_default_and_project_only_operator_descriptor():
    from pydantic import ValidationError

    assert not ExtensionsConfig().composio_me.enabled
    for descriptor in [{"project_key_env": "COMPOSIO_USER_API_KEY"}, {"project_key_env": "$PROJECT_KEY"}, {"project_key": "must-not-be-config"}, {"toolkits": ["unreviewed"]}]:
        with pytest.raises(ValidationError):
            ExtensionsConfig.model_validate({"composioMe": descriptor})


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["session", "pat", "auth_disabled", "internal", "factory-error"])
async def test_worker_binds_original_server_session_scope_and_resets(repo, source):
    from langchain_core.tools import ToolException

    from app.gateway.services import inject_authenticated_user_context
    from deerflow.mcp.composio_sessions import current_composio_context
    from deerflow.runtime.runs.manager import RunRecord, RunStartOutcome
    from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
    from deerflow.runtime.runs.worker import RunContext, run_agent
    from deerflow.runtime.user_context import get_current_user

    seen = []

    def allowed(runtime=None):
        try:
            current_composio_context(runtime)
            return True
        except ToolException:
            return False

    class Agent:
        metadata, checkpointer, store = {}, None, None
        interrupt_before_nodes, interrupt_after_nodes = [], []

        async def astream(self, *args, **kwargs):
            seen.append(("graph", allowed(SimpleNamespace(context=kwargs["config"]["context"]))))
            assert AUTHENTICATED_CONTEXT_MARKER_KEY not in kwargs["config"]["context"]
            assert PRIVATE_MCP_SESSION_CONTEXT_KEY not in kwargs["config"]["context"]
            return
            yield

    def factory(**kwargs):
        seen.append(("assembly", allowed()))
        if source == "factory-error":
            raise RuntimeError("synthetic assembly failure")
        return Agent()

    manager = SimpleNamespace(**{name: AsyncMock() for name in ["wait_for_prior_finalizing", "set_status", "set_status_if_not_cancelled", "update_model_name", "update_run_completion", "cleanup"]})
    manager.set_finalizing = AsyncMock(return_value=None)
    manager.try_start = AsyncMock(return_value=RunStartOutcome.started)
    manager.has_later_run = manager.has_later_started_run = AsyncMock(return_value=False)
    manager.set_status_if_not_cancelled = AsyncMock(return_value=None)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    record = RunRecord(run_id="run", thread_id="thread", assistant_id="lead-agent", status=RunStatus.pending, on_disconnect=DisconnectMode.cancel)
    record.abort_event = asyncio.Event()
    with actor(A, **{AUTHENTICATED_CONTEXT_MARKER_KEY: False}):
        assert not allowed()
        config = {"context": {"actor_user_id": B, "user_id": B, AUTHENTICATED_CONTEXT_MARKER_KEY: True}}
        request = SimpleNamespace(state=SimpleNamespace(user=get_current_user(), auth_source="session" if source == "factory-error" else source, actor_user_id=A, storage_user_id=STORAGE, organization_id=ORG))
        inject_authenticated_user_context(config, request)
        await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None), agent_factory=factory, graph_input={"messages": []}, config=config)
        assert not allowed()
    valid = source in {"session", "factory-error"}
    assert seen == [("assembly", valid)] + ([] if source == "factory-error" else [("graph", valid)])


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_shape", ["versioned", "unversioned"])
@pytest.mark.parametrize("stage,failure", [("success", None), ("discovery", "redirect"), ("invocation", "redirect"), ("discovery", "timeout"), ("invocation", "timeout")])
async def test_real_sdk_post_only_lifecycle_redirect_rejection_and_log_redaction(repo, policy, upstream, monkeypatch, caplog, endpoint_shape, stage, failure):
    import logging

    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", RealMcpClient)
    endpoint = f"https://backend.composio.dev/tool_router/{'v3/' if endpoint_shape == 'versioned' else ''}trs_11111111/mcp"
    if endpoint_shape == "unversioned":
        upstream.mutate = lambda body: {**body, "mcp": {"type": "http", "url": endpoint}}
    caplog.set_level(logging.INFO)
    forwarded = []
    failed = []

    def protocol(request):
        assert request.method == "POST"
        assert request.headers["x-api-key"] == "synthetic-project-key"
        body = json.loads(request.content)
        method = body["method"]
        forwarded.append((str(request.url), method))
        if (stage == "discovery" and method == "tools/list") or (stage == "invocation" and method == "tools/call"):
            failed.append(method)
            if failure == "redirect":
                return httpx.Response(307, headers={"Location": str(request.url)})
            raise httpx.ReadTimeout("synthetic-project-key " + str(request.url))
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "synthetic", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "COMPOSIO_SEARCH_TOOLS", "description": "Synthetic", "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "synthetic result"}], "isError": False}
        else:
            return httpx.Response(202)
        return httpx.Response(200, headers={"mcp-session-id": "synthetic-protocol-session", "content-type": "application/json"}, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    monkeypatch.setattr(sessions, "_mcp_http_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(protocol), **kwargs))
    with actor(A) as runtime:
        wrapper = sessions.composio_tools(runtime.context, policy)[0]
        invocation = wrapper.coroutine(tool_name="COMPOSIO_SEARCH_TOOLS", arguments={}, runtime=runtime)
        if failure:
            with pytest.raises(ToolException) as error:
                await asyncio.wait_for(invocation, 5)
            assert "synthetic-project-key" not in str(error.value) and "https://" not in str(error.value)
            assert len(failed) == 1
        else:
            result = await asyncio.wait_for(invocation, 5)
            assert "synthetic result" in str(result)
    assert forwarded and all(path.endswith("/mcp") for path, _ in forwarded)
    assert all(method != "tools/call" for _, method in forwarded) if stage == "discovery" else True
    assert all(path == endpoint for path, _ in forwarded)
    assert endpoint not in caplog.text and "synthetic-project-key" not in caplog.text
    if failure:
        assert "Composio" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [300, 304, 307, 399])
async def test_response_hook_denies_every_3xx_without_location(status):
    from langchain_core.tools import ToolException

    from deerflow.mcp.composio_sessions import _reject_redirect

    with pytest.raises(ToolException, match="redirect_denied"):
        await _reject_redirect(httpx.Response(status))


@pytest.mark.asyncio
async def test_cancelled_create_is_held_and_cancellation_propagates(repo, policy, monkeypatch):
    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    entered = asyncio.Event()
    requests = []

    async def blocked(request):
        requests.append(request)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(sessions, "_api_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(blocked)))
    with actor(A) as runtime:
        task = asyncio.create_task(sessions.resolve_actor_session(runtime, policy))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ToolException, match="held"):
            await sessions.resolve_actor_session(runtime, policy)
    assert len(requests) == 1
    assert (await repo.get(A))[sessions.SESSION_KEY]["state"] == "creating"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"session_id": "bad/identifier"}, []])
async def test_malformed_create_stays_uncertain_without_replay(repo, policy, monkeypatch, body):
    from langchain_core.tools import ToolException

    from deerflow.mcp import composio_sessions as sessions

    requests = []

    def malformed(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(sessions, "_api_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(malformed)))
    with actor(A) as runtime:
        for _ in range(2):
            with pytest.raises(ToolException, match="held"):
                await sessions.resolve_actor_session(runtime, policy)
    assert len(requests) == 1
    assert (await repo.get(A))[sessions.SESSION_KEY]["state"] == "uncertain"


def test_role_visibility_preserves_public_research_and_never_mutates_cache(policy, monkeypatch):
    from langchain_core.tools import StructuredTool

    from deerflow.mcp import cache
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    async def call():
        return "synthetic"

    public = tag_mcp_tool(StructuredTool.from_function(coroutine=call, name="public_search", description="Synthetic"), server_name="composio-marketing")
    other = tag_mcp_tool(StructuredTool.from_function(coroutine=call, name="unrelated", description="Synthetic"), server_name="unrelated")
    cached = [public, other]
    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_is_cache_stale", lambda: False)
    monkeypatch.setattr(cache, "_mcp_tools_cache", cached)
    for role in ("user", "exec", "admin", "client"):
        with actor(A, role=role) as runtime:
            visible = cache.get_cached_mcp_tools(run_context=runtime.context, extensions_config=policy)
            assert (public in visible) == (role != "client")
            assert other in visible
    assert cache._mcp_tools_cache is cached and cached == [public, other]


@pytest.mark.asyncio
async def test_preferences_api_cannot_read_or_modify_internal_session_key(repo, monkeypatch):
    from fastapi import FastAPI

    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.routers import user_preferences
    from deerflow.mcp.composio_sessions import SESSION_KEY

    await repo.reserve_key(A, SESSION_KEY, {"state": "ready", "session_id": "trs_saved"})

    async def authenticate(request):
        return User(id=UUID(A), email="synthetic@example.com", system_role="user")

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticate)
    monkeypatch.setattr(user_preferences, "_repository", lambda: repo)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(user_preferences.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
        headers = {**auth_headers(A, ORG), "X-Expected-User-Id": A}
        assert (await client.patch("/api/v1/auth/preferences", headers=headers, json={SESSION_KEY: {"state": "ready", "session_id": "trs_foreign"}})).status_code == 422
        result = await client.get("/api/v1/auth/preferences", headers=headers)
        assert result.status_code == 200 and SESSION_KEY not in result.json()
    assert (await repo.get(A))[SESSION_KEY]["session_id"] == "trs_saved"


def test_result_redaction_preserves_safe_tool_metadata(policy):
    from deerflow.mcp.composio_sessions import _safe_result

    result = (
        {
            "tool": "GMAIL_LIST_LABELS",
            "logo": "https://logos.composio.dev/gmail",
            "headers": {"x-api-key": "synthetic-project-key"},
            "nested": ["https://backend.composio.dev/tool_router/v3/trs_secret/mcp"],
            "actual_nested": ["https://backend.composio.dev/tool_router/trs_actual_secret/mcp"],
            "synthetic-project-key": "unsafe field name",
            "https://backend.composio.dev/tool_router/v3/trs_secret/mcp": "unsafe field name",
            "https://backend.composio.dev/tool_router/trs_actual_secret/mcp": "unsafe field name",
        },
        None,
    )
    safe = _safe_result(result, policy)
    assert safe[0]["tool"] == "GMAIL_LIST_LABELS"
    assert safe[0]["logo"] == "https://logos.composio.dev/gmail"
    assert "synthetic-project-key" not in str(safe)
    assert "trs_secret" not in str(safe) and "trs_actual_secret" not in str(safe)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS"])
async def test_envelope_redacts_credential_urls_but_preserves_public_links(repo, policy, upstream, tool_name):
    from deerflow.mcp.composio_sessions import composio_tools

    credential_urls = [
        "https://oauth.example.invalid/callback#access_token=SYNTHETIC_ACCESS_TOKEN",
        "https://oauth.example.invalid/callback#ACCESS%5FToken=SYNTHETIC_ENCODED_TOKEN",
        "https://oauth.example.invalid/callback#/callback?refresh_token=SYNTHETIC_ROUTED_TOKEN",
        "https://oauth.example.invalid/callback#id_token%3DSYNTHETIC_ENCODED_FRAGMENT",
        "https://SYNTHETIC_USER:SYNTHETIC_PASSWORD@oauth.example.invalid/connect",
        "https://SYNTHETIC_USERNAME@oauth.example.invalid/connect",
        "https://:SYNTHETIC_PASSWORD_ONLY@oauth.example.invalid/connect",
        "https://oauth.example.invalid/connect?access_token=SYNTHETIC_QUERY_TOKEN",
        "https://oauth.example.invalid/connect?%61pi%5Fkey=SYNTHETIC_QUERY_KEY",
        "https://backend.composio.dev/tool_router/v3/trs_synthetic/mcp",
        "https://backend.composio.dev/tool_router/trs_synthetic/mcp",
    ]
    public_urls = [
        "https://research.example.invalid/paper?q=connection#results",
        "https://docs.example.invalid/oauth#access_token",
        "https://docs.composio.dev/reference/authenticating-to-composio/project-api-key-permissions",
        "https://public.example.invalid/connect/SYNTHETIC_PUBLIC_PATH",
    ]
    connect_url = "https://connect.example.invalid/connect/SYNTHETIC_BEARER_HANDLE"
    auth_url = "https://identity.example.invalid/authorize/SYNTHETIC_AUTH_HANDLE"
    upstream.result = {
        connect_url: "connection alias before its semantic field",
        "alias": "Follow " + auth_url,
        "metadata": [{"nested": ["Follow " + url], url: "field-name"} for url in credential_urls],
        "connection": {"redirect_url": connect_url, connect_url: "field-name", "docs_url": public_urls[1]},
        "authorization_url": auth_url,
        "citations": public_urls,
        public_urls[0]: "public field-name",
        "tool": "GMAIL_LIST_LABELS",
    }
    with actor(A) as runtime:
        wrapper = composio_tools(runtime.context, policy)[0]
        content, artifact = await wrapper.coroutine(tool_name=tool_name, arguments={}, runtime=runtime)
    rendered = json.dumps((content, artifact))
    for url in credential_urls + [connect_url, auth_url]:
        assert url not in rendered
    assert "SYNTHETIC_ACCESS_TOKEN" not in rendered and "SYNTHETIC_PASSWORD" not in rendered
    assert content["citations"] == public_urls
    assert content["connection"]["docs_url"] == public_urls[1]
    assert content[public_urls[0]] == "public field-name"
    assert content["tool"] == "GMAIL_LIST_LABELS" and artifact is None
    assert len(upstream.calls) == 1 and upstream.calls[0][1].name == tool_name


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS"])
async def test_installed_adapter_json_text_redacts_aliases_across_guarded_envelope(repo, policy, upstream, tool_name):
    from mcp.types import CallToolResult, TextContent

    from deerflow.mcp.composio_sessions import composio_tools

    connect_url = "https://connect.example.invalid/connect/SYNTHETIC_EMBEDDED_BEARER"
    auth_url = "https://identity.example.invalid/authorize/SYNTHETIC_EMBEDDED_AUTH"
    nested_url = "https://identity.example.invalid/consent/SYNTHETIC_NESTED_AUTH"
    public_url = "https://public.example.invalid/connect/SYNTHETIC_PUBLIC_PATH"
    docs_url = "https://docs.composio.dev/reference/authenticating-to-composio/project-api-key-permissions"
    payload = {
        connect_url: "alias before semantic field",
        "alias": "Follow " + auth_url,
        "connection": {"redirect_url": connect_url},
        "authorization_url": auth_url,
        "nested_json": json.dumps({"authorization_url": nested_url, "docs": docs_url}),
        "citations": [public_url, docs_url],
    }
    upstream.convert_result = True
    upstream.result = CallToolResult(
        content=[
            TextContent(type="text", text=f"Useful research: {docs_url}. Connect alias: {connect_url} Nested alias: {nested_url}"),
            TextContent(type="text", text=json.dumps(payload)),
            TextContent(type="text", text="Ordinary prose and a public link: " + public_url),
        ],
        structuredContent={"alias": auth_url, connect_url: "artifact alias", "docs": docs_url},
    )
    with actor(A) as runtime:
        result = await composio_tools(runtime.context, policy)[0].coroutine(tool_name=tool_name, arguments={}, runtime=runtime)
    assert isinstance(result, tuple) and len(result) == 2
    content, artifact = result
    assert isinstance(content, list) and len(content) == 3
    assert all(block["type"] == "text" and isinstance(block["text"], str) for block in content)
    rendered = json.dumps(result)
    assert all(url not in rendered for url in (connect_url, auth_url, nested_url))
    decoded = json.loads(content[1]["text"])
    assert decoded["citations"] == [public_url, docs_url]
    assert json.loads(decoded["nested_json"])["docs"] == docs_url
    assert "Useful research:" in content[0]["text"] and docs_url in content[0]["text"]
    assert content[2]["text"] == "Ordinary prose and a public link: " + public_url
    assert artifact["structured_content"]["docs"] == docs_url
    assert len(upstream.calls) == 1 and upstream.calls[0][1].name == tool_name


def test_result_sanitizer_preserves_plain_response_representations(policy):
    from deerflow.mcp.composio_sessions import _safe_result

    prose = "Useful research: https://docs.example.invalid/topic#results"
    for result in (prose, [prose], (prose, None), ([{"type": "text", "text": prose}], None)):
        assert _safe_result(result, policy) == result


def test_embedded_json_classification_has_a_fail_closed_layer_bound(policy):
    from deerflow.mcp.composio_sessions import ComposioSessionError, _safe_result

    value = {"authorization_url": "https://identity.example.invalid/authorize/SYNTHETIC_DEEP_AUTH"}
    for _ in range(9):
        value = {"nested": json.dumps(value)}
    with pytest.raises(ComposioSessionError, match="result_unavailable"):
        _safe_result((value, None), policy)


@pytest.mark.parametrize("schema", [{"properties": {"synthetic-project-key": {"type": "string"}}}, {"$ref": "#/$defs/synthetic-project-key"}])
def test_structural_schema_rejects_secret_bearing_names(policy, schema):
    from deerflow.mcp.composio_sessions import ComposioSessionError, _structural_schema

    with pytest.raises(ComposioSessionError, match="schema_unavailable"):
        _structural_schema(schema, secret="synthetic-project-key")


@pytest.mark.asyncio
async def test_caller_selection_ids_cannot_choose_another_actor_and_unknown_tool_has_zero_http(repo, policy, upstream):
    from langchain_core.tools import ToolException

    from deerflow.mcp.composio_sessions import composio_tools, resolve_actor_session

    with actor(A, user_id=B, composio_user_id="momobot-foreign", session_id="trs_foreign") as runtime:
        wrapper = composio_tools(runtime.context, policy)[0]
        with pytest.raises(ToolException, match="tool_denied"):
            await wrapper.coroutine(tool_name="COMPOSIO_MANAGE_CONNECTIONS", arguments={}, runtime=runtime)
        assert upstream.requests == []
        reference = await resolve_actor_session(runtime, policy)
    assert reference.actor_user_id == A
    assert json.loads(upstream.requests[0].content)["user_id"] == f"momobot-{A}"


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", ["bound", "current", "unrelated"])
async def test_before_io_classifier_uses_validated_exact_customer_binding(repo, policy, upstream, relation):
    from langchain_core.tools import ToolException
    from sqlalchemy import update

    from app.gateway.invitation_policy import validate_customer_workspace
    from deerflow.mcp.composio_sessions import resolve_actor_session

    issuer, agency_storage, bound_id, other_id = [str(UUID(int=value)) for value in (901, 902, 903, 904)]
    agency = private_organization_id(agency_storage)
    async with repo.sessions() as session, session.begin():
        session.add_all([UserRow(id=issuer, email="issuer@example.test", system_role="admin"), UserRow(id=agency_storage, email="agency-storage@example.test", system_role="user")])
        session.add(OrganizationRow(id=agency, slug="synthetic-agency", name="Synthetic Agency", storage_user_id=agency_storage, status="active"))
        session.add_all([OrganizationMemberRow(organization_id=organization, user_id=issuer, role="owner", status="active") for organization in (agency, ORG)])
        session.add_all([ClientRow(id=client_id, organization_id=agency, display_name="Synthetic Client", status="active") for client_id in (bound_id, other_id)])
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG).values(customer_client_id=bound_id))
        session.add(ClientAssignmentRow(client_id=other_id if relation == "unrelated" else bound_id, organization_id=ORG if relation == "current" else agency, user_id=A, role="client_contact"))
        await session.flush()
        canonical = await validate_customer_workspace(session, organization=await session.get(OrganizationRow, ORG), actor_id=issuer)
        assert canonical.id == bound_id and canonical.organization_id == agency
    with actor(A) as runtime:
        if relation == "unrelated":
            assert (await resolve_actor_session(runtime, policy)).actor_user_id == A
            assert [request.method for request in upstream.requests] == ["POST", "GET"]
        else:
            with pytest.raises(ToolException):
                await resolve_actor_session(runtime, policy)
            assert upstream.requests == []
