"""M3 lane 0 phase 2: internal callers act only through an organization delegation.

Contract section 4: an internal token plus ``X-DeerFlow-Owner-User-Id`` is never
enough by itself. AuthMiddleware admits an internal call only with an active
delegation (``X-DeerFlow-Delegation-Id``) whose owner is an active member of an
active organization and matches the owner header; the delegation's scopes
narrow the route permissions like PAT scopes. Also covered: the invitation
freeze (decision 1), the admin listing of ownerless threads (decision 3),
channel and MCP delegation grants, and background channel identity.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from org_isolation_fixtures import ORG_A, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import update

from app.gateway import services
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import require_permission
from app.gateway.internal_auth import INTERNAL_DELEGATION_ID_HEADER_NAME, create_internal_auth_headers
from app.gateway.routers import console, invitations
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationDelegationRow, OrganizationMemberRow
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, get_current_user, resolve_organization_id, resolve_user_id

pytestmark = pytest.mark.asyncio


def _proof_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/threads/{thread_id}")
    @require_permission("threads", "read")
    async def read_thread(thread_id: str, request: Request):
        return {"actor": request.state.actor_user_id, "storage": resolve_user_id(AUTO), "organization": resolve_organization_id(), "delegation": request.state.delegation_id}

    @app.delete("/api/threads/{thread_id}")
    @require_permission("threads", "delete")
    async def delete_thread(thread_id: str, request: Request):
        return {"deleted": thread_id}

    return app


async def test_internal_calls_are_admitted_only_through_a_matching_active_delegation(org_world, caplog):  # noqa: F811
    delegations = OrganizationDelegationRepository(org_world)
    private = await delegations.grant(organization_id=ORG_A, subject_type="test_worker", subject_id="w-private", owner_user_id=USER_A, scopes=["threads:read"])
    shared = await delegations.grant(organization_id=ORG_S, subject_type="test_worker", subject_id="w-shared", owner_user_id=USER_C, scopes=["threads:read"])
    expired = await delegations.grant(organization_id=ORG_A, subject_type="test_worker", subject_id="w-expired", owner_user_id=USER_A, scopes=["threads:read"], expires_at=datetime.now(UTC) - timedelta(seconds=1))
    revoked = await delegations.grant(organization_id=ORG_A, subject_type="test_worker", subject_id="w-revoked", owner_user_id=USER_A, scopes=["threads:read"])
    await delegations.revoke(subject_type="test_worker", subject_id="w-revoked")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_proof_app()), base_url="http://test") as client:

        async def call(method="GET", **kwargs):
            return await client.request(method, "/api/threads/t", headers=create_internal_auth_headers(**kwargs))

        # Refused: token alone, token plus owner header, unknown/expired/revoked ids,
        # and a real delegation presented with someone else's owner header.
        for kwargs in ({}, {"owner_user_id": USER_A}, {"owner_user_id": USER_A, "delegation_id": "nope"}, {"delegation_id": expired}, {"delegation_id": revoked}, {"owner_user_id": USER_B, "delegation_id": private}):
            response = await call(**kwargs)
            assert (response.status_code, response.json()["detail"]) == (403, "Internal calls require an active organization delegation"), kwargs
        assert "Rejected internal call without a matching active delegation" in caplog.text

        # Admitted: the owner acts in the delegation's organization, on its storage principal.
        assert (await call(owner_user_id=USER_A, delegation_id=private)).json() == {"actor": USER_A, "storage": USER_A, "organization": ORG_A, "delegation": private}
        assert (await call(delegation_id=shared)).json() == {"actor": USER_C, "storage": STORAGE_S, "organization": ORG_S, "delegation": shared}
        # Scopes narrow route permissions exactly like PAT scopes.
        assert (await call("DELETE", delegation_id=private)).status_code == 403

        # Revoking the owner's membership invalidates the delegation on the next request.
        async with org_world() as session, session.begin():
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_S, OrganizationMemberRow.user_id == USER_C).values(status="revoked"))
        assert (await call(delegation_id=shared)).status_code == 403


async def test_resolve_delegation_by_id_applies_every_check(org_world):  # noqa: F811
    delegations = OrganizationDelegationRepository(org_world)
    granted = await delegations.grant(organization_id=ORG_A, subject_type="test_worker", subject_id="w", owner_user_id=USER_A, scopes=["runs:create"])
    assert (await delegations.resolve_delegation_by_id(granted)).owner_user_id == USER_A
    assert await delegations.resolve_delegation_by_id(granted, scope="runs:create") is not None
    assert await delegations.resolve_delegation_by_id(granted, scope="threads:delete") is None
    assert await delegations.resolve_delegation_by_id(None) is None
    async with org_world() as session, session.begin():
        await session.execute(update(OrganizationDelegationRow).where(OrganizationDelegationRow.id == granted).values(scopes=[]))
    assert await delegations.resolve_delegation_by_id(granted) is None


async def test_shared_workspace_launch_through_a_delegation_still_needs_the_isolated_sandbox(org_world):  # noqa: F811
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    try:
        delegation_id = await OrganizationDelegationRepository(org_world).grant(organization_id=ORG_S, subject_type="scheduled_task", subject_id="task-s", owner_user_id=USER_A, scopes=["runs:create"])
        delegation = await OrganizationDelegationRepository(org_world).resolve_delegation_by_id(delegation_id)
        app_state = SimpleNamespace(stream_bridge=object(), run_manager=object(), checkpointer=InMemorySaver(), run_event_store=object(), thread_store=ThreadMetaRepository(org_world))
        request = services._delegated_internal_request(SimpleNamespace(state=app_state), delegation)
        assert "X-DeerFlow-Owner-User-Id" not in request.headers
        assert (request.state.actor_user_id, request.state.storage_user_id, request.state.organization_id) == (USER_A, STORAGE_S, ORG_S)
        body = services.RunCreateRequest(assistant_id="lead_agent", input={"messages": [{"role": "user", "content": "hi"}]})
        with pytest.raises(HTTPException) as refused:
            await services.start_run(body, "thread-s", request)
        assert (refused.value.status_code, refused.value.detail) == (503, "Shared workspace tools require the isolated workspace sandbox")
    finally:
        reset_app_config()


async def test_invitations_are_frozen_by_default_for_creation_and_acceptance():
    assert AuthorizationConfig().invitations_frozen is True
    for call in (
        lambda: invitations.create_invitation(invitations.CreateInvitationRequest(organization_id=ORG_S, email="new@example.com"), SimpleNamespace(), SimpleNamespace(headers={})),
        lambda: invitations.inspect_invitation(invitations.InvitationTokenRequest(token="t"), SimpleNamespace(headers={})),
        lambda: invitations.accept_invitation(invitations.AcceptInvitationRequest(token="t", password="a long enough password"), SimpleNamespace(), SimpleNamespace(headers={})),
    ):
        with pytest.raises(HTTPException) as frozen:
            await call()
        assert frozen.value.status_code == 403
        assert "Existing members keep their access" in frozen.value.detail


async def test_admin_lists_ownerless_and_orphan_thread_ids_read_only(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(console, "get_session_factory", lambda: org_world)
    async with org_world() as session, session.begin():
        session.add_all([ThreadMetaRow(thread_id="t-owned", user_id=USER_A, organization_id=ORG_A), ThreadMetaRow(thread_id="t-ownerless", user_id=None)])
    saver = InMemorySaver()
    for thread_id in ("t-owned", "t-orphan"):
        await saver.aput({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, empty_checkpoint(), {"step": 1, "source": "loop", "writes": {}, "parents": {}}, {})
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(console.router)
    app.state.checkpointer = saver

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/console/ownerless-threads", headers=auth_headers(USER_A))).status_code == 403
        monkeypatch.setattr("app.gateway.deps.is_admin_user", lambda request: asyncio.sleep(0, result=True))
        listed = await client.get("/api/console/ownerless-threads", headers=auth_headers(USER_A))
    assert (listed.status_code, listed.json()) == (200, {"ownerless": ["t-ownerless"], "orphan_checkpoints": ["t-orphan"]})


async def test_connecting_a_channel_grants_its_worker_delegation(org_world):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    connection = await repo.upsert_connection(owner_user_id=USER_A, provider="slack", external_account_id="U-a", workspace_id="T1")
    found = await repo.find_connection_by_external_identity(provider="slack", external_account_id="U-a", workspace_id="T1")
    delegation = await OrganizationDelegationRepository(org_world).resolve_delegation_by_id(found["delegation_id"])
    assert (delegation.subject_id, delegation.owner_user_id, delegation.organization.id) == (connection["id"], USER_A, ORG_A)
    assert delegation.scopes == frozenset({"threads:read", "threads:write", "runs:create", "runs:read"})

    from app.channels.connection_identity import attach_connection_identity
    from app.channels.manager import _owner_headers
    from app.channels.message_bus import InboundMessage

    inbound = await attach_connection_identity(InboundMessage(channel_name="slack", chat_id="C1", user_id="U-a", text="hi"), repo=repo, provider="slack", workspace_id="T1")
    assert _owner_headers(inbound)[INTERNAL_DELEGATION_ID_HEADER_NAME] == delegation.id

    # Disconnecting revokes it, and the next lookup carries none.
    await repo.disconnect_connection(connection_id=connection["id"], owner_user_id=USER_A)
    assert await OrganizationDelegationRepository(org_world).resolve_delegation_by_id(delegation.id) is None


async def test_mcp_task_creation_grants_the_acting_member_and_the_launcher_acts_through_it(org_world, monkeypatch):  # noqa: F811
    from deerflow.persistence.mcp_tasks import McpTaskRepository

    async with org_world() as session, session.begin():
        session.add(ThreadMetaRow(thread_id="t-s", user_id=STORAGE_S, organization_id=ORG_S))
    task = {"user_id": STORAGE_S, "thread_id": "t-s", "run_id": None, "tool_call_id": None, "server_name": "srv", "driver_name": "drv", "task_name": "job", "status": "working"}
    task |= {"result": None, "result_preview": None, "result_truncated": False, "result_artifact": None, "error": None, "input_required": None, "next_poll_at": None}
    with acting_as(USER_C, ORG_S):
        await McpTaskRepository(org_world).create(task_id="task-s", remote_task_id="remote-1", **task)

    captured = []

    async def start_run(body, thread_id, request, **_kwargs):
        captured.append((request.headers, request.state.actor_user_id, request.state.storage_user_id, request.state.organization_id, resolve_organization_id()))
        return SimpleNamespace(run_id="run-n", thread_id=thread_id)

    monkeypatch.setattr(services, "start_run", start_run)
    launch = {"app": SimpleNamespace(state=SimpleNamespace()), "thread_id": "t-s", "assistant_id": None, "owner_user_id": STORAGE_S, "dispatch_version": 1, "dispatch_attempt": 1, "event": {}}
    await services.launch_mcp_task_notification_run(task_id="task-s", organization_id=ORG_S, **launch)
    assert captured == [({}, USER_C, STORAGE_S, ORG_S, ORG_S)]
    # Another organization, or another task's id, finds no delegation.
    for task_id, organization_id in (("task-s", ORG_A), ("task-other", ORG_S)):
        with pytest.raises(PermissionError):
            await services.launch_mcp_task_notification_run(task_id=task_id, organization_id=organization_id, **launch)
    assert len(captured) == 1


async def test_channels_start_without_the_callers_request_identity(monkeypatch):
    from app.channels import service as channel_service
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    seen = []

    class _Channel:
        is_running = True

        def __init__(self, *, bus, config):
            pass

        async def start(self):
            # Tasks a channel spawns here inherit this context.
            seen.append(get_current_user())

    monkeypatch.setitem(channel_service._CHANNEL_REGISTRY, "probe", "tests:_Channel")
    monkeypatch.setattr("deerflow.reflection.resolve_class", lambda *_args, **_kwargs: _Channel)
    service = channel_service.ChannelService.__new__(channel_service.ChannelService)
    service._channels, service.bus, service.store, service._connection_repo = {}, None, None, None
    token = set_current_user(SimpleNamespace(id="http-caller"))  # a restart running inside an HTTP request
    try:
        assert await service._start_channel("probe", {}) is True
        assert get_current_user().id == "http-caller"
    finally:
        reset_current_user(token)
    assert seen == [None]
