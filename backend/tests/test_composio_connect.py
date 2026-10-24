"""Offline actor-bound guided connect and one-attempt callback contracts."""

import asyncio
import json
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import update
from test_composio_me_sessions import ORG, STORAGE, A, B, actor, auth_headers, response
from test_composio_me_sessions import policy as policy
from test_composio_me_sessions import repo as repo
from test_composio_me_sessions import upstream as upstream

from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.persistence.user.model import UserRow


@pytest_asyncio.fixture
async def connect_world(repo, monkeypatch, upstream):
    from app.gateway.routers import composio_connect, user_preferences
    from deerflow.mcp import composio_sessions

    monkeypatch.setenv("COMPOSIO_C_TEST_KEY", "synthetic-c-project-key")
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    config = ExtensionsConfig.model_validate(
        {
            "composioMe": {
                "enabled": True,
                "project_key_env": "COMPOSIO_C_TEST_KEY",
                "toolkits": ["gmail"],
                "connect": {"enabled": True, "callback_url": "https://momo.example.test/api/integrations/callback", "auth_configs": {"gmail": "ac_synthetic"}},
            }
        }
    )
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    state = SimpleNamespace(requests=[], connected=False, failure=None, mutate=None, no_auth=False)
    state.mcp = upstream
    upstream.owners["trs_synthetic"] = A
    state.account = {
        "id": "ca_synthetic",
        "user_id": f"momobot-{A}",
        "toolkit": {"slug": "gmail"},
        "status": "ACTIVE",
        "is_disabled": False,
        "auth_config": {"id": "ac_synthetic", "is_disabled": False},
        "experimental": {"account_type": "PRIVATE"},
        "state": {"val": {"access_token": "SYNTHETIC_DISCARD"}},
        "data": {"token": "SYNTHETIC_DISCARD"},
        "params": {"secret": "SYNTHETIC_DISCARD"},
    }
    state.accounts = {"gmail": state.account}

    def api(request):
        state.requests.append(request)
        assert request.headers["x-api-key"] == "synthetic-c-project-key"
        if state.failure and request.url.path.endswith("/link"):
            raise state.failure
        if request.url.path == "/api/v3.1/connected_accounts":
            assert request.url.params.get("user_ids") == f"momobot-{A}"
            data = {"items": [state.accounts[request.url.params["toolkit_slugs"]]] if state.connected else [], "next_cursor": None}
        elif request.url.path.startswith("/api/v3.1/connected_accounts/"):
            data = next(account for account in state.accounts.values() if account["id"] == request.url.path.rsplit("/", 1)[-1]) if request.url.path.endswith("ca_slack") else state.account
        elif request.url.path.startswith("/api/v3.1/tools/"):
            data = {"slug": request.url.path.rsplit("/", 1)[-1], "toolkit": {"slug": "gmail"}, "no_auth": state.no_auth}
        elif request.url.path.endswith("/link"):
            body = json.loads(request.content)
            assert body["callback_url"].startswith(config.composio_me.connect.callback_url + "?handle=")
            assert set(body) == {"toolkit", "callback_url"}
            data = {
                "connected_account_id": state.accounts[body["toolkit"]]["id"],
                "redirect_url": "https://app.composio.dev/link/SYNTHETIC_LINK_CAP?token=SYNTHETIC_LINK_TOKEN",
                "link_token": "SYNTHETIC_LINK_TOKEN",
                "experimental": {"account_type": "PRIVATE"},
            }
        elif request.method == "POST":
            assert json.loads(request.content)["user_id"] == f"momobot-{A}"
            data = {"session_id": "trs_synthetic"}
        else:
            data = response("trs_synthetic", config={"user_id": f"momobot-{A}", "toolkits": {"enabled": config.composio_me.toolkits}, "auth_configs": config.composio_me.connect.auth_configs})
        return httpx.Response(200, json=state.mutate(data) if state.mutate else data)

    monkeypatch.setattr(composio_sessions, "_api_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(api)))

    async def authenticate(request):
        identity = request.cookies["access_token"]
        async with repo.sessions() as session:
            row = await session.get(UserRow, identity)
        return User(id=UUID(identity), email="synthetic@example.com", system_role=row.system_role)

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticate)
    monkeypatch.setattr(user_preferences, "_repository", lambda: repo)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(composio_connect.router)
    app.include_router(user_preferences.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://momo.example.test") as client:
        yield state, repo, client, config


@pytest_asyncio.fixture
async def retry_world(connect_world, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway import deps, services
    from app.gateway.routers import thread_runs
    from deerflow.config.app_config import AppConfig
    from deerflow.mcp.composio_sessions import bind_composio_context, reset_composio_context
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import DisconnectMode, RunManager, RunRecord, RunStatus
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge
    from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER_KEY, PRIVATE_MCP_SESSION_CONTEXT_KEY

    state, repo, client, config = connect_world
    app = client._transport.app
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}}})
    monkeypatch.setattr(services, "get_app_config", lambda: app_config)
    monkeypatch.setattr(deps, "get_config", lambda: app_config)
    store = InMemoryStore()
    manager = RunManager(store=MemoryRunStore())
    app.state.store = store
    app.state.thread_store = MemoryThreadMetaStore(store)
    app.state.checkpointer = InMemorySaver()
    app.state.run_manager = manager
    app.state.run_store = manager._store
    app.state.run_event_store = DbRunEventStore(repo.sessions)
    app.state.stream_bridge = MemoryStreamBridge()
    app.include_router(thread_runs.router)
    with actor(A):
        await app.state.thread_store.create("thread", user_id=STORAGE)
        source = RunRecord(run_id="run", thread_id="thread", assistant_id=None, status=RunStatus.success, on_disconnect=DisconnectMode.continue_, user_id=STORAGE)
        manager._runs["run"] = source
        await app.state.run_event_store.put(thread_id="thread", run_id="run", event_type="run.end", category="outputs", content={}, metadata={"status": "success"})
    state.admissions = []
    state.results = []
    state.worker_modes = []

    async def execute_graph(bridge, run_manager, record, *, agent_factory, graph_input, config, **kwargs):
        state.worker_modes.append(kwargs.get("_allow_goal_continuation", True))
        # Exercise the real admission's opaque markers, exact graph and guards;
        # the general worker lifecycle itself is already covered by the B suite.
        token = bind_composio_context(config["context"], thread_id=record.thread_id, run_id=record.run_id)
        runtime_context = {**config["context"], "thread_id": record.thread_id, "run_id": record.run_id}
        runtime_context.pop(AUTHENTICATED_CONTEXT_MARKER_KEY, None)
        runtime_context.pop(PRIVATE_MCP_SESSION_CONTEXT_KEY, None)
        config = {**config, "context": runtime_context}
        try:
            from langgraph.graph import END, START, StateGraph

            from deerflow.agents.thread_state import get_thread_state_schema
            from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode

            mode = getattr(app.state, "checkpoint_channel_mode", "full")
            inject_checkpoint_mode(config, mode)

            class ExtendedState(get_thread_state_schema(mode)):
                unrelated_channel: dict

            seed = StateGraph(ExtendedState)
            seed.add_node("seed", lambda state: {})
            seed.add_edge(START, "seed")
            seed.add_edge("seed", END)
            await seed.compile(checkpointer=app.state.checkpointer).ainvoke({"messages": [], "unrelated_channel": {"value": "preserved"}}, config)
            state.admissions.append(record)
            graph = agent_factory(config=config, app_config=app_config)
            graph.checkpointer = app.state.checkpointer
            state.results.append(await graph.ainvoke(graph_input, config, context=runtime_context))
            checkpoint = await app.state.checkpointer.aget_tuple(config)
            assert checkpoint.checkpoint["channel_values"]["unrelated_channel"] == {"value": "preserved"}
            await run_manager.set_status(record.run_id, RunStatus.success)
        finally:
            reset_composio_context(token)

    monkeypatch.setattr(services, "run_agent", execute_graph)
    yield state, repo, client, config
    tasks = [record.task for record in manager._runs.values() if record.task is not None]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def headers(client, actor_id=A, handle=None, organization=ORG):
    result = auth_headers(actor_id, organization)
    if handle:
        nonce = client.cookies.get("momo_connect_" + handle)
        if nonce:
            result["Cookie"] += "; momo_connect_" + handle + "=" + nonce
    return result


