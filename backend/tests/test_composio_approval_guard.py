"""Offline Composio boundary tests: real persistence/CAS, fake MCP transport."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world, org_world_pooled  # noqa: F401
from test_approvals_inbox import _app, _http

from app.gateway.approval_adapters import execute_approved
from deerflow.approvals import InvalidPayloadError
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.interceptors import build_mcp_tool_interceptors, compose_tool_interceptors
from deerflow.persistence.approvals import PendingActionRepository


def request(name="COMPOSIO_MULTI_EXECUTE_TOOL", args=None, *, server="composio-me", call_id="call-1", **context):
    return MCPToolCallRequest(
        server_name=server,
        name=name,
        args=args if args is not None else batch("GMAIL_SEND_EMAIL", {"recipient_email": "qa@example.test", "body": "Exact draft"}),
        headers={"Authorization": "transport-secret-never-persist"},
        runtime=SimpleNamespace(tool_call_id=call_id, context={"thread_id": "thread-1", "run_id": "run-1", **context}),
    )


def batch(slug, arguments=None):
    return {"tools": [{"tool_slug": slug, "arguments": arguments or {}}]}


def boundary(upstream, *, custom=None):
    config = ExtensionsConfig.model_validate({"mcpServers": {}, **({"mcpInterceptors": ["tests:custom"]} if custom else {})})
    interceptors = build_mcp_tool_interceptors(
        config,
        oauth_builder=lambda _: None,
        user_auth_builder=lambda _: None,
        context_headers_builder=lambda _: None,
        resolver=lambda _: lambda: custom,
    )
    return compose_tool_interceptors(interceptors, upstream)


@pytest.fixture
def inbox(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: org_world)
    return PendingActionRepository(org_world)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": ["gmail"]}),
        ("COMPOSIO_SEARCH_TOOLS", {"queries": [{"use_case": "find mail"}]}),
        ("COMPOSIO_GET_TOOL_SCHEMAS", {"tool_slugs": ["GMAIL_SEND_EMAIL"]}),
        ("GMAIL_FETCH_EMAILS", {"query": "from:qa@example.test"}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", batch("HUBSPOT_GET_CONTACT")),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_LIST_LABELS", "arguments": {}}, {"tool_slug": "SLACK_SEARCH_ALL", "arguments": {"query": "qa"}}]}),
    ],
)
async def test_known_reads_and_controls_pass_once(inbox, name, args):
    upstream = AsyncMock(return_value="read result")
    with acting_as(USER_A, ORG_S):
        assert await boundary(upstream)(request(name, args)) == "read result"
        assert await inbox.list() == []
    upstream.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [("COMPOSIO_MULTI_EXECUTE_TOOL", batch(slug, {"exact": "payload"})) for slug in ("GMAIL_SEND_EMAIL", "HUBSPOT_CREATE_CONTACT", "GOOGLEADS_MUTATE", "METAADS_UPDATE_CAMPAIGN", "SLACK_POST_MESSAGE", "NEW_VENDOR_FUTURE_ACTION")]
    + [
        ("COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": "client.send()"}),
        ("COMPOSIO_REMOTE_BASH_TOOL", {"command": "send"}),
        ("COMPOSIO_PROXY_EXECUTE", {"method": "POST"}),
        ("COMPOSIO_GET_PROXY", {"method": "POST"}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_GET_EMAIL", "arguments": {}}, {"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"body": "exact"}}]}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", batch("COMPOSIO_MULTI_EXECUTE_TOOL", batch("GMAIL_SEND_EMAIL"))),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": "unparseable"}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_GET_EMAIL", "arguments": {}, "execute": "send"}]}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GMAIL_GET_EMAIL", "arguments": {}}], "future_execution": {"slug": "SEND"}}),
    ],
)
async def test_write_unknown_mixed_and_nested_withhold_entire_call(inbox, name, args):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        result = await boundary(upstream)(request(name, args, actor_user_id=USER_B, storage_user_id="storage-s", organization_id=ORG_A, approved=True))
        row = (await inbox.list())[0]
        assert result.structuredContent == {"status": "pending_approval", "id": row["id"]}
        assert (row["user_id"], row["organization_id"], row["thread_id"], row["run_id"]) == (USER_A, ORG_S, "thread-1", "run-1")
        assert row["payload"] == {"server_name": "composio-me", "tool_name": name, "arguments": args, "tool_call_id": "call-1"}
        assert "transport-secret" not in json.dumps(row)
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_proposal_is_durable_idempotent_and_conflict_is_refused(inbox):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        first = await boundary(upstream)(request())
        again = await boundary(upstream)(request())
        assert first.structuredContent == again.structuredContent
        assert len(await inbox.list()) == 1
        with pytest.raises(InvalidPayloadError, match="conflict"):
            await boundary(upstream)(request(args=batch("SLACK_POST_MESSAGE")))
        row = (await inbox.list())[0]
        assert row["payload"]["arguments"] == request().args
        with pytest.raises(InvalidPayloadError):
            await inbox.edit(row["id"], payload={**row["payload"], "arguments": {"changed": True}})
    upstream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("server", ["composio-sean", "composio-marketing", "composio-me", "composio-future"])
async def test_all_composio_servers_gate_even_sean_and_forged_bypass(inbox, server):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        result = await boundary(upstream)(request(server=server, approved_composio=True, approval_id="forged"))
        assert result.structuredContent["status"] == "pending_approval"
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_boundary_rechecks_custom_rewrites(inbox):
    async def rewrite(req, handler):
        return await handler(req.override(name="COMPOSIO_MULTI_EXECUTE_TOOL", args=batch("GMAIL_SEND_EMAIL")))

    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        result = await boundary(upstream, custom=rewrite)(request("GMAIL_GET_EMAIL", {}))
        assert result.structuredContent["status"] == "pending_approval"
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_mcp_unchanged_and_missing_scope_never_executes(inbox):
    upstream = AsyncMock(return_value="other")
    assert await boundary(upstream)(request(server="private-brain")) == "other"
    upstream.reset_mock()
    with pytest.raises(ToolException, match="authenticated"):
        await boundary(upstream)(request(actor_user_id=USER_A, organization_id=ORG_S))
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_credentials_in_arguments_are_refused_without_storage(inbox):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        with pytest.raises(InvalidPayloadError, match="credential"):
            await boundary(upstream)(request(args={"headers": {"Authorization": "never-store-this"}}))
        assert await inbox.list() == []
    upstream.assert_not_awaited()


async def propose(inbox):
    with acting_as(USER_A, ORG_S):
        out = await boundary(AsyncMock())(request())
        return await inbox.get(out.structuredContent["id"])


@pytest.mark.asyncio
async def test_foreign_actor_and_org_cannot_list_get_approve_reject(inbox, org_world):  # noqa: F811
    row = await propose(inbox)
    async with _http(_app(org_world)) as client:
        for actor, org in ((USER_A, ORG_A), (USER_C, ORG_S), (USER_B, None)):
            headers = auth_headers(actor, org)
            assert (await client.get("/api/approvals", headers=headers)).json()["approvals"] == []
            assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).status_code == 404
            for choice in ("approve", "reject"):
                assert (await client.post(f"/api/approvals/{row['id']}/{choice}", headers=headers)).status_code in (403, 404)


def fake_transport(monkeypatch, upstream, *, custom=None):
    async def call(runtime=None, **args):
        return await boundary(upstream, custom=custom)(MCPToolCallRequest(name="COMPOSIO_MULTI_EXECUTE_TOOL", args=args, server_name="composio-me", runtime=runtime))

    config = ExtensionsConfig.model_validate({"mcpServers": {"composio-me": {"type": "http", "url": "https://example.invalid/mcp", "enabled": True}}})
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools", AsyncMock(return_value=[SimpleNamespace(name="composio-me_COMPOSIO_MULTI_EXECUTE_TOOL", coroutine=call)]))


@pytest.mark.asyncio
async def test_reject_zero_and_approve_one_with_no_replay(inbox, org_world, monkeypatch):  # noqa: F811
    upstream = AsyncMock(return_value="sent")
    fake_transport(monkeypatch, upstream)
    row = await propose(inbox)
    async with _http(_app(org_world)) as client:
        headers = auth_headers(USER_A, ORG_S)
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)).json()["status"] == "rejected"
        upstream.assert_not_awaited()
        with acting_as(USER_A, ORG_S):
            rejected = await inbox.get(row["id"])
            assert (await execute_approved(rejected)).status == "failed"
        with acting_as(USER_A, ORG_S):
            pending = await boundary(AsyncMock())(request(call_id="call-2"))
        action_id = pending.structuredContent["id"]
        assert (await client.post(f"/api/approvals/{action_id}/approve", headers=headers)).json()["status"] == "executed"
        assert (await client.post(f"/api/approvals/{action_id}/approve", headers=headers)).status_code == 409
        with acting_as(USER_A, ORG_S):
            assert (await execute_approved(await inbox.get(action_id))).status == "failed"
    upstream.assert_awaited_once()
    sent = upstream.await_args.args[0]
    assert sent.args == request().args


@pytest.mark.asyncio
async def test_timeout_fences_attempt_and_leaves_unknown(inbox, monkeypatch):
    upstream = AsyncMock(side_effect=TimeoutError("secret-provider-response"))
    fake_transport(monkeypatch, upstream)
    row = await propose(inbox)
    with acting_as(USER_A, ORG_S):
        approved = await inbox.decide(row["id"], approve=True, decided_by=USER_A)
        out = await execute_approved(approved)
        assert out.status == "approved" and out.detail["state"] == "outcome_unknown"
        assert "secret-provider-response" not in json.dumps(out.detail) + str(out.error)
        persisted = await inbox.get(row["id"])
        assert persisted["status"] == "approved" and persisted["execution_result"]["state"] == "outcome_unknown"
        await execute_approved(approved)
    upstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_approved_custom_retry_cannot_attempt_twice(inbox, monkeypatch):
    async def retry(req, handler):
        result = await handler(req)
        with pytest.raises(ToolException, match="consumed"):
            await handler(req)
        return result

    upstream = AsyncMock(return_value="sent")
    fake_transport(monkeypatch, upstream, custom=retry)
    row = await propose(inbox)
    with acting_as(USER_A, ORG_S):
        out = await execute_approved(await inbox.decide(row["id"], approve=True, decided_by=USER_A))
        assert out.status == "executed"
    upstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_proposal_and_approval_claims(org_world_pooled, monkeypatch):  # noqa: F811
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: org_world_pooled)
    inbox = PendingActionRepository(org_world_pooled)
    upstream = AsyncMock(return_value="sent")
    fake_transport(monkeypatch, upstream)
    with acting_as(USER_A, ORG_S):
        proposals = await asyncio.gather(*(boundary(AsyncMock())(request()) for _ in range(3)))
        assert len({out.structuredContent["id"] for out in proposals}) == 1
        action_id = proposals[0].structuredContent["id"]
        decisions = await asyncio.gather(*(inbox.decide(action_id, approve=True, decided_by=USER_A) for _ in range(3)))
        winners = [row for row in decisions if row]
        assert len(winners) == 1
        await asyncio.gather(*(execute_approved(winners[0]) for _ in range(3)))
    upstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_optional_builder_failure_cannot_remove_gate_or_run_auth_first(inbox):
    auth = AsyncMock()
    upstream = AsyncMock()
    config = ExtensionsConfig.model_validate({"mcpInterceptors": ["missing:builder"]})

    def broken(_):
        raise ImportError("missing")

    interceptors = build_mcp_tool_interceptors(config, oauth_builder=lambda _: auth, user_auth_builder=lambda _: None, context_headers_builder=lambda _: None, resolver=broken)
    with acting_as(USER_A, ORG_S):
        out = await compose_tool_interceptors(interceptors, upstream)(request())
        assert out.structuredContent["status"] == "pending_approval"
    auth.assert_not_awaited()
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_50_action_batch_is_classified_before_any_call(inbox):
    upstream = AsyncMock(return_value="read")
    args = {"tools": [{"tool_slug": "GMAIL_GET_EMAIL", "arguments": {"id": str(i)}} for i in range(50)]}
    with acting_as(USER_A, ORG_S):
        assert await boundary(upstream)(request(args=args)) == "read"
        upstream.assert_awaited_once()
        upstream.reset_mock()
        args["tools"][-1] = {"tool_slug": "GMAIL_SEND_EMAIL", "arguments": {"body": "last action is a write"}}
        out = await boundary(upstream)(request(args=args))
        assert out.structuredContent["status"] == "pending_approval"
        assert len((await inbox.get(out.structuredContent["id"]))["payload"]["arguments"]["tools"]) == 50
    upstream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("COMPOSIO_GET_FUTURE_WRAPPER", {"method": "POST"}),
        ("GMAIL_GET_AND_SEND_EMAIL", {}),
        ("GMAIL_GET_EMAIL.bad", {}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {**batch("GMAIL_GET_EMAIL"), "session_id": {"execute": "send"}}),
        ("COMPOSIO_MULTI_EXECUTE_TOOL", {**batch("GMAIL_GET_EMAIL"), "memory": {"execute": "send"}}),
    ],
)
async def test_unrecognized_read_shaped_execution_fails_closed(inbox, name, args):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        out = await boundary(upstream)(request(name, args))
        assert out.structuredContent["status"] == "pending_approval"
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_crash_after_upstream_keeps_durable_unknown_and_fences_retry(inbox, monkeypatch):
    upstream = AsyncMock(side_effect=asyncio.CancelledError())
    fake_transport(monkeypatch, upstream)
    row = await propose(inbox)
    with acting_as(USER_A, ORG_S):
        approved = await inbox.decide(row["id"], approve=True, decided_by=USER_A)
        with pytest.raises(asyncio.CancelledError):
            await execute_approved(approved)
        stored = await inbox.get(row["id"])
        assert stored["status"] == "approved" and stored["execution_result"]["state"] == "outcome_unknown"
        await execute_approved(approved)
        assert await inbox.decide(row["id"], approve=True, decided_by=USER_A) is None
        repeated = await boundary(upstream)(request())
        assert repeated.structuredContent == {"status": "approved", "id": row["id"]}
        assert len(await inbox.list()) == 1
    upstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_approved_payload_rewrite_cannot_reach_upstream(inbox, monkeypatch):
    async def rewrite(req, handler):
        return await handler(req.override(args=batch("SLACK_POST_MESSAGE", {"text": "changed after approval"})))

    upstream = AsyncMock()
    fake_transport(monkeypatch, upstream, custom=rewrite)
    row = await propose(inbox)
    with acting_as(USER_A, ORG_S):
        out = await execute_approved(await inbox.decide(row["id"], approve=True, decided_by=USER_A))
        assert out.status == "approved" and out.detail["state"] == "outcome_unknown"
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_tool_call_identity_or_database_cannot_execute(inbox, monkeypatch):
    upstream = AsyncMock()
    with acting_as(USER_A, ORG_S):
        with pytest.raises(InvalidPayloadError, match="tool call id"):
            await boundary(upstream)(request(call_id=None))
        monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)
        with pytest.raises(ToolException, match="unavailable"):
            await boundary(upstream)(request())
        assert await inbox.list() == []
    upstream.assert_not_awaited()
