"""Synthetic HTTP acceptance; no real accounts, credentials, or network calls."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from deerflow_extension_api import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI
from fastapi.testclient import TestClient

from northwind_placement import install
from northwind_placement.api import Service, build_router
from northwind_placement.store import Store, put

BASE = datetime(2026, 10, 20, 20, tzinfo=UTC)


def build_test_app(data_dir, user_id="jordan", organization_id="northwind", auth_source="session", principal=True, csrf=False):
    """Test-only host adapter; never install this identity stub in a real Gateway."""
    service = Service(
        {"data_dir": str(data_dir), "organization_id": "northwind", "allowed_user_ids": ["jordan", "avery"], "placement_confirmer_user_ids": ["jordan"]}
    )
    asyncio.run(service.start(None))
    app = FastAPI()
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal(user_id=user_id) if principal else None)

    @app.middleware("http")
    async def test_host_identity(request, call_next):
        request.state.auth_source = auth_source
        request.state.organization_id = organization_id
        return await call_next(request)

    app.include_router(build_router(service))
    if csrf:
        from app.gateway.csrf_middleware import CSRFMiddleware

        app.add_middleware(CSRFMiddleware)
    return app, service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("northwind_placement.api.now", lambda: BASE)
    monkeypatch.setattr("northwind_placement.store.now", lambda: BASE)
    app, _ = build_test_app(tmp_path)
    with TestClient(app) as result:
        yield result


def post(client, path, data, key=None):
    return client.post("/api/northwind" + path, json=data, headers={"Idempotency-Key": key or str(uuid4())})


def referral_data(**changes):
    return {
        "name": "Synthetic Family",
        "email": "family@example.test",
        "phone": "+1 (813) 555-0100",
        "responsible_contact": "Synthetic Adult Child",
        "location": "Hillsborough County",
        "budget_cents": 600000,
        "care_needs": "Help with daily tasks",
        "timing": "Within 30 days",
        "source_ref": "synthetic-form:submission-001",
        "contact_preference": "email",
        **changes,
    }


def qualified(client):
    referral = post(client, "/referrals", referral_data()).json()
    response = post(client, f"/referrals/{referral['id']}/transition", {"status": "Qualified", "human_confirmed": True})
    assert response.status_code == 200, response.text
    return response.json()


def community(client):
    response = post(
        client,
        "/communities",
        {
            "name": "Synthetic Community",
            "city": "Tampa",
            "services": ["assisted living"],
            "licensed_beds": 12,
            "source_url": "https://example.test/community",
            "observed_at": (BASE - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def placement(client, referral_id, community_id):
    response = post(
        client,
        "/placements",
        {
            "referral_id": referral_id,
            "community_id": community_id,
            "move_in_date": "2026-08-01",
            "agreement_signed_on": "2026-07-30",
            "agreement_ref": "synthetic-signed-agreement:001",
            "fee_cents": 600001,
            "terms": "50_50_day30_day60",
            "refund_terms": "Synthetic signed no-refund term",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "identity",
    [
        {"principal": False},
        {"auth_source": "auth_disabled"},
        {"auth_source": "internal"},
        {"auth_source": "pat"},
        {"organization_id": None},
        {"organization_id": "other-workspace"},
        {"user_id": "outsider"},
    ],
)
def test_auth_fails_closed(tmp_path, identity):
    app, _ = build_test_app(tmp_path, **identity)
    with TestClient(app) as client:
        assert client.get("/api/northwind/state").status_code in (401, 403)
        assert client.get("/api/northwind/dashboard/").status_code in (401, 403)
        assert post(client, "/referrals", referral_data()).status_code in (401, 403)
    assert not list(tmp_path.iterdir())


def test_identity_isolation_and_restart(client, tmp_path):
    referral = post(client, "/referrals", referral_data(), "import-001").json()
    for identity in [{"user_id": "outsider"}, {"organization_id": "other-workspace"}]:
        app, _ = build_test_app(tmp_path, **identity)
        with TestClient(app) as isolated:
            assert isolated.get("/api/northwind/state").status_code == 403
            assert isolated.get(f"/api/northwind/referrals/{referral['id']}").status_code == 403
            assert post(isolated, "/referrals", referral_data(), "import-001").status_code == 403
    app, _ = build_test_app(tmp_path, user_id="avery")
    with TestClient(app) as avery:
        assert avery.get(f"/api/northwind/referrals/{referral['id']}").json()["name"] == "Synthetic Family"
        grace_referral = post(
            avery,
            "/referrals",
            referral_data(source_ref="synthetic-form:avery", email="avery@example.test", phone="813-555-0199"),
            "import-001",
        )
        assert grace_referral.status_code == 201
        assert grace_referral.json()["id"] != referral["id"]
        response = avery.patch(
            f"/api/northwind/referrals/{referral['id']}", json={"expected_version": 1, "name": "Synthetic Avery update"}, headers={"Idempotency-Key": "update"}
        )
        assert response.status_code == 200
    app, _ = build_test_app(tmp_path)
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/northwind/referrals/{referral['id']}").json()["name"] == "Synthetic Avery update"
        assert post(restarted, "/referrals", referral_data(), "import-001").json()["id"] == referral["id"]
        assert restarted.get("/api/northwind/state").json()["audit"][0]["actor"] == "avery"


def test_source_replay_duplicate_contacts_and_conflicts(client):
    original = post(client, "/referrals", referral_data(), "source-retry").json()
    assert post(client, "/referrals", referral_data(), "source-retry").json() == original
    assert post(client, "/referrals", referral_data()).json()["id"] == original["id"]
    assert post(client, "/referrals", referral_data(name="Different family")).status_code == 409
    response = post(
        client, "/referrals", referral_data(source_ref="different-source", email="other@example.test", phone="813-555-0100", name="Different family")
    )
    assert response.status_code == 409
    assert response.json()["detail"]["duplicate_ids"] == [original["id"]]
    assert post(client, "/referrals", referral_data(name="changed"), "source-retry").status_code == 409
    no_contact = {"name": "Synthetic Incomplete", "source_ref": "blank-contact-source"}
    first = post(client, "/referrals", no_contact).json()
    assert post(client, "/referrals", no_contact).json()["id"] == first["id"]
    assert len(client.get("/api/northwind/state").json()["referrals"]) == 2


def test_intake_missing_info_attention_and_version(client):
    referral = post(client, "/referrals", {"name": "Synthetic Incomplete", "source_ref": "manual:001", "attention": "human_request"}).json()
    assert "phone_or_email" in referral["missing_info"]
    assert referral["handoff_status"] == "unconnected"
    assert post(client, f"/referrals/{referral['id']}/transition", {"status": "Qualified", "human_confirmed": True}).status_code == 409
    patch = {"expected_version": 1, **referral_data(source_ref="manual:001")}
    response = client.patch(f"/api/northwind/referrals/{referral['id']}", json=patch, headers={"Idempotency-Key": "patch"})
    assert response.status_code == 200, response.text
    assert response.json()["missing_info"] == []
    assert client.patch(f"/api/northwind/referrals/{referral['id']}", json=patch, headers={"Idempotency-Key": "stale"}).status_code == 409
    invalid = {"expected_version": 2, "name": None}
    assert client.patch(f"/api/northwind/referrals/{referral['id']}", json=invalid, headers={"Idempotency-Key": "invalid"}).status_code == 422
    immutable = {"expected_version": 2, "source_ref": "manual:changed"}
    assert client.patch(f"/api/northwind/referrals/{referral['id']}", json=immutable, headers={"Idempotency-Key": "immutable"}).status_code == 409
    assert client.get("/api/northwind/state").json()["briefing"]["human_callback_needed"] == 1


def test_stop_suppression_survives_restart_and_contact_change(client, tmp_path):
    referral = post(client, "/referrals", referral_data()).json()
    path = f"/referrals/{referral['id']}"
    assert post(client, path + "/drafts", {"reason": "no_booking", "body": "Synthetic unsent follow-up"}).status_code == 201
    assert post(client, path + "/contact-events", {"event": "stop"}).json()["contact_status"] == "stopped"
    assert post(client, path + "/contact-events", {"event": "reply"}).json()["contact_status"] == "stopped"
    version = client.get("/api/northwind" + path).json()["version"]
    assert (
        client.patch(
            "/api/northwind" + path,
            json={"expected_version": version, "email": "new@example.test", "phone": "8135550101"},
            headers={"Idempotency-Key": "change-contact"},
        ).status_code
        == 200
    )
    app, _ = build_test_app(tmp_path)
    with TestClient(app) as restarted:
        assert post(restarted, path + "/drafts", {"reason": "no_booking", "body": "Never send"}).status_code == 409
        assert restarted.get("/api/northwind/state").json()["drafts"][0]["status"] == "suppressed"
        returning = post(restarted, "/referrals", referral_data(source_ref="old-contact-return")).json()
        assert returning["contact_status"] == "stopped"
        assert (
            restarted.patch(
                f"/api/northwind/referrals/{returning['id']}",
                json={"expected_version": 1, "email": "archived@example.test", "phone": "8135550188"},
                headers={"Idempotency-Key": "archive-returning-contact"},
            ).status_code
            == 200
        )

        active = post(
            restarted,
            "/referrals",
            referral_data(source_ref="second-family", email="second@example.test", phone="8135550199"),
        ).json()
        assert post(restarted, f"/referrals/{active['id']}/drafts", {"reason": "planning", "body": "Do not send"}).status_code == 201
        response = restarted.patch(
            f"/api/northwind/referrals/{active['id']}",
            json={"expected_version": 1, "email": "family@example.test"},
            headers={"Idempotency-Key": "suppressed-contact-edit"},
        )
        assert response.status_code == 200
        assert response.json()["contact_status"] == "stopped"
        draft = next(d for d in restarted.get("/api/northwind/state").json()["drafts"] if d["referral_id"] == active["id"])
        assert draft["status"] == "suppressed"


@pytest.mark.parametrize("event", ["reply", "decline", "booking"])
def test_response_events_pause_drafts(client, event):
    referral = post(client, "/referrals", referral_data()).json()
    path = f"/referrals/{referral['id']}"
    assert post(client, path + "/drafts", {"reason": "planning", "body": "Synthetic planning follow-up"}).status_code == 201
    post(client, path + "/contact-events", {"event": event})
    assert client.get("/api/northwind/state").json()["drafts"][0]["status"] == "paused"
    assert post(client, path + "/drafts", {"reason": "planning", "body": "Paused"}).status_code == 409


def test_capacity_never_becomes_availability_and_expiry(client, monkeypatch):
    record = community(client)
    assert record["licensed_beds"] == 12
    assert record["availability"] == {"status": "unknown", "vacancies": None}
    payload = {
        "vacancies": 2,
        "verified_at": BASE.isoformat(),
        "expires_at": (BASE + timedelta(days=1)).isoformat(),
        "source_ref": "synthetic-call-note",
        "human_confirmed": True,
    }
    response = post(client, f"/communities/{record['id']}/availability", payload)
    assert response.status_code == 200, response.text
    assert response.json()["availability"]["vacancies"] == 2
    monkeypatch.setattr("northwind_placement.api.now", lambda: BASE + timedelta(days=2))
    expired = client.get("/api/northwind/state").json()["communities"][0]["availability"]
    assert expired["status"] == "expired" and expired["vacancies"] is None
    assert post(client, f"/communities/{record['id']}/availability", {**payload, "expires_at": (BASE + timedelta(days=9)).isoformat()}).status_code == 422
    newer = {**payload, "verified_at": (BASE + timedelta(days=1)).isoformat(), "expires_at": (BASE + timedelta(days=3)).isoformat()}
    assert post(client, f"/communities/{record['id']}/availability", newer).status_code == 200
    stale = {**payload, "verified_at": (BASE + timedelta(hours=12)).isoformat(), "expires_at": (BASE + timedelta(days=3)).isoformat()}
    assert post(client, f"/communities/{record['id']}/availability", stale).status_code == 409
    stored = client.get("/api/northwind/state").json()["communities"][0]["availability"]["verified_at"]
    assert datetime.fromisoformat(stored) == datetime.fromisoformat(newer["verified_at"])


def test_tours_proposed_only_collisions_and_adjacent_slots(client):
    referral, place = qualified(client), community(client)
    payload = {
        "referral_id": referral["id"],
        "community_id": place["id"],
        "start_at": (BASE + timedelta(days=1)).isoformat(),
        "end_at": (BASE + timedelta(days=1, hours=1)).isoformat(),
    }
    tour = post(client, "/tours", payload).json()
    assert tour["status"] == "proposed" and tour["calendar_connected"] is False
    assert tour["availability_at_proposal"]["status"] == "unknown"
    assert post(client, "/tours", payload).status_code == 409
    assert post(client, "/tours", {**payload, "start_at": payload["end_at"], "end_at": (BASE + timedelta(days=1, hours=2)).isoformat()}).status_code == 201
    assert post(client, f"/tours/{tour['id']}/confirm", {"confirmed": True}).status_code == 404
    assert post(client, f"/referrals/{referral['id']}/transition", {"status": "Touring", "human_confirmed": True}).status_code == 200


def test_fees_exact_cents_receipts_and_separate_totals(client):
    referral, place = qualified(client), community(client)
    record = placement(client, referral["id"], place["id"])
    assert (
        post(
            client,
            "/placements",
            {
                "referral_id": referral["id"],
                "community_id": place["id"],
                "move_in_date": "2026-08-01",
                "agreement_signed_on": "2026-07-30",
                "agreement_ref": "synthetic-signed-agreement:002",
                "fee_cents": 600001,
                "terms": "50_50_day30_day60",
                "refund_terms": "Synthetic signed no-refund term",
            },
        ).status_code
        == 409
    )
    assert record["installments"] == [
        {"day": 30, "due_date": "2026-08-31", "amount_cents": 300000},
        {"day": 60, "due_date": "2026-09-30", "amount_cents": 300001},
    ]
    endpoint = f"/placements/{record['id']}/ledger"
    receipt = {"kind": "collected", "day": 30, "amount_cents": 300000, "event_date": "2026-09-01", "receipt_ref": "synthetic-payment:001"}
    assert post(client, endpoint, receipt).status_code == 409
    assert post(client, endpoint, {**receipt, "kind": "invoiced", "receipt_ref": "synthetic-invoice:001"}).status_code == 201
    first = post(client, endpoint, receipt, "payment-001").json()
    assert post(client, endpoint, receipt, "payment-001").json() == first
    assert post(client, endpoint, receipt).status_code == 409
    assert post(client, endpoint, {**receipt, "amount_cents": 1, "receipt_ref": "too-much"}).status_code == 409
    brief = client.get("/api/northwind/state").json()["briefing"]
    assert (brief["contracted_cents"], brief["invoiced_cents"], brief["collected_cents"], brief["due_cents"]) == (600001, 300000, 300000, 300001)
    assert brief["costs_cents"] is None


def test_store_serializes_retries_and_separates_workspaces(tmp_path):
    store = Store(tmp_path, "northwind", "workspace-a", "jordan")

    def write_once():
        return store.mutate("same-key", "test.write", {"value": 1}, lambda connection: put(connection, "test", {"id": "record-1", "value": 1}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: write_once(), range(2))) == [{"id": "record-1", "value": 1}] * 2
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1
    assert store.path != Store(tmp_path, "other", "workspace-a", "jordan").path
    assert store.path != Store(tmp_path, "northwind", "workspace-b", "jordan").path


def test_placement_requires_configured_confirmer_and_signed_terms(tmp_path, monkeypatch):
    monkeypatch.setattr("northwind_placement.api.now", lambda: BASE)
    app, _ = build_test_app(tmp_path, user_id="avery")
    with TestClient(app) as client:
        referral, place = qualified(client), community(client)
        payload = {
            "referral_id": referral["id"],
            "community_id": place["id"],
            "move_in_date": "2026-10-20",
            "agreement_signed_on": "2026-10-19",
            "agreement_ref": "synthetic-contract",
            "fee_cents": 600000,
            "terms": "50_50_day30_day60",
            "refund_terms": "Recorded signed term",
        }
        assert post(client, "/placements", payload).status_code == 403
        assert post(client, "/placements", {**payload, "fee_cents": 0.5}).status_code == 422
        assert post(client, "/placements", {**payload, "agreement_ref": ""}).status_code == 422


def test_extension_registration_and_stop(tmp_path):
    class Registry:
        def service(self, service):
            self.instance = service

        def routers(self, routers):
            self.routes = routers

    registry = Registry()
    install(registry, {"data_dir": str(tmp_path), "organization_id": "northwind", "allowed_user_ids": ["jordan"]})
    assert registry.routes[0].prefix == "/api/northwind"
    app, service = build_test_app(tmp_path)
    asyncio.run(service.stop())
    with TestClient(app) as client:
        assert client.get("/api/northwind/state").status_code == 503


def test_required_retry_key_no_cache_and_unknown_fields(client):
    assert client.post("/api/northwind/referrals", json=referral_data()).status_code == 422
    assert post(client, "/referrals", referral_data(status="Placed")).status_code == 422
    assert client.get("/api/northwind/state").headers["cache-control"] == "no-store"


def test_real_host_csrf_middleware(tmp_path, monkeypatch):
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    app, _ = build_test_app(tmp_path, csrf=True)
    with TestClient(app) as client:
        assert post(client, "/referrals", referral_data()).status_code == 403
        client.cookies.set("csrf_token", "synthetic-test-token")
        headers = {"Idempotency-Key": "csrf-success", "X-CSRF-Token": "wrong-token"}
        assert client.post("/api/northwind/referrals", json=referral_data(), headers=headers).status_code == 403
        headers["X-CSRF-Token"] = "synthetic-test-token"
        assert client.post("/api/northwind/referrals", json=referral_data(), headers=headers).status_code == 201
        assert len(client.get("/api/northwind/state").json()["referrals"]) == 1


def test_business_dates_follow_florida_midnight(client, monkeypatch):
    monkeypatch.setattr("northwind_placement.api.now", lambda: datetime(2026, 10, 21, 1, tzinfo=UTC))
    referral, place = qualified(client), community(client)
    data = {
        "referral_id": referral["id"],
        "community_id": place["id"],
        "move_in_date": "2026-10-21",
        "agreement_signed_on": "2026-09-20",
        "agreement_ref": "synthetic-contract",
        "fee_cents": 600000,
        "terms": "50_50_day30_day60",
        "refund_terms": "Synthetic signed terms",
    }
    assert post(client, "/placements", data).status_code == 422
    response = post(client, "/placements", {**data, "move_in_date": "2026-09-21"})
    assert response.status_code == 201
    record = response.json()
    assert record["installments"][0]["due_date"] == "2026-10-21"
    assert client.get("/api/northwind/state").json()["briefing"]["due_cents"] == 0
    receipt = {"kind": "invoiced", "day": 30, "amount_cents": 300000, "event_date": "2026-10-21", "receipt_ref": "synthetic-invoice"}
    assert post(client, f"/placements/{record['id']}/ledger", receipt).status_code == 422
    monkeypatch.setattr("northwind_placement.api.now", lambda: datetime(2026, 10, 21, 4, tzinfo=UTC))
    assert client.get("/api/northwind/state").json()["briefing"]["due_cents"] == 300000
    assert post(client, f"/placements/{record['id']}/ledger", receipt).status_code == 201