async def opened(client):
    created = await client.post("/api/integrations/connect", headers=headers(client), json={"toolkit": "gmail"})
    assert created.status_code == 200, created.text
    handle = created.json()["handle"]
    result = await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))
    assert result.status_code == 302, result.text
    return handle


def callback_params(handle, account="ca_synthetic"):
    return {"handle": handle, "connected_account_id": account, "status": "success"}


def test_connect_operator_policy_is_disabled_and_fixed_by_default():
    from deerflow.config.extensions_config import ComposioConnectConfig, ExtensionsConfig

    assert not ExtensionsConfig().composio_me.connect.enabled
    policy = ComposioConnectConfig(callback_url="https://momo.example.test/api/integrations/callback", auth_configs={"gmail": "ac_synthetic"})
    assert policy.authorization_origins == ["https://app.composio.dev"]
    assert policy.ttl_seconds == 600
    for callback in ("http://momo.example.test/api/integrations/callback", "https://momo.example.test/api/integrations/callback?target=x", "https://user@momo.example.test/api/integrations/callback", "https://momo.example.test/elsewhere"):
        with pytest.raises(ValidationError):
            ComposioConnectConfig(callback_url=callback)
    with pytest.raises(ValidationError):
        ComposioConnectConfig(authorization_origins=["https://*.example.test"])
    with pytest.raises(ValidationError):
        ComposioConnectConfig(auth_configs={"unreviewed": "ac_synthetic"})


