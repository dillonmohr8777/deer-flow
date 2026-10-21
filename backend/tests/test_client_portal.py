"""Real SQL + AuthMiddleware portal acceptance; synthetic text, no model/sends."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import func, select, update
from test_org_isolation_b_threads import world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals, board, client_portal
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.board.model import BoardMessageRow, BoardThreadRow
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.thread_meta import ThreadMetaRepository

pytestmark = pytest.mark.asyncio
BASE = "/api/client-portal/threads"


def _app(sf):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(sf)
    app.state.board_repo = BoardRepository(sf)
    app.state.pending_action_repo = PendingActionRepository(sf)
    app.state.audit_repo = AuditEventRepository(sf)
    app.state.thread_store = ThreadMetaRepository(sf)
    app.include_router(client_portal.router)
    app.include_router(approvals.router)
    app.include_router(board.router)
    return app


def _http(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed(sf, org=ORG_S):
    now = datetime.now(UTC)
    async with sf() as session, session.begin():
        session.add_all([ClientRow(id="client-a", organization_id=org, display_name="Synthetic Alpha"), ClientRow(id="client-b", organization_id=org, display_name="Synthetic Beta")])
        if org == ORG_S:
            session.add(OrganizationMemberRow(organization_id=org, user_id=USER_B, role="member", status="active", created_at=now, updated_at=now))
        session.add_all([ClientAssignmentRow(client_id="client-a", user_id=USER_B, organization_id=org, role="client_contact"), ClientAssignmentRow(client_id="client-b", user_id=USER_C, organization_id=org, role="client_contact")])


async def _compose(client, headers):
    payload = {"client_id": "client-a", "submission_key": "weekly-report-20261021", "subject": "Weekly report", "body": "Please summarize completed work and next week's priorities using the attached source record."}
    response = await client.post(BASE, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    duplicate = await client.post(BASE, headers=headers, json=payload)
    assert duplicate.status_code == 200 and duplicate.json()["id"] == response.json()["id"]
    return response.json()


async def test_weekly_report_published_exactly_once_and_survives_reopen(org_world):  # noqa: F811
    await _seed(org_world)
    staff, alpha, beta = (auth_headers(user, ORG_S) for user in (USER_A, USER_B, USER_C))
    report = "# Weekly report\nCompleted: corrected three settings in the synthetic source record.\nNext: verify the next report against its source.\n"
    app = _app(org_world)
    async with _http(app) as client:
        created = await _compose(client, alpha)
        path = f"{BASE}/{created['id']}"
        assert (await client.get(path, headers=beta)).status_code == 404
        assert (await client.get(path, headers=auth_headers(USER_B))).status_code == 404
        assert len((await client.get(BASE, headers=staff)).json()["threads"]) == 1
        draft = await client.post(
            path + "/draft", headers=staff, json={"expected_revision": 0, "body": "Your weekly report is ready. Here is what changed and what happens next.", "attachments": [{"name": "weekly-report.md", "content": report}]}
        )
        assert draft.status_code == 200, draft.text
        version = draft.json()
        hidden = (await client.get(path, headers=alpha)).json()
        assert len(hidden["messages"]) == 1 and "draft" not in hidden and "approval_id" not in hidden
        assert (await client.get("/api/approvals", headers=alpha)).status_code == 403
        assert (await client.get(f"/api/approvals/{version['approval_id']}", headers=alpha)).status_code == 403
        assert (await client.get(f"/api/board/threads/{created['id']}/messages", headers=alpha)).status_code == 403
        publish = {"approval_id": version["approval_id"], "expected_revision": 1}
        assert (await client.post(path + "/publish", headers=alpha, json=publish)).status_code == 403
        published = await client.post(path + "/publish", headers=staff, json=publish)
        assert published.status_code == 200, published.text
        receipt = published.json()["publish_receipt"]
        assert receipt and (await client.post(path + "/publish", headers=staff, json=publish)).json()["publish_receipt"] == receipt
        assert (await client.post(path + "/draft", headers=staff, json={"expected_revision": 1, "body": "replace approved content"})).status_code == 409
        assert (await client.get(BASE + "?q=Weekly&state=published", headers=alpha)).json()["threads"][0]["id"] == created["id"]
    # New application + new browser transport: only the SQL store carries state.
    async with _http(_app(org_world)) as reopened:
        visible = await reopened.get(path, headers=alpha)
        assert visible.status_code == 200
        assert visible.json()["messages"][-1]["body"] == version["draft"]["body"]
        asset = await reopened.get(path + f"/messages/{receipt}/attachments/weekly-report.md", headers=alpha)
        assert asset.status_code == 200 and asset.text == report
        import hashlib

        assert asset.headers["x-content-sha256"] == hashlib.sha256(report.encode()).hexdigest()
        assert (await reopened.get(path + f"/messages/{receipt}/attachments/weekly-report.md", headers=beta)).status_code == 404
        async with org_world() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(BoardMessageRow).where(BoardMessageRow.id == receipt)) == 1
            assert await session.scalar(select(func.count()).select_from(BoardThreadRow)) == 1
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_S, OrganizationMemberRow.user_id == USER_B).values(status="revoked"))
        assert (await reopened.get(path, headers=alpha)).status_code == 403


async def test_duplicate_deliverable_names_rejected_before_draft_revision_changes(org_world):  # noqa: F811
    await _seed(org_world)
    async with _http(_app(org_world)) as client:
        thread = await _compose(client, auth_headers(USER_B, ORG_S))
        path = f"{BASE}/{thread['id']}"
        original = await client.post(f"{path}/draft", headers=auth_headers(USER_A, ORG_S), json={"expected_revision": 0, "body": "Original report", "attachments": [{"name": "report.md", "content": "original"}]})
        assert original.status_code == 200, original.text
        duplicate = await client.post(
            f"{path}/draft", headers=auth_headers(USER_A, ORG_S), json={"expected_revision": 1, "body": "Ambiguous files", "attachments": [{"name": "report.md", "content": "first"}, {"name": "report.md", "content": "second"}]}
        )
        assert duplicate.status_code == 422, duplicate.text
        after = await client.get(path, headers=auth_headers(USER_A, ORG_S))
        assert after.status_code == 200, after.text
        assert after.json()["revision"] == original.json()["revision"] == 1
        assert after.json()["approval_id"] == original.json()["approval_id"]
        assert after.json()["draft"] == original.json()["draft"]


async def test_competing_edit_invalidates_approval_and_legacy_stays_internal(org_world):  # noqa: F811
    await _seed(org_world)
    staff, alpha = auth_headers(USER_A, ORG_S), auth_headers(USER_B, ORG_S)
    async with _http(_app(org_world)) as client:
        created = await _compose(client, alpha)
        path = f"{BASE}/{created['id']}"
        first = (await client.post(path + "/draft", headers=staff, json={"expected_revision": 0, "body": "First exact version"})).json()
        second = await client.post(path + "/draft", headers=staff, json={"expected_revision": 1, "body": "Current exact version"})
        assert second.status_code == 200
        assert (await client.post(path + "/publish", headers=staff, json={"approval_id": first["approval_id"], "expected_revision": 1})).status_code == 409
        assert (await client.post(f"/api/approvals/{first['approval_id']}/approve", headers=staff)).status_code == 409
        # Legacy Board records never opt into the portal, even if assigned to A.
        async with org_world() as session, session.begin():
            session.add(BoardThreadRow(id="legacy", organization_id=ORG_S, client_id="client-a", subject="Internal discussion"))
        assert (await client.get(BASE + "/legacy", headers=alpha)).status_code == 404
        listing = (await client.get(BASE, headers=alpha)).json()
        assert all(row["id"] != "legacy" for row in listing["threads"])
        assert (await client.post(BASE, headers=alpha, json={"client_id": "client-b", "submission_key": "forged-client-key", "subject": "forged", "body": "denied"})).status_code == 404
        assert (await client.get(BASE, headers={**alpha, "X-Portal-Workspace": ORG_A})).status_code == 409


async def test_contact_chats_are_creator_bound_and_agency_memory_cannot_run(org_world):  # noqa: F811
    await _seed(org_world)
    store = ThreadMetaRepository(org_world)
    with acting_as(USER_A, ORG_S):
        await store.create("staff-private")
    with acting_as(USER_B, ORG_S):
        await store.create("alpha-chat")
        assert await store.get("staff-private") is None
        assert [r["thread_id"] for r in await store.search()] == ["alpha-chat"]
    with acting_as(USER_C, ORG_S):
        assert await store.get("alpha-chat") is None
        assert await store.check_access("alpha-chat", "storage-s") is False
        assert await store.search() == []
    with acting_as(USER_A, ORG_S):
        assert await store.get("alpha-chat") is not None  # intentional staff sharing
    from fastapi import HTTPException

    from app.gateway.client_workspace import require_client_workspace

    with acting_as(USER_B, ORG_S), pytest.raises(HTTPException) as failure:
        await require_client_workspace(SimpleNamespace(id=USER_B, system_role="client"))
    assert failure.value.status_code == 403


async def test_own_client_chat_in_dedicated_workspace_is_durable(org_world, monkeypatch):  # noqa: F811
    async with org_world() as session, session.begin():
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG_B).values(customer_client_id="dedicated-client"))
        session.add(ClientRow(id="dedicated-client", organization_id=ORG_A, display_name="Synthetic Dedicated"))
        session.add(ClientAssignmentRow(client_id="dedicated-client", user_id=USER_B, organization_id=ORG_B, role="client_contact"))

    async def user(request):
        return SimpleNamespace(id=request.cookies["access_token"], system_role="client", email="synthetic@example.test")

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)
    # Portal imports the auth accessor: test both consumers against the same identity.
    monkeypatch.setattr(client_portal, "get_current_user_from_request", user)
    headers = auth_headers(USER_B)
    async with _http(_app(org_world)) as client:
        created = await client.post(BASE, headers=headers, json={"client_id": "dedicated-client", "submission_key": "own-momo-chat-key", "subject": "Help with my report", "body": "Prepare next steps"})
        assert created.status_code == 200, created.text
        path = f"{BASE}/{created.json()['id']}/chat"
        chat = await client.post(path, headers=headers)
        assert chat.status_code == 200, chat.text
        assert (await client.post(path, headers=headers)).json() == chat.json()
    with acting_as(USER_B):
        saved = await ThreadMetaRepository(org_world).get(chat.json()["chat_id"])
        assert saved["assistant_id"] == "momobot-max" and saved["client_actor_id"] == USER_B
        from test_momobot_max import _config

        from app.gateway.momobot_max import apply_run_policy

        run_config = {"configurable": {"agent_name": "other", "model_name": "cheap-model"}, "context": {"reasoning_effort": "low", "max_total_subagents": 50}}
        config = _config(momobot_max={"enabled": True})
        await apply_run_policy(run_config, user=SimpleNamespace(id=USER_B, system_role="client"), actor_user_id=USER_B, app_config=config)
        for section in run_config.values():
            assert section["agent_name"] == "momobot-max" and "model_name" not in section
            assert section["reasoning_effort"] == "high" and section["max_total_subagents"] == config.subagents.max_total_per_run


async def test_admin_onboards_fresh_customer_workspace_without_cloning_client(org_world, monkeypatch):  # noqa: F811
    from app.gateway.routers import workspaces
    from deerflow.persistence.user.model import UserRow

    async with org_world() as session, session.begin():
        session.add(ClientRow(id="canonical-alpha", organization_id=ORG_S, display_name="Synthetic Alpha"))
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="client"))

    async def user(request):
        actor = request.cookies["access_token"]
        return SimpleNamespace(id=actor, system_role="admin" if actor == USER_A else "client", email="synthetic@example.test")

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)
    monkeypatch.setattr(client_portal, "get_current_user_from_request", user)
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: org_world)
    app = _app(org_world)
    app.include_router(workspaces.router)
    async with _http(app) as client:
        payload = {"client_id": "canonical-alpha", "user_id": USER_B, "name": "Synthetic Alpha customer workspace"}
        setup = await client.post("/api/client-portal/customer-workspaces", headers=auth_headers(USER_A, ORG_S), json=payload)
        assert setup.status_code == 201, setup.text
        customer_org = setup.json()["workspace_id"]
        assert customer_org != ORG_S
        assert (await client.post("/api/client-portal/customer-workspaces", headers=auth_headers(USER_A, ORG_S), json=payload)).status_code == 409
        headers = auth_headers(USER_B, customer_org)
        roster = await client.get("/api/client-portal/clients", headers=headers)
        assert roster.status_code == 200 and roster.json()["clients"] == [{"id": "canonical-alpha", "name": "Synthetic Alpha"}]
        created = await client.post(BASE, headers=headers, json={"client_id": "canonical-alpha", "submission_key": "customer-onboarding-request", "subject": "Weekly report", "body": "My report"})
        assert created.status_code == 200, created.text
        chat = await client.post(f"{BASE}/{created.json()['id']}/chat", headers=headers)
        assert chat.status_code == 200, chat.text
        assert (await client.post("/api/workspaces/select", headers=auth_headers(USER_B), json={"workspace_id": customer_org})).status_code == 200
        # Staff receives the same Board request by selecting the customer workspace.
        assert len((await client.get(BASE, headers=auth_headers(USER_A, customer_org))).json()["threads"]) == 1
        async with org_world() as session:
            assert await session.scalar(select(func.count()).select_from(ClientRow)) == 1
            workspace = await session.get(OrganizationRow, customer_org)
            assert workspace.customer_client_id == "canonical-alpha" and workspace.storage_user_id not in {USER_A, USER_B, "storage-s"}


async def test_memory_backend_cannot_overwrite_another_contacts_chat(org_world):  # noqa: F811
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.base import ThreadOwnershipConflictError
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

    await _seed(org_world)
    store = MemoryThreadMetaStore(InMemoryStore())
    with acting_as(USER_B, ORG_S):
        await store.create("memory-alpha")
    with acting_as(USER_C, ORG_S):
        assert await store.get("memory-alpha") is None
        assert await store.check_access("memory-alpha", "storage-s") is False
        assert await store.search() == []
        with pytest.raises(ThreadOwnershipConflictError):
            await store.create("memory-alpha")


async def test_customer_scope_holds_on_generic_thread_run_file_routes(world):  # noqa: F811
    """Use the existing full Gateway isolation fixture; no model or sandbox starts."""
    from test_org_isolation_b_threads import R_S, T_S

    await _seed(world.sf)
    with acting_as(USER_B, ORG_S):
        await world.threads.create("alpha-owned", assistant_id="momobot-max")
    with acting_as(USER_C, ORG_S):
        await world.threads.create("beta-owned", assistant_id="momobot-max")
        await world.runs.put("beta-run", thread_id="beta-owned", assistant_id="momobot-max", status="success")
        await world.events.put(thread_id="beta-owned", run_id="beta-run", event_type="llm.ai.response", category="message", content={"type": "ai", "content": "Private Beta response", "id": "beta-answer"})
        await world.app.state.feedback_repo.create(thread_id="beta-owned", run_id="beta-run", rating=1, comment="Private Beta feedback")
    with acting_as(USER_B, ORG_S):
        await world.runs.put("alpha-run", thread_id="alpha-owned", assistant_id="momobot-max", status="success")
        await world.events.put(thread_id="alpha-owned", run_id="alpha-run", event_type="llm.ai.response", category="message", content={"type": "ai", "content": "Private Alpha response", "id": "alpha-answer"})
        await world.app.state.feedback_repo.create(thread_id="alpha-owned", run_id="alpha-run", rating=1, comment="Private Alpha feedback")
    with acting_as(USER_A, ORG_S):
        await world.app.state.feedback_repo.create(thread_id=T_S, run_id=R_S, rating=1, comment="Shared staff feedback")
    for path in [
        f"/api/threads/{T_S}",
        f"/api/threads/{T_S}/messages",
        f"/api/threads/{T_S}/runs/{R_S}",
        f"/api/threads/{T_S}/artifacts/mnt/user-data/outputs/report.txt",
        f"/api/threads/{T_S}/uploads/list",
        "/api/threads/beta-owned",
        "/api/threads/beta-owned/runs/beta-run",
        "/api/runs/beta-run/messages",
        "/api/runs/beta-run/feedback",
    ]:
        response = await world.request(USER_B, "GET", path, org=ORG_S)
        assert response.status_code == 404, (path, response.status_code, response.text)
    # Both contacts retain their own actual event/feedback content, never the other's.
    for actor, own_run, other_run, own_name, other_name in [(USER_B, "alpha-run", "beta-run", "Alpha", "Beta"), (USER_C, "beta-run", "alpha-run", "Beta", "Alpha")]:
        for suffix, content in [("messages", f"Private {own_name} response"), ("feedback", f"Private {own_name} feedback")]:
            visible = await world.request(actor, "GET", f"/api/runs/{own_run}/{suffix}", org=ORG_S)
            assert visible.status_code == 200, visible.text
            assert content in visible.text
            hidden = await world.request(actor, "GET", f"/api/runs/{other_run}/{suffix}", org=ORG_S)
            assert hidden.status_code == 404, hidden.text
            assert f"Private {other_name}" not in hidden.text
    # The strict check preserves intentional organization-wide staff conversation sharing.
    for suffix, content in [("messages", f"answer {T_S}"), ("feedback", "Shared staff feedback")]:
        shared = await world.request(USER_A, "GET", f"/api/runs/{R_S}/{suffix}", org=ORG_S)
        assert shared.status_code == 200, shared.text
        assert content in shared.text
    own = await world.request(USER_B, "GET", "/api/threads/alpha-owned", org=ORG_S)
    assert own.status_code == 200, own.text
    listing = await world.request(USER_B, "POST", "/api/threads/search", {}, org=ORG_S)
    assert listing.status_code == 200, listing.text
    assert [row["thread_id"] for row in listing.json()] == ["alpha-owned"]


async def test_edited_generic_approval_cannot_publish_and_approved_crash_resumes(org_world):  # noqa: F811
    from deerflow.persistence.approvals.model import PendingActionRow

    await _seed(org_world)
    staff, alpha = auth_headers(USER_A, ORG_S), auth_headers(USER_B, ORG_S)
    async with _http(_app(org_world)) as client:
        created = await _compose(client, alpha)
        path = f"{BASE}/{created['id']}"
        draft = (await client.post(path + "/draft", headers=staff, json={"expected_revision": 0, "body": "Original approved content"})).json()
        async with org_world() as session:
            original = (await session.get(PendingActionRow, draft["approval_id"])).original_payload
        edited = await client.patch(f"/api/approvals/{draft['approval_id']}", headers=staff, json={"payload": {**original, "body": "Substituted content"}})
        assert edited.status_code == 200, edited.text
        assert (await client.post(path + "/publish", headers=staff, json={"approval_id": draft["approval_id"], "expected_revision": 1})).status_code == 409
        assert len((await client.get(path, headers=alpha)).json()["messages"]) == 1
        current = (await client.post(path + "/draft", headers=staff, json={"expected_revision": 1, "body": "Reviewed replacement content"})).json()
        # Simulate termination after pending->approved but before adapter execution.
        async with org_world() as session, session.begin():
            await session.execute(update(PendingActionRow).where(PendingActionRow.id == current["approval_id"]).values(status="approved", decided_by=USER_A))
        published = await client.post(path + "/publish", headers=staff, json={"approval_id": current["approval_id"], "expected_revision": 2})
        assert published.status_code == 200, published.text
        assert published.json()["messages"][-1]["body"] == "Reviewed replacement content"
        async with org_world() as session:
            approved = await session.get(PendingActionRow, current["approval_id"])
            assert approved.status == "executed" and approved.execution_result["delivery"] == "portal"


async def test_staff_work_uses_existing_durable_run_admission_once(world):  # noqa: F811
    from deerflow.config.app_config import AppConfig, set_app_config

    await _seed(world.sf)
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "synthetic-no-provider"}],
                "momobot_max": {"enabled": True},
            }
        )
    )
    world.app.state.client_repo = ClientRepository(world.sf)
    world.app.state.board_repo = BoardRepository(world.sf)
    world.app.state.pending_action_repo = PendingActionRepository(world.sf)
    world.app.state.audit_repo = AuditEventRepository(world.sf)
    world.app.include_router(client_portal.router)
    async with _http(world.app) as client:
        created = await _compose(client, auth_headers(USER_B, ORG_S))
        path = f"{BASE}/{created['id']}/work"
        staff = auth_headers(USER_A, ORG_S)
        work = await client.post(path, headers=staff)
        assert work.status_code == 200, work.text
        repeated = await client.post(path, headers=staff)
        assert repeated.status_code == 200 and repeated.json()["run_id"] == work.json()["run_id"]
        detail = (await client.get(f"{BASE}/{created['id']}", headers=staff)).json()
        assert detail["work_run_id"] == work.json()["run_id"] and detail["work_chat_id"] == work.json()["chat_id"]
        visible = (await client.get(f"{BASE}/{created['id']}", headers=auth_headers(USER_B, ORG_S))).json()
        assert "work_chat_id" not in visible and "work_run_id" not in visible
        assert (await client.get(f"/api/threads/{work.json()['chat_id']}", headers=auth_headers(USER_B, ORG_S))).status_code == 404
        assert (await client.post(path, headers=auth_headers(USER_B, ORG_S))).status_code == 404
