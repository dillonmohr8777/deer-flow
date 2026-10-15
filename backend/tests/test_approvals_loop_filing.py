"""Client Loop filing: a delegated internal caller files a pending action; nobody else can."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, USER_A, USER_B, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import approvals
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository

FILE = {
    "client": "acme-fake",
    "action_type": "email",
    "title": "Reply to Pat about the report",
    "target": "pat@example.com",
    "payload": {"subject": "Re: report", "body": "hey Pat, google ads showed 537 queries this week"},
    "source_link": "https://mail.google.com/mail/u/0/#all/abc123",
    "draft_ref": {"gmail_draft_id": "r-1"},
    "thread": "abc123",
    "evidence": [{"source": "sources.md", "text": "Google Ads: 537 queries, CTR 3.5%"}],
}


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(approvals.router)
    return app


def _http(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _delegation(org_world, scopes):  # noqa: F811
    return await OrganizationDelegationRepository(org_world).grant(organization_id=ORG_A, subject_type="client_loop", subject_id="loop", owner_user_id=USER_A, scopes=scopes)


@pytest.mark.asyncio
async def test_delegated_loop_files_a_pending_row_with_fact_check_and_metadata(org_world):  # noqa: F811
    did = await _delegation(org_world, ["approvals:propose"])
    async with _http(_app(org_world)) as client:
        resp = await client.post("/api/approvals/propose", json=FILE, headers=create_internal_auth_headers(delegation_id=did))
        assert resp.status_code == 201, resp.text
        out = resp.json()
        assert out["status"] == "pending" and out["agent_name"] == "acme-fake" and out["thread_id"] == "abc123"
        assert out["fact_check"]["gate"] == "pass" and "evidence" not in out["fact_check"]
        assert out["payload"]["loop"] == {"client": "acme-fake", "source_link": FILE["source_link"], "draft_ref": FILE["draft_ref"]}
        # the owner sees it in the inbox as a normal browser user, and nothing was sent
        listed = (await client.get("/api/approvals?status=pending", headers=auth_headers(USER_A))).json()["approvals"]
        assert [r["id"] for r in listed] == [out["id"]]
        assert (await client.get("/api/approvals", headers=auth_headers(USER_B))).json()["approvals"] == []


@pytest.mark.asyncio
async def test_contradicted_draft_is_refused_and_nothing_is_filed(org_world):  # noqa: F811
    did = await _delegation(org_world, ["approvals:propose"])
    bad = {**FILE, "payload": {"subject": "s", "body": "we reviewed 900 queries"}}
    async with _http(_app(org_world)) as client:
        resp = await client.post("/api/approvals/propose", json=bad, headers=create_internal_auth_headers(delegation_id=did))
        assert resp.status_code == 422 and "contradicts" in resp.json()["detail"]
        assert (await client.get("/api/approvals", headers=auth_headers(USER_A))).json()["approvals"] == []


@pytest.mark.asyncio
async def test_invalid_payload_is_422(org_world):  # noqa: F811
    did = await _delegation(org_world, ["approvals:propose"])
    async with _http(_app(org_world)) as client:
        resp = await client.post("/api/approvals/propose", json={**FILE, "target": "not-an-address"}, headers=create_internal_auth_headers(delegation_id=did))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_only_a_delegation_holding_the_propose_scope_may_file(org_world):  # noqa: F811
    read_only = await _delegation(org_world, ["approvals:read"])
    async with _http(_app(org_world)) as client:
        # a browser session, even the owner's, cannot use the internal filing path
        assert (await client.post("/api/approvals/propose", json=FILE, headers=auth_headers(USER_A))).status_code == 403
        # a token alone, or a delegation without the scope
        assert (await client.post("/api/approvals/propose", json=FILE, headers=create_internal_auth_headers())).status_code == 403
        assert (await client.post("/api/approvals/propose", json=FILE, headers=create_internal_auth_headers(delegation_id=read_only))).status_code == 403
        assert (await client.get("/api/approvals", headers=auth_headers(USER_A))).json()["approvals"] == []


@pytest.mark.asyncio
async def test_a_propose_delegation_cannot_approve_or_edit(org_world):  # noqa: F811
    did = await _delegation(org_world, ["approvals:propose"])
    h = create_internal_auth_headers(delegation_id=did)
    async with _http(_app(org_world)) as client:
        row = (await client.post("/api/approvals/propose", json=FILE, headers=h)).json()
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 403
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=h)).status_code == 403
        assert (await client.patch(f"/api/approvals/{row['id']}", json={"title": "x"}, headers=h)).status_code == 403