@pytest.mark.asyncio
async def test_browser_connect_open_callback_status_and_private_preferences(connect_world, caplog):
    state, repo, client, config = connect_world
    caplog.set_level("INFO")
    handle = await opened(client)
    assert len([request for request in state.requests if request.url.path.endswith("/link")]) == 1
    assert (await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))).status_code == 409
    state.connected = True
    result = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert result.status_code == 200 and result.json()["status"] == "connected", result.text
    before = len(state.requests)
    duplicate = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert duplicate.json() == result.json() and len(state.requests) == before
    status = await client.get("/api/integrations/status", headers=headers(client))
    assert status.json()["toolkits"] == [{"toolkit": "gmail", "connected": True, "connectable": False, "reason": None}]
    private = await client.get("/api/v1/auth/preferences", headers={**headers(client), "X-Expected-User-Id": A})
    assert private.status_code == 200 and "__c_" not in private.text
    assert (await client.patch("/api/v1/auth/preferences", headers={**headers(client), "X-Expected-User-Id": A}, json={"__c_" + handle: {"state": "complete"}})).status_code == 422
    rendered = result.text + status.text + private.text + caplog.text
    assert all(secret not in rendered for secret in ("SYNTHETIC_LINK_CAP", "SYNTHETIC_LINK_TOKEN", "SYNTHETIC_DISCARD", "synthetic-c-project-key", client.cookies.get("momo_connect_" + handle)))


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["actor", "org", "nonce", "account", "expired", "duplicate_query"])
async def test_callback_tampering_has_zero_provider_requests(connect_world, tamper):
    from deerflow.mcp.composio_sessions import ConnectManager
    from deerflow.persistence.organizations.identity import private_organization_id

    state, repo, client, config = connect_world
    handle = await opened(client)
    params, head = callback_params(handle), headers(client, handle=handle)
    if tamper == "actor":
        head = headers(client, B, handle)
    elif tamper == "org":
        head = headers(client, A, handle, private_organization_id(A))
    elif tamper == "nonce":
        head = headers(client)
    elif tamper == "account":
        params["connected_account_id"] = "ca_foreign"
    elif tamper == "duplicate_query":
        params = [*params.items(), ("connected_account_id", "ca_foreign")]
    else:
        value = await repo.get_key(A, ConnectManager.attempt_key(handle))
        await repo.patch(A, {ConnectManager.attempt_key(handle): {**value, "expires_at": time.time() - 1}})
    state.requests.clear()
    result = await client.get("/api/integrations/callback", params=params, headers=head)
    assert result.status_code in {400, 403, 404, 409} and state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["user_id", "toolkit", "status", "disabled", "auth_disabled", "auth_config", "shared", "id"])
async def test_callback_requires_exact_active_private_account_metadata(connect_world, field):
    state, repo, client, config = connect_world
    handle = await opened(client)
    state.connected = True
    if field == "user_id":
        state.account["user_id"] = f"momobot-{B}"
    elif field == "toolkit":
        state.account["toolkit"] = {"slug": "slack"}
    elif field == "status":
        state.account["status"] = "EXPIRED"
    elif field == "disabled":
        state.account["is_disabled"] = True
    elif field == "auth_disabled":
        state.account["auth_config"]["is_disabled"] = True
    elif field == "auth_config":
        state.account["auth_config"]["id"] = "ac_foreign"
    elif field == "shared":
        state.account["experimental"]["account_type"] = "SHARED"
    else:
        state.account["id"] = "ca_foreign"
    result = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert result.status_code == 409
    count = len(state.requests)
    assert (await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))).status_code == 409
    assert len(state.requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["membership", "contact"])
async def test_callback_rechecks_current_actor_before_provider_lookup(connect_world, change):
    from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
    from deerflow.persistence.organizations.model import OrganizationMemberRow

    state, repo, client, config = connect_world
    handle = await opened(client)
    async with repo.sessions() as session, session.begin():
        if change == "membership":
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == A, OrganizationMemberRow.organization_id == ORG).values(status="revoked"))
        else:
            session.add(ClientRow(id="callback-contact", organization_id=ORG, display_name="Synthetic", status="active"))
            session.add(ClientAssignmentRow(client_id="callback-contact", organization_id=ORG, user_id=A, role="client_contact"))
    state.requests.clear()
    result = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert result.status_code in {403, 404} and state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["ambiguous", "cursor", "cancelled"])
