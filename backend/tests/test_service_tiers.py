"""Service tiers (Mac's model) behind ``service_tiers.enabled``: real SQL + AuthMiddleware.

Synthetic text only: no model call, no sends, nothing external. Covers:

* tier routing: each tier's draft reaches the right reviewer and nobody else;
* flag off (and no tier set) keeps the original owner/admin-only rule;
* service settings: member read, owner/admin compare-and-set write, validation;
* onboarding: contract text -> work plan -> PAUSED recurring scheduled tasks.
"""

from datetime import UTC, datetime

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from sqlalchemy import select
from test_client_portal import BASE, CUSTOMER_ORG, _app, _compose, _http, _seed_bound_customer

from app.gateway import service_onboarding as plan
from app.gateway import service_tiers
from app.gateway.routers import workspace_service, workspaces
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.board.model import BoardPortalRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.organizations.service import WorkspaceServiceSettingsRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.user.model import UserRow

USER_D = "user-d-unassigned"
SERVICE = f"/api/workspaces/{CUSTOMER_ORG}/service"
ONBOARDING = f"/api/onboarding/{CUSTOMER_ORG}"


@pytest.fixture
def tiers_on(monkeypatch):
    monkeypatch.setattr(service_tiers, "service_tiers_enabled", lambda: True)


@pytest.fixture
def tiers_off(monkeypatch):
    monkeypatch.setattr(service_tiers, "service_tiers_enabled", lambda: False)


async def _set_tier(sf, tier, *, booking_url=None):
    async with sf() as session, session.begin():
        session.add(WorkspaceServiceSettingsRow(organization_id=CUSTOMER_ORG, service_tier=tier, booking_url=booking_url, version=1))


async def _add_unassigned_member(sf):
    now = datetime.now(UTC)
    async with sf() as session, session.begin():
        session.add(UserRow(id=USER_D, email=f"{USER_D}@example.test", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=CUSTOMER_ORG, user_id=USER_D, role="member", status="active"))


def _full_app(sf, monkeypatch):
    app = _app(sf)
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: sf)
    app.state.scheduled_task_repo = ScheduledTaskRepository(sf)
    app.include_router(workspace_service.router)
    app.include_router(workspace_service.onboarding_router)
    return app


async def _drafted(client, contact, drafter):
    """A client request plus a staff draft waiting for review. Returns (path, publish body)."""
    created = await _compose(client, contact)
    path = f"{BASE}/{created['id']}"
    draft = await client.post(path + "/draft", headers=drafter, json={"expected_revision": 0, "body": "Synthetic reviewed draft", "attachments": [{"name": "plan.txt", "content": "Synthetic plan"}]})
    assert draft.status_code == 200, draft.text
    return path, {"approval_id": draft.json()["approval_id"], "expected_revision": 1}


def _headers():
    return tuple(auth_headers(user, CUSTOMER_ORG) for user in (USER_B, USER_C, USER_A))


# --- Tier routing -----------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_keeps_original_rule_even_with_a_stored_tier(org_world, tiers_off, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    await _set_tier(org_world, "software")
    contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)
        assert (await client.get(SERVICE, headers=owner)).status_code == 404
        assert (await client.post(path + "/approve", headers=contact, json=publish)).status_code == 404
        hidden = (await client.get(path, headers=contact)).json()
        assert "service_tier" not in hidden and "review" not in hidden and "can_approve" not in hidden
        assert (await client.post(path + "/publish", headers=member, json=publish)).status_code == 403
        published = await client.post(path + "/publish", headers=owner, json=publish)
        assert published.status_code == 200, published.text


@pytest.mark.asyncio
async def test_flag_on_without_a_tier_keeps_original_rule(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)
        assert (await client.post(path + "/approve", headers=contact, json=publish)).status_code == 404
        assert (await client.post(path + "/publish", headers=member, json=publish)).status_code == 403
        assert (await client.post(path + "/publish", headers=owner, json=publish)).status_code == 200


