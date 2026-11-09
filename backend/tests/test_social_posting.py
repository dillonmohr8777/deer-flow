"""Social posting inside MomoBot: approve to publish on the workspace page.

One test per rule: approve publishes exactly once, reject never publishes, a
failure shows as failed, switches off answer 404 or "unavailable", the public
page shows only published posts of enabled workspaces, and auto-publish only
ever applies to the workspace's own MomoBot page. Business names are made up.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from sqlalchemy import func, select, update

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals, social_posting
from deerflow.approvals import InvalidPayloadError, validate_payload
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.social.model import SocialPostRow
from deerflow.persistence.user.model import UserRow
from deerflow.social import ACTION_TYPE, TARGET_OWN_PAGE, WorkspaceSocial, load_settings, page_url, publish_approved, save_settings
from deerflow.tools.builtins.propose_social_post_tool import propose_social_post
from deerflow.tools.tools import get_available_tools

pytestmark = pytest.mark.asyncio

BAKERY = "Maple Street Bakery"


def _config(enabled: bool) -> AppConfig:
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "social_posting": {"enabled": enabled}})


@pytest.fixture(autouse=True)
def social_on():
    set_app_config(_config(True))
    yield
    reset_app_config()


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(approvals.router)
    app.include_router(social_posting.router)
    app.include_router(social_posting.public_router)
    return app


def _http(session_factory):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test")


async def _enable(session_factory, organization_id=ORG_A, actor=USER_A, **kw) -> WorkspaceSocial:
    async with session_factory() as session, session.begin():
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == organization_id).values(name=BAKERY))
    return await save_settings(session_factory, organization_id, actor_user_id=actor, business_name=BAKERY, enabled=True, **kw)


async def _file(session_factory, text="Fresh sourdough is out of the oven.", user="user-a", **payload) -> dict:
    settings = await load_settings(session_factory, ORG_S if user == "storage-s" else ORG_A)
    body = {"text": text, "page_url": page_url(settings.public_slug or "pending")} | payload
    return await PendingActionRepository(session_factory).create(action_type=ACTION_TYPE, target=TARGET_OWN_PAGE, payload=body, title=f"Social post: {text[:40]}", user_id=user)


async def _post_count(session_factory) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(SocialPostRow))).scalar_one()


async def _add_member(session_factory, user_id="plain"):
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


def _runtime(user=USER_A):
    return SimpleNamespace(context={"user_id": user, "thread_id": "t-1", "run_id": "r-1", "agent_name": "momo"}, config={})


# --- payload rules ------------------------------------------------------------


async def test_payload_rules():
    validate_payload(ACTION_TYPE, TARGET_OWN_PAGE, {"text": "Open late on Fridays.", "link": "https://example.com/menu", "page_url": "/x"})
    for target, payload in (
        (TARGET_OWN_PAGE, {"text": "   "}),
        (TARGET_OWN_PAGE, {"text": "x" * 3001}),
        (TARGET_OWN_PAGE, {"text": "ok", "link": "javascript:alert(1)"}),
        (TARGET_OWN_PAGE, {"text": "ok", "channel": "facebook"}),
        ("facebook_page", {"text": "ok"}),
    ):
        with pytest.raises(InvalidPayloadError):
            validate_payload(ACTION_TYPE, target, payload)


# --- approve publishes exactly once ------------------------------------------


async def test_approve_publishes_exactly_once(org_world):  # noqa: F811
    settings = await _enable(org_world)
    row = await _file(org_world)
    assert await _post_count(org_world) == 0  # proposing never publishes
    async with _http(org_world) as client:
        h = auth_headers(USER_A)
        done = (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).json()
        assert done["status"] == "executed", done
        assert done["execution_result"]["live_url"] == page_url(settings.public_slug)
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 409
    again = await publish_approved(org_world, await PendingActionRepository(org_world).get(row["id"], user_id=USER_A))
    assert again.status == "executed" and again.detail["post_id"] == done["execution_result"]["post_id"]
    assert await _post_count(org_world) == 1


async def test_reject_never_publishes(org_world):  # noqa: F811
    settings = await _enable(org_world)
    row = await _file(org_world, text="Rejected draft about muffins.")
    async with _http(org_world) as client:
        h = auth_headers(USER_A)
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=h)).json()["status"] == "rejected"
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 409
        page = await client.get(f"/api/public/social/{settings.public_slug}")
    assert await _post_count(org_world) == 0
    assert "Rejected draft" not in page.text


# --- failure shows as failed -----------------------------------------------------


@pytest.mark.parametrize("switch", ["workspace", "global"])
async def test_switched_off_after_filing_marks_failed(org_world, switch):  # noqa: F811
    await _enable(org_world)
    row = await _file(org_world)
    if switch == "workspace":
        await save_settings(org_world, ORG_A, actor_user_id=USER_A, business_name=BAKERY, enabled=False)
    else:
        set_app_config(_config(False))
    async with _http(org_world) as client:
        out = (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))).json()
    assert out["status"] == "failed" and "turned off" in out["error"]
    assert await _post_count(org_world) == 0


async def test_publisher_crash_marks_failed(org_world, monkeypatch):  # noqa: F811
    await _enable(org_world)
    row = await _file(org_world)

    async def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(social_posting, "publish_approved", boom)
    async with _http(org_world) as client:
        out = (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))).json()
    assert out["status"] == "failed" and out["error"]
    assert await _post_count(org_world) == 0


# --- switches off: 404 or unavailable ------------------------------------------


async def test_global_flag_off_hides_every_surface(org_world):  # noqa: F811
    settings = await _enable(org_world)
    set_app_config(_config(False))
    async with _http(org_world) as client:
        h = auth_headers(USER_A)
        assert (await client.get("/api/social/settings", headers=h)).status_code == 404
        assert (await client.put("/api/social/settings", json={"enabled": True}, headers=h)).status_code == 404
        assert (await client.get("/api/social/posts", headers=h)).status_code == 404
        assert (await client.get(f"/api/public/social/{settings.public_slug}")).status_code == 404
    assert "not available" in await propose_social_post.coroutine(runtime=_runtime(), text="Hello")
    for enabled in (False, True):
        names = {t.name for t in get_available_tools(app_config=_config(enabled), include_mcp=False, groups=[])}
        assert ("propose_social_post" in names) is enabled


async def test_workspace_switch_off_by_default(org_world):  # noqa: F811
    assert (await load_settings(org_world, ORG_A)).enabled is False
    await _add_member(org_world)
    async with _http(org_world) as client:
        admin = (await client.get("/api/social/settings", headers=auth_headers(USER_A))).json()
        assert admin["enabled"] is False and admin["public_url"] is None and admin["can_manage"] is True
        assert (await client.get("/api/social/settings", headers=auth_headers("plain", ORG_S))).status_code == 404
        assert (await client.get("/api/social/posts", headers=auth_headers(USER_A))).status_code == 404
    assert "turned off for this workspace" in await propose_social_post.coroutine(runtime=_runtime(), text="Hello")
    assert await PendingActionRepository(org_world).list(user_id=USER_A) == []


async def test_only_admins_change_the_switch_and_slug_hides_ids(org_world):  # noqa: F811
    await _add_member(org_world)
    async with _http(org_world) as client:
        assert (await client.put("/api/social/settings", json={"enabled": True}, headers=auth_headers("plain", ORG_S))).status_code == 403
        out = await client.put("/api/social/settings", json={"enabled": True}, headers=auth_headers(USER_C, ORG_S))
    assert out.status_code == 200, out.text
    url = out.json()["public_url"]
    assert url and url.startswith("/api/public/social/")
    assert ORG_S not in url and "storage" not in url


# --- public page ---------------------------------------------------------------


async def test_public_page_shows_only_published_posts_newest_first(org_world):  # noqa: F811
    settings = await _enable(org_world)
    first = await _file(org_world, text="First: croissants are back.")
    second = await _file(org_world, text="Second: <script>alert(1)</script> rye loaves.")
    rejected = await _file(org_world, text="Never shown: rejected.")
    await _file(org_world, text="Never shown: still pending.")
    async with _http(org_world) as client:
        h = auth_headers(USER_A)
        for row in (first, second):
            assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).json()["status"] == "executed"
        await client.post(f"/api/approvals/{rejected['id']}/reject", headers=h)
        page = await client.get(f"/api/public/social/{settings.public_slug}")
        unknown = await client.get("/api/public/social/no-such-page-1234abcd")
        listing = (await client.get("/api/social/posts", headers=h)).json()
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert '<meta name="robots" content="noindex, nofollow">' in page.text
    assert BAKERY in page.text
    assert "Never shown" not in page.text
    assert "<script" not in page.text and "&lt;script&gt;" in page.text
    assert page.text.index("Second:") < page.text.index("First:")
    assert unknown.status_code == 404
    assert {item["status_label"] for item in listing["items"]} == {"Published", "Rejected", "Waiting for approval"}
    assert listing["page_url"] == page_url(settings.public_slug)


async def test_public_page_404_for_disabled_workspace(org_world):  # noqa: F811
    settings = await _enable(org_world)
    row = await _file(org_world)
    async with _http(org_world) as client:
        await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))
        assert (await client.get(f"/api/public/social/{settings.public_slug}")).status_code == 200
        await save_settings(org_world, ORG_A, actor_user_id=USER_A, business_name=BAKERY, enabled=False)
        assert (await client.get(f"/api/public/social/{settings.public_slug}")).status_code == 404


async def test_other_workspace_cannot_approve_or_list(org_world):  # noqa: F811
    await _enable(org_world)
    row = await _file(org_world)
    async with _http(org_world) as client:
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_B))).status_code == 404
        assert (await client.get("/api/social/posts", headers=auth_headers(USER_B))).status_code == 404
    assert await _post_count(org_world) == 0


# --- agent tool and auto-publish ------------------------------------------------


async def test_tool_files_for_approval_by_default(org_world):  # noqa: F811
    settings = await _enable(org_world)
    out = json.loads(await propose_social_post.coroutine(runtime=_runtime(), text="Pumpkin bread is back this week."))
    assert out["status"] == "pending_approval" and out["page_url"] == page_url(settings.public_slug)
    row = await PendingActionRepository(org_world).get(out["id"], user_id=USER_A)
    assert row["status"] == "pending" and row["action_type"] == ACTION_TYPE and row["target"] == TARGET_OWN_PAGE
    assert row["payload"]["text"] == "Pumpkin bread is back this week."
    assert await _post_count(org_world) == 0