async def test_callback_verification_unknown_or_ambiguous_is_held_without_replay(connect_world, monkeypatch, failure):
    from deerflow.mcp.composio_sessions import ConnectManager

    state, repo, client, config = connect_world
    handle = await opened(client)
    state.connected = True
    if failure == "cancelled":
        original = ConnectManager.request

        async def cancel_lookup(self, method, path, **kwargs):
            if path.endswith("/ca_synthetic"):
                raise asyncio.CancelledError
            return await original(self, method, path, **kwargs)

        monkeypatch.setattr(ConnectManager, "request", cancel_lookup)
        with actor(A):
            from deerflow.mcp.composio_sessions import composio_browser_origin

            with composio_browser_origin(), pytest.raises(asyncio.CancelledError):
                await ConnectManager(config).callback(handle, client.cookies.get("momo_connect_" + handle), "ca_synthetic")
        monkeypatch.setattr(ConnectManager, "request", original)
    else:
        state.mutate = lambda value: {**value, "items": [state.account, {**state.account, "id": "ca_other"}]} if "items" in value and failure == "ambiguous" else {**value, "next_cursor": "cursor_unverified"} if "items" in value else value
        result = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
        assert result.status_code == 409
    before = len(state.requests)
    duplicate = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert duplicate.status_code == 409 and len(state.requests) == before


@pytest.mark.asyncio
async def test_concurrent_first_connect_one_link_and_uncertain_creation_never_replays(connect_world):
    state, repo, client, config = connect_world
    state.failure = httpx.ReadTimeout("synthetic uncertain")
    results = await asyncio.gather(*(client.post("/api/integrations/connect", json={"toolkit": "gmail"}, headers=headers(client)) for _ in range(2)))
    assert all(result.status_code == 409 for result in results)
    assert len([request for request in state.requests if request.url.path.endswith("/link")]) == 1
    state.failure = None
    assert (await client.post("/api/integrations/connect", json={"toolkit": "gmail"}, headers=headers(client))).status_code == 409
    assert len([request for request in state.requests if request.url.path.endswith("/link")]) == 1
    status = await client.get("/api/integrations/status", headers=headers(client))
    assert status.json()["toolkits"] == [{"toolkit": "gmail", "connected": False, "connectable": False, "reason": "connect_attempt_held"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("toolkit", ["metaads", "fireflies", "composio_search", "unreviewed"])
async def test_unsupported_or_auth_free_toolkit_never_creates_link(connect_world, toolkit):
    state, repo, client, config = connect_world
    config.composio_me.toolkits = ["gmail", "metaads", "fireflies", "composio_search"]
    result = await client.post("/api/integrations/connect", json={"toolkit": toolkit}, headers=headers(client))
    assert result.status_code == 409 and state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://evil.example.test/link", "https://user@app.composio.dev/link", "https://app.composio.dev:443/link", "https://app.composio.dev/link#secret"])
async def test_unapproved_auth_redirect_is_held_without_export(connect_world, origin):
    state, repo, client, config = connect_world
    state.mutate = lambda value: {**value, "redirect_url": origin} if "redirect_url" in value else value
    result = await client.post("/api/integrations/connect", json={"toolkit": "gmail"}, headers=headers(client))
    assert result.status_code == 409 and origin not in result.text


def test_untrusted_state_metadata_cannot_manufacture_upload_reservation():
    from app.gateway.services import _canonical_run_record_input, normalize_input

    raw = {"messages": [{"role": "user", "content": "Hello"}], "metadata": {"_deerflow_upload_reservation": {"actor": B}, "public_label": "kept"}}
    normalized = normalize_input(raw)
    assert normalized["metadata"] == {"public_label": "kept"}
    assert _canonical_run_record_input(raw, normalized)["metadata"] == {"public_label": "kept"}
    assert "_deerflow_upload_reservation" in raw["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [True, False])
@pytest.mark.parametrize("checkpoint_mode", ["full", "delta"])
async def test_exact_no_execution_callback_retries_once_via_run_manager_and_write_guard(retry_world, write, checkpoint_mode):
    from deerflow.mcp.composio_sessions import composio_tools

    state, repo, client, config = retry_world
    client._transport.app.state.checkpoint_channel_mode = checkpoint_mode
    arguments = {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"recipient_email": "synthetic@example.com", "body": "Exact draft"}}]} if write else {"tools": [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}]}
    with actor(A) as runtime:
        card, _ = await composio_tools(runtime.context, config)[0].coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments=arguments, runtime=runtime)
    assert card["no_execution"] and state.mcp.calls == []
    handle = card["connect"]["handle"]
    assert (await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))).status_code == 302
    state.connected = True
    result = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert result.status_code == 200, result.text
    assert result.json()["retry"]["state"] == "submitted"
    manager = client._transport.app.state.run_manager
    admitted = await manager.get(result.json()["retry"]["run_id"], user_id=STORAGE)
    await asyncio.wait_for(admitted.task, 5)
    assert len(state.admissions) == 1 and len(state.mcp.calls) == (0 if write else 1)
    message = state.results[0]["messages"][-1]
    assert ("pending_approval" in message.content) is write
    assert admitted.kwargs["input"]["messages"][-1]["tool_calls"][0]["args"]["arguments"] == arguments
    assert admitted.metadata["original_tool_call_id"] == "call"
    count = len(state.requests)
    duplicate = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert duplicate.json() == result.json() and len(state.requests) == count and len(state.admissions) == 1
    events = await client.get("/api/threads/thread/runs/run/events", headers=headers(client), params={"event_types": "composio.connected"})
    assert events.status_code == 200, events.text
    assert events.json()[0]["content"] == {"handle": handle, "toolkit": "gmail", "source_run_id": "run", "tool_call_id": "call"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [[{"tool_slug": "COMPOSIO_SEARCH_WEB", "arguments": {"query": "public"}}], [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}, {"tool_slug": "GMAIL_GET_PROFILE", "arguments": {}}]])