@pytest.mark.asyncio
async def test_software_tier_client_reviews_and_approves_in_their_own_inbox(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    await _set_tier(org_world, "software", booking_url="https://booking.example.test/momentum")
    contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)

        roster = (await client.get("/api/client-portal/clients", headers=contact)).json()
        assert roster["service"] == {"tier": "software", "booking_url": "https://booking.example.test/momentum"}
        staff_roster = (await client.get("/api/client-portal/clients", headers=owner)).json()
        assert staff_roster["can_review"] is False  # nothing waits on the team

        detail = (await client.get(path, headers=contact)).json()
        assert detail["service_tier"] == "software" and detail["can_approve"] is True and detail["can_review"] is False
        assert detail["review"]["body"] == "Synthetic reviewed draft" and detail["review"]["approval_id"] == publish["approval_id"]
        assert [a["name"] for a in detail["review"]["attachments"]] == ["plan.txt"]
        attachment = await client.get(f"{path}/messages/{detail['review']['message_id']}/attachments/plan.txt", headers=contact)
        assert attachment.status_code == 200 and attachment.text == "Synthetic plan"

        # Staff, even the owner, cannot publish over the client.
        for staff in (owner, member):
            refused = await client.post(path + "/publish", headers=staff, json=publish)
            assert refused.status_code == 403 and refused.json()["detail"] == service_tiers.CLIENT_REVIEWS
        assert (await client.post(f"/api/approvals/{publish['approval_id']}/approve", headers=owner)).status_code == 403
        caps = (await client.get(f"/api/approvals/{publish['approval_id']}", headers=owner)).json()["capabilities"]
        assert caps["approve"] is False and caps["reject"] is True and caps["reason"] == service_tiers.CLIENT_REVIEWS

        stale = await client.post(path + "/approve", headers=contact, json={**publish, "expected_revision": 9})
        assert stale.status_code == 409
        approved = await client.post(path + "/approve", headers=contact, json=publish)
        assert approved.status_code == 200, approved.text
        assert approved.json()["publish_receipt"] and approved.json()["messages"][-1]["body"] == "Synthetic reviewed draft"
        again = await client.post(path + "/approve", headers=contact, json=publish)
        assert again.status_code == 200 and again.json()["publish_receipt"] == approved.json()["publish_receipt"]


@pytest.mark.asyncio
async def test_software_tier_client_asks_for_changes(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    await _set_tier(org_world, "software")
    contact, member, _owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)
        assert (await client.post(path + "/request-changes", headers=member, json={**publish, "note": "x"})).status_code == 404
        changed = await client.post(path + "/request-changes", headers=contact, json={**publish, "note": "Please make it shorter."})
        assert changed.status_code == 200, changed.text
        body = changed.json()
        assert body["messages"][-1]["body"] == "Please make it shorter." and body["publish_receipt"] is None and "review" not in body
        async with org_world() as session:
            action = await session.get(PendingActionRow, publish["approval_id"])
            portal = await session.get(BoardPortalRow, path.rsplit("/", 1)[1])
        assert action.status == "rejected" and action.decided_by == USER_B and portal.approval_id is None
        # The declined draft can no longer be approved.
        assert (await client.post(path + "/approve", headers=contact, json=publish)).status_code == 409


@pytest.mark.asyncio
async def test_am_assisted_tier_assigned_account_manager_publishes_client_cannot(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    await _add_unassigned_member(org_world)
    await _set_tier(org_world, "am_assisted")
    contact, member, _owner = _headers()
    unassigned = auth_headers(USER_D, CUSTOMER_ORG)
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)

        client_view = (await client.get(path, headers=contact)).json()
        assert client_view["service_tier"] == "am_assisted" and "review" not in client_view and "draft" not in client_view
        assert client_view["review_reason"] == service_tiers.TEAM_REVIEWS
        refused = await client.post(path + "/approve", headers=contact, json=publish)
        assert refused.status_code == 403 and refused.json()["detail"] == service_tiers.TEAM_REVIEWS

        am_view = (await client.get(path, headers=member)).json()
        assert am_view["can_review"] is True
        caps = (await client.get(f"/api/approvals/{publish['approval_id']}", headers=member)).json()["capabilities"]
        assert caps["approve"] is True and caps["reject"] is True

        # A teammate who is not this client's account manager cannot even load the draft.
        other = await client.post(path + "/publish", headers=unassigned, json=publish)
        assert other.status_code in {403, 404}
        assert (await client.post(f"/api/approvals/{publish['approval_id']}/approve", headers=unassigned)).status_code in {403, 404}

        published = await client.post(path + "/publish", headers=member, json=publish)
        assert published.status_code == 200, published.text
        assert (await client.get(path, headers=contact)).json()["messages"][-1]["body"] == "Synthetic reviewed draft"