async def test_public_or_batch_calls_never_acquire_connect_retry_intent(connect_world, tools):
    from deerflow.mcp.composio_sessions import ConnectManager

    state, repo, client, config = connect_world
    with actor(A) as runtime:
        assert await ConnectManager(config, runtime=runtime).preflight("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": tools}) is None
    assert state.requests == []


@pytest.mark.asyncio
async def test_missing_metadata_read_scope_does_not_create_attempt_or_retry(connect_world, monkeypatch):
    from deerflow.mcp.composio_sessions import ComposioSessionError, ConnectManager

    state, repo, client, config = connect_world

    async def denied(*args, **kwargs):
        raise ComposioSessionError("composio_session_request_failed")

    monkeypatch.setattr(ConnectManager, "request", denied)
    with actor(A) as runtime, pytest.raises(ComposioSessionError, match="metadata_unavailable"):
        await ConnectManager(config, runtime=runtime).preflight("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}]})
    assert not await repo.get(A) and state.mcp.calls == []


@pytest.mark.asyncio
async def test_browser_cookie_workspace_and_parallel_per_handle_nonce(connect_world):
    from deerflow.persistence.organizations.identity import private_organization_id

    state, repo, client, config = connect_world
    config.composio_me.toolkits.append("slack")
    config.composio_me.connect.auth_configs["slack"] = "ac_slack"
    state.accounts["slack"] = {**state.account, "id": "ca_slack", "toolkit": {"slug": "slack"}, "auth_config": {"id": "ac_slack", "is_disabled": False}}
    client.cookies.set("access_token", A, domain="momo.example.test", path="/")
    client.cookies.set("deerflow_workspace", ORG, domain="momo.example.test", path="/")
    handles = []
    for toolkit in ("gmail", "slack"):
        created = await client.post("/api/integrations/connect", json={"toolkit": toolkit})
        assert created.status_code == 200, created.text
        handles.append(created.json()["handle"])
        assert (await client.get(f"/api/integrations/connect/{handles[-1]}/open")).status_code == 302
    assert client.cookies.get("momo_connect_" + handles[0]) != client.cookies.get("momo_connect_" + handles[1])
    client.cookies.set("deerflow_workspace", private_organization_id(A), domain="momo.example.test", path="/")
    before = len(state.requests)
    assert (await client.get("/api/integrations/callback", params=callback_params(handles[0]))).status_code == 404
    assert len(state.requests) == before
    client.cookies.set("deerflow_workspace", ORG, domain="momo.example.test", path="/")
    state.connected = True
    for handle, account in zip(handles, ("ca_synthetic", "ca_slack"), strict=True):
        assert (await client.get("/api/integrations/callback", params=callback_params(handle, account))).json()["status"] == "connected"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["client", "revoked", "contact", "missing_key", "legacy"])
async def test_current_actor_policy_denials_precede_all_provider_io(connect_world, monkeypatch, change):
    from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
    from deerflow.persistence.organizations.model import OrganizationMemberRow

    state, repo, client, config = connect_world
    if change == "missing_key":
        monkeypatch.delenv("COMPOSIO_C_TEST_KEY")
    elif change == "legacy":
        from deerflow.config.extensions_config import McpServerConfig

        config.mcp_servers["composio-sean"] = McpServerConfig(type="http", url="https://legacy.example.test", user_auth={"users": {A: "SYNTHETIC_UNREAD"}})
    else:
        async with repo.sessions() as session, session.begin():
            if change == "client":
                await session.execute(update(UserRow).where(UserRow.id == A).values(system_role="client"))
            elif change == "revoked":
                await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == A, OrganizationMemberRow.organization_id == ORG).values(status="revoked"))
            else:
                session.add(ClientRow(id="synthetic-client", organization_id=ORG, display_name="Synthetic", status="active"))
                session.add(ClientAssignmentRow(client_id="synthetic-client", organization_id=ORG, user_id=A, role="client_contact"))
    result = await client.post("/api/integrations/connect", json={"toolkit": "gmail"}, headers=headers(client))
    assert result.status_code in {403, 409} and state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["pat", "internal", "auth_disabled"])
async def test_non_browser_origin_has_zero_provider_io(connect_world, origin):
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    state, repo, client, config = connect_world

    async def stamp(request, call_next):
        request.state.auth_source = origin
        return await call_next(request)

    client._transport.app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=stamp))
    result = await client.post("/api/integrations/connect", json={"toolkit": "gmail"}, headers=headers(client))
    assert result.status_code == 403 and state.requests == []


@pytest.mark.asyncio
async def test_callback_race_one_lookup_and_unknown_dispatch_stays_held(retry_world, monkeypatch, caplog):
    from app.gateway.routers import thread_runs
    from deerflow.mcp.composio_sessions import composio_tools

    state, repo, client, config = retry_world
    with actor(A) as runtime:
        card, _ = await composio_tools(runtime.context, config)[0].coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments={"tools": [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}]}, runtime=runtime)
    handle = card["connect"]["handle"]
    assert (await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))).status_code == 302

    async def unknown(*args, **kwargs):
        raise httpx.ReadTimeout("https://app.composio.dev/link/SYNTHETIC_HIDDEN_TOKEN")

    monkeypatch.setattr(thread_runs, "start_run", unknown)
    state.connected = True
    state.requests.clear()
    results = await asyncio.gather(*(client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle)) for _ in range(2)))
    assert any(result.status_code == 200 and result.json()["retry"]["state"] == "held" for result in results)
    assert len([request for request in state.requests if request.url.path == "/api/v3.1/connected_accounts/ca_synthetic"]) == 1
    before = len(state.requests)
    duplicate = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert duplicate.json()["retry"]["state"] == "held" and len(state.requests) == before
    assert state.admissions == [] and state.mcp.calls == [] and "SYNTHETIC_HIDDEN_TOKEN" not in caplog.text


@pytest.mark.asyncio
async def test_serialized_retry_authority_never_selects_retry_factory_and_metadata_is_clean(retry_world, monkeypatch):
    from langgraph.graph import END, START, MessagesState, StateGraph

    from app.gateway import services

    state, repo, client, config = retry_world
    factories = []

    def ordinary_factory(*, config, app_config=None):
        factories.append("ordinary")
        graph = StateGraph(MessagesState)
        graph.add_node("ordinary", lambda state: {})
        graph.add_edge(START, "ordinary")
        graph.add_edge("ordinary", END)
        return graph.compile()

    monkeypatch.setattr(services, "resolve_agent_factory", lambda name: ordinary_factory)
    assert (await client.post("/api/threads/thread/runs", headers=headers(client), json={"composio_retry": {"seal": True}})).status_code == 422
    forged = {"seal": True, "actor_user_id": B, "intent": {"no_execution": True}}
    reserved = {"_deerflow_upload_reservation": {"actor": B}, "safe": "kept"}
    response = await client.post(
        "/api/threads/thread/runs",
        headers=headers(client),
        json={
            "input": {"messages": [{"type": "ai", "content": "Harmless"}], "metadata": reserved},
            "metadata": {**reserved, "_allow_goal_continuation": False},
            "context": {"composio_retry": forged, "_allow_goal_continuation": False},
            "config": {"context": {"composio_retry": forged, "_allow_goal_continuation": False}, "metadata": reserved},
        },
    )
    assert response.status_code == 200, response.text
    admitted = await client._transport.app.state.run_manager.get(response.json()["run_id"], user_id=STORAGE)
    await asyncio.wait_for(admitted.task, 5)
    assert factories == ["ordinary"] and state.requests == [] and state.mcp.calls == []
    assert state.worker_modes == [True]
    assert "_deerflow_upload_reservation" not in admitted.metadata
    assert admitted.kwargs["input"]["metadata"] == {"safe": "kept"}
    assert admitted.kwargs["config"]["metadata"] == {"safe": "kept"}