@pytest.mark.asyncio
async def test_standard_tier_team_reviews_and_client_sees_no_momobot_link(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    await _set_tier(org_world, "standard", booking_url="https://booking.example.test/ignored")
    contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        path, publish = await _drafted(client, contact, member)
        listed = (await client.get(BASE, headers=contact)).json()["threads"]
        assert listed and all(thread["momo_href"] is None for thread in listed)
        staff_listed = (await client.get(BASE, headers=member)).json()["threads"]
        assert all(thread["momo_href"] for thread in staff_listed)
        roster = (await client.get("/api/client-portal/clients", headers=contact)).json()
        assert roster["service"] == {"tier": "standard", "booking_url": None}
        chat = await client.post(path + "/chat", headers=contact, json={})
        assert chat.status_code == 403 and "team is handling" in chat.json()["detail"]
        assert (await client.post(path + "/approve", headers=contact, json=publish)).status_code == 403
        assert (await client.post(path + "/publish", headers=owner, json=publish)).status_code == 200


# --- Service settings -------------------------------------------------------


@pytest.mark.asyncio
async def test_service_settings_member_read_owner_write_with_compare_and_set(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        read = await client.get(SERVICE, headers=member)
        assert read.status_code == 200, read.text
        assert read.json()["service_tier"] is None and read.json()["version"] == 0 and read.json()["can_edit"] is False
        assert (await client.get(SERVICE, headers=contact)).status_code in {403, 404}
        good = {"service_tier": "software", "booking_url": "https://booking.example.test/call", "sold_by_user_id": USER_C, "expected_version": 0}
        assert (await client.put(SERVICE, headers=member, json=good)).status_code == 403

        for bad in (
            {**good, "service_tier": "premium"},
            {**good, "booking_url": "http://booking.example.test/call"},
            {**good, "booking_url": "https://user:secret@booking.example.test/"},
            {**good, "booking_url": "javascript:alert(1)"},
            {**good, "sold_by_user_id": USER_B},  # a client is never the seller
            {**good, "sold_by_user_id": "nobody"},
        ):
            assert (await client.put(SERVICE, headers=owner, json=bad)).status_code == 422, bad
        written = await client.put(SERVICE, headers=owner, json=good)
        assert written.status_code == 200, written.text
        assert written.json() | {"workspace_name": None} == written.json() | {
            "workspace_name": None,
            "service_tier": "software",
            "booking_url": "https://booking.example.test/call",
            "sold_by_user_id": USER_C,
            "version": 1,
            "can_edit": True,
        }
        assert (await client.put(SERVICE, headers=owner, json=good)).status_code == 412
        cleared = await client.put(SERVICE, headers=owner, json={"service_tier": None, "booking_url": None, "sold_by_user_id": None, "expected_version": 1})
        assert cleared.status_code == 200 and cleared.json()["service_tier"] is None and cleared.json()["version"] == 2


# --- Onboarding -------------------------------------------------------------

CONTRACT = """Scope of work for Synthetic Bakery

Deliverables:
- 4 blog posts per month
- Social media posts 3x per week
- Monthly performance report
- Google Ads management (ad spend $2,000/mo billed separately)
- Email newsletter twice a month
- Quarterly SEO audit
- Website audit and fixes
Payment: $1,500 per month, net 30
This agreement is between the parties named below.
"""


def test_contract_parser_maps_cadences_and_drops_money():
    items = plan.parse_contract(CONTRACT)
    got = [(item.title, item.kind, item.cadence, item.cron) for item in items]
    assert got == [
        ("4 blog posts per month", "seo", "weekly", "0 9 * * 1"),
        ("Social media posts 3x per week", "social", "3_per_week", "0 9 * * 1,3,5"),
        ("Monthly performance report", "reporting", "monthly", "0 9 1 * *"),
        ("Google Ads management (ad spend billed separately)", "ads", "once", None),
        ("Email newsletter twice a month", "email", "twice_monthly", "0 9 1,15 * *"),
        ("Quarterly SEO audit", "seo", "quarterly", "0 9 1 1,4,7,10 *"),
        ("Website audit and fixes", "website", "once", None),
    ]
    assert not any("$" in item.title or "1,500" in item.title for item in items)


@pytest.mark.parametrize(
    ("line", "cadence"),
    [
        ("Daily community replies", "daily"),
        ("2 posts per week", "2_per_week"),
        ("five posts a week", "weekdays"),
        ("Weekly social calendar", "weekly"),
        ("Biweekly email", "twice_monthly"),
        ("Every other week strategy notes", "twice_monthly"),
        ("2x monthly newsletter", "twice_monthly"),
        ("8 posts per month", "2_per_week"),
        ("Once a month report", "monthly"),
        ("Every quarter planning", "quarterly"),
        ("Brand guide", "once"),
    ],
)
def test_cadence_table(line, cadence):
    assert plan.detect_cadence(line) == cadence


def test_drafts_only_prompts_name_the_right_reviewer():
    item = plan.make_item("Weekly social calendar", "weekly")
    software = plan.task_prompt(item, workspace_name="Synthetic Bakery", tier="software")
    assisted = plan.task_prompt(item, workspace_name="Synthetic Bakery", tier="am_assisted")
    assert "client reviews every draft in their own inbox" in software
    assert "account manager reviews every draft in Approvals" in assisted
    for prompt in (software, assisted, plan.check_in_prompt(workspace_name="Synthetic Bakery", seller_name="the seller")):
        assert "Do not" in prompt and "publish" in prompt and "send" in prompt


@pytest.mark.asyncio
async def test_onboarding_preview_then_apply_creates_paused_tasks(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    _contact, member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        assert (await client.post(ONBOARDING + "/preview", headers=member, json={"contract_text": CONTRACT})).status_code == 403
        preview = await client.post(ONBOARDING + "/preview", headers=owner, json={"contract_text": CONTRACT})
        assert preview.status_code == 200, preview.text
        assert preview.json()["recurring"] == 5 and preview.json()["one_time"] == 2
        async with org_world() as session:
            assert (await session.scalars(select(ScheduledTaskRow))).all() == []  # preview writes nothing

        # Onboarding runs inside the workspace being set up, never across workspaces.
        elsewhere = await client.post(ONBOARDING + "/apply", headers=auth_headers(USER_A, ORG_S), json={"contract_text": CONTRACT, "expected_version": 0})
        assert elsewhere.status_code in {403, 404, 409}
        assert (await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": "nothing to see", "expected_version": 0})).status_code == 422

        applied = await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": CONTRACT, "expected_version": 0, "workspace_name": "Synthetic Bakery"})
        assert applied.status_code == 200, applied.text
        settings = applied.json()
        assert settings["workspace_name"] == "Synthetic Bakery" and settings["sold_by_user_id"] == USER_A and settings["check_in_task_id"]
        onboarding = settings["onboarding"]
        assert onboarding["contract_sha256"] == plan.contract_digest(CONTRACT) and "contract_text" not in onboarding
        assert CONTRACT not in str(onboarding)
        task_ids = {item["task_id"] for item in onboarding["items"] if item["cron"]}
        assert len(task_ids) == 5 and all("task_id" not in item for item in onboarding["items"] if not item["cron"])

        async with org_world() as session:
            tasks = (await session.scalars(select(ScheduledTaskRow))).all()
            workspace = await session.get(OrganizationRow, CUSTOMER_ORG)
        assert workspace.name == "Synthetic Bakery"
        assert {task.id for task in tasks} == task_ids | {settings["check_in_task_id"]}
        assert all(task.status == "paused" and task.schedule_type == "cron" for task in tasks)
        assert all(task.organization_id == CUSTOMER_ORG and "do not publish" in task.prompt.lower() for task in tasks)
        crons = sorted(task.schedule_spec["cron"] for task in tasks)
        assert crons == sorted(["0 9 * * 1", "0 9 * * 1,3,5", "0 9 1 * *", "0 9 1,15 * *", "0 9 1 1,4,7,10 *", "0 9 1 * *"])

        again = await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": CONTRACT, "expected_version": settings["version"]})
        assert again.status_code == 409
        stale = await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": CONTRACT, "expected_version": 0})
        assert stale.status_code == 412


@pytest.mark.asyncio
async def test_onboarding_uses_the_reviewed_plan_and_credits_another_seller_without_a_check_in(org_world, tiers_on, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    _contact, _member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        seller = await client.put(SERVICE, headers=owner, json={"service_tier": "am_assisted", "sold_by_user_id": USER_C, "expected_version": 0})
        assert seller.status_code == 200, seller.text
        reviewed = [{"title": "Weekly social calendar", "cadence": "weekly"}, {"title": "Brand guide", "cadence": "once"}]
        bad = await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": CONTRACT, "expected_version": 1, "items": [{"title": "x y z", "cadence": "hourly"}]})
        assert bad.status_code == 422, bad.text
        applied = await client.post(ONBOARDING + "/apply", headers=owner, json={"contract_text": CONTRACT, "expected_version": 1, "items": reviewed})
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["sold_by_user_id"] == USER_C and body["check_in_task_id"] is None and body["service_tier"] == "am_assisted"
        assert [item["title"] for item in body["onboarding"]["items"]] == ["Weekly social calendar", "Brand guide"]
        async with org_world() as session:
            tasks = (await session.scalars(select(ScheduledTaskRow))).all()
        assert len(tasks) == 1 and tasks[0].status == "paused"
        assert "account manager reviews every draft in Approvals" in tasks[0].prompt


@pytest.mark.asyncio
async def test_onboarding_routes_are_invisible_while_the_flag_is_off(org_world, tiers_off, monkeypatch):  # noqa: F811
    await _seed_bound_customer(org_world)
    _contact, _member, owner = _headers()
    async with _http(_full_app(org_world, monkeypatch)) as client:
        for method, url, payload in (
            ("put", SERVICE, {"service_tier": "software", "expected_version": 0}),
            ("post", ONBOARDING + "/preview", {"contract_text": CONTRACT}),
            ("post", ONBOARDING + "/apply", {"contract_text": CONTRACT, "expected_version": 0}),
        ):
            response = await getattr(client, method)(url, headers=owner, json=payload)
            assert response.status_code == 404, (url, response.text)
    async with org_world() as session:
        assert (await session.scalars(select(WorkspaceServiceSettingsRow))).all() == []
        assert (await session.scalars(select(ScheduledTaskRow))).all() == []