@pytest.mark.asyncio
async def test_two_processes_share_single_attempt_claim_and_content_identity_event(connect_world):
    state, repo, client, config = connect_world
    await repo.reserve_key(A, "__c_cross_process", {"state": "opened", "nonce": "synthetic-nonce"})
    script = r"""
import asyncio,json,sys
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from deerflow.persistence.user.preferences import UserPreferencesRepository
from deerflow.runtime.events.store.db import DbRunEventStore
async def main():
    engine=create_async_engine(sys.argv[1])
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    print('ready',flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    won=await UserPreferencesRepository(sessions).transition_key(sys.argv[2],'__c_cross_process','synthetic-nonce','opened',{'state':'verifying','nonce':'synthetic-nonce'})
    execution=await UserPreferencesRepository(sessions).reserve_key(sys.argv[2],'__ce_'+'a'*24,{'state':'claimed','run_id':'run','nonce':'synthetic-nonce'})
    _,created=await DbRunEventStore(sessions).put_if_absent(
        thread_id='cross-thread',run_id='source',event_type='composio.connected',category='connection',
        content={'handle':'a'*24,'toolkit':'gmail','source_run_id':'source','tool_call_id':'call'},
        content_identity={'handle':'a'*24})
    print(json.dumps({'claim':won,'execution':execution,'event':created}),flush=True)
    await engine.dispose()
asyncio.run(main())
"""

    def race():
        processes = [subprocess.Popen([sys.executable, "-c", script, str(repo.sessions.kw["bind"].url), A], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            assert all(process.stdout.readline().strip() == "ready" for process in processes)
            for process in processes:
                process.stdin.write("go\n")
                process.stdin.flush()
            outputs = [process.communicate(timeout=20) for process in processes]
            assert all(process.returncode == 0 for process in processes), outputs
            return [json.loads(output) for output, _ in outputs]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.communicate(input="go\n", timeout=20)

    values = await asyncio.to_thread(race)
    assert sum(value["claim"] for value in values) == 1
    assert sum(value["execution"] for value in values) == 1
    assert sum(value["event"] for value in values) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_args", [{"headers": {"Authorization": "SYNTHETIC_FORBIDDEN"}}, {"query": "https://example.com/?access_token=SYNTHETIC_FORBIDDEN"}])
async def test_original_credential_arguments_rejected_before_connect_io_or_storage(connect_world, caplog, secret_args):
    from deerflow.mcp.composio_sessions import ComposioSessionError, composio_tools

    state, repo, client, config = connect_world
    caplog.set_level("INFO")
    with actor(A) as runtime, pytest.raises(ComposioSessionError, match="call_failed"):
        await composio_tools(runtime.context, config)[0].coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments={"tools": [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": secret_args}]}, runtime=runtime)
    assert state.requests == [] and state.mcp.calls == [] and not await repo.get(A)
    assert "SYNTHETIC_FORBIDDEN" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["open", "callback"])
async def test_current_toolkit_revocation_blocks_existing_attempt_before_io(connect_world, stage):
    state, repo, client, config = connect_world
    created = await client.post("/api/integrations/connect", headers=headers(client), json={"toolkit": "gmail"})
    handle = created.json()["handle"]
    if stage == "callback":
        assert (await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))).status_code == 302
    config.composio_me.toolkits = ["slack"]  # The old Gmail auth-config remains configured.
    state.connected = True
    state.requests.clear()
    result = (
        await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client)) if stage == "open" else await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    )
    assert result.status_code == 409 and "location" not in result.headers
    assert state.requests == [] and state.mcp.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["batch", "public", "search", "schemas"])
async def test_all_argument_shapes_reject_credentials_before_session_state(connect_world, variant, caplog):
    from deerflow.mcp.composio_sessions import ComposioSessionError, composio_tools

    state, repo, client, config = connect_world
    secret = {"headers": {"Authorization": "SYNTHETIC_BOUNDARY_FORBIDDEN"}}
    if variant == "batch":
        name, arguments = "COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": secret}, {"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}]}
    elif variant == "public":
        name, arguments = "COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "COMPOSIO_SEARCH_WEB", "arguments": secret}]}
    elif variant == "search":
        name, arguments = "COMPOSIO_SEARCH_TOOLS", {"queries": [{"use_case": "synthetic"}], **secret}
    else:
        name, arguments = "COMPOSIO_GET_TOOL_SCHEMAS", {"tool_slugs": ["GMAIL_FETCH_EMAILS"], **secret}
    with actor(A) as runtime, pytest.raises(ComposioSessionError, match="call_failed"):
        await composio_tools(runtime.context, config)[0].coroutine(tool_name=name, arguments=arguments, runtime=runtime)
    assert state.requests == [] and state.mcp.calls == [] and not await repo.get(A)
    assert "SYNTHETIC_BOUNDARY_FORBIDDEN" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_mode", ["full", "delta"])
@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize("failure", [None, "timeout", "cancel"])
async def test_real_worker_retry_preserves_goal_without_model_and_cannot_reenter(retry_world, monkeypatch, checkpoint_mode, write, failure):
    from contextvars import copy_context

    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.graph import END, START, StateGraph

    from app.gateway import services
    from deerflow.agents.thread_state import get_thread_state_schema
    from deerflow.mcp.composio_sessions import ComposioRetry, ComposioSessionError, composio_tools
    from deerflow.runtime.goal import GoalEvaluation, build_goal_state, read_thread_goal
    from deerflow.runtime.runs import worker

    state, repo, client, config = retry_world
    app = client._transport.app
    app.state.checkpoint_channel_mode = checkpoint_mode
    monkeypatch.setattr(services, "run_agent", worker.run_agent)
    reached, captured = [], []

    def model(**kwargs):
        reached.append("model")
        return object()

    async def evaluate(*args, **kwargs):
        reached.append("evaluate")
        done = reached.count("evaluate") > 1
        return GoalEvaluation(satisfied=done, blocker="none" if done else "goal_not_met_yet", reason="Synthetic", evidence_summary="No provider")

    monkeypatch.setattr(worker, "create_goal_evaluator_model", model)
    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    entered = asyncio.Event()
    if failure:

        async def uncertain(request, handler):
            await handler(request)
            if failure == "cancel":
                entered.set()
                await asyncio.Future()  # The host cancels the actual worker after entry.
            raise httpx.ReadTimeout("Synthetic unknown outcome")

        state.mcp.interceptor = uncertain
    factory = ComposioRetry.factory

    def capture(self, *, config, app_config=None):
        graph = factory(self, config=config, app_config=app_config)
        saved = {**config, "configurable": {**config.get("configurable", {})}, "context": {**config["context"]}}
        captured.append((self, graph, saved, copy_context()))
        return graph

    monkeypatch.setattr(ComposioRetry, "factory", capture)
    goal = build_goal_state("Finish the synthetic task", max_continuations=2)
    seed = StateGraph(get_thread_state_schema(checkpoint_mode))
    seed.add_node("seed", lambda state: {})
    seed.add_edge(START, "seed")
    seed.add_edge("seed", END)
    await seed.compile(checkpointer=app.state.checkpointer).ainvoke(
        {"messages": [HumanMessage(content="Please finish this task."), AIMessage(content="Connect Gmail so I can continue.")], "goal": goal}, {"configurable": {"thread_id": "thread", "checkpoint_ns": ""}}
    )
    with actor(A):
        await app.state.run_event_store.put(thread_id="thread", run_id="run", event_type="human_message", category="message", content="Please finish this task.")
    with actor(A) as runtime:
        arguments = {"tools": [{"tool_slug": "GMAIL_SEND_EMAIL" if write else "GMAIL_LIST_LABELS", "arguments": {"body": "Exact synthetic draft"} if write else {}}]}
        card, _ = await composio_tools(runtime.context, config)[0].coroutine(tool_name="COMPOSIO_MULTI_EXECUTE_TOOL", arguments=arguments, runtime=runtime)
    handle = card["connect"]["handle"]
    assert (await client.get(f"/api/integrations/connect/{handle}/open", headers=headers(client))).status_code == 302
    state.connected = True
    reply = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert reply.status_code == 200 and reply.json()["retry"]["state"] == "submitted", reply.text
    admitted = await app.state.run_manager.get(reply.json()["retry"]["run_id"], user_id=STORAGE)
    if failure == "cancel" and not write:
        await asyncio.wait_for(entered.wait(), 5)
        admitted.task.cancel()
    await asyncio.wait_for(admitted.task, 15)
    assert admitted.status.value == ("success" if failure is None or write else "interrupted" if failure == "cancel" else "error") and reached == []
    assert await read_thread_goal(app.state.checkpointer, "thread") == goal
    assert len(state.mcp.calls) == int(not write)
    consumed = await repo.get_key(A, "__ce_" + handle)
    assert consumed["state"] == "claimed" and consumed["run_id"] == admitted.run_id
    from deerflow.persistence.approvals import PendingActionRepository

    with actor(A):
        pending = await PendingActionRepository(repo.sessions).list()
    assert len(pending) == int(write)
    if write:
        assert pending[0]["status"] == "pending" and pending[0]["payload"]["arguments"] == arguments
    cap, graph, saved, execution_context = captured[0]
    with pytest.raises(ComposioSessionError, match="connect_retry_consumed"):
        await asyncio.create_task(graph.ainvoke(cap.input(), saved, context=saved["context"]), context=execution_context)
    assert len(state.mcp.calls) == int(not write)
    assert await read_thread_goal(app.state.checkpointer, "thread") == goal
    count = len(state.requests)
    duplicate = await client.get("/api/integrations/callback", params=callback_params(handle), headers=headers(client, handle=handle))
    assert duplicate.json() == reply.json() and len(state.requests) == count
