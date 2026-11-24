"""Synthetic tests for SRS Placement Desk v2: custom facilities, monthly FHF sync,
weekly 5-facility contract sprint, Monday 3-bucket vacancy pulse, Day 7/30/60
post-placement check-in cadence, and workspace-scoped ModelTools.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import MappingProxyType

import pytest
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.plugins import ToolContext
from fastapi.testclient import TestClient
from test_api import BASE, build_test_app, post, qualified

from vhin_placement.api import Service
from vhin_placement.models import PulseSubmission
from vhin_placement.tools import build_plugin


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr("vhin_placement.api.now", lambda: BASE)
    monkeypatch.setattr("vhin_placement.store.now", lambda: BASE)


@pytest.fixture
def owner_env(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("VHIN_PULSE_SECRET", "test-only")
    app, service = build_test_app(tmp_path)
    with TestClient(app) as client:
        yield client, service, tmp_path


def test_custom_facility_without_url_and_patch_rates(owner_env):
    client, _, _ = owner_env
    # Brand-new pre-listing opening (no source_url or observed_at required)
    res = post(
        client,
        "/communities",
        {
            "name": "Synthetic Gallery",
            "city": "Brandon",
            "category": "Assisted Living Facility",
            "care_levels": ["Assisted Living", "Memory Care", "Independent Living"],
            "services": ["assisted living", "memory care", "independent living"],
            "licensed_beds": 300,
            "miles_from_office": 1.0,
            "private_rate_range": "$5,800 - $7,200",
            "community_fee": "$2,500",
            "accepts_medicaid": False,
            "accepts_va": True,
            "contact_email": "admin@synthetic-gallery.test",
            "contact_sms_phone": "813-555-0199",
            "preferred_pulse_channel": "both",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["source_kind"] == "owner_added"
    assert body["source_url"] is None
    assert body["preferred_pulse_channel"] == "both"
    assert "UNCONTRACTED" in body["contract_warning"]

    # Patch updates rates/channel without clobbering existing fields
    patched = client.patch(
        f"/api/vhin/communities/{body['id']}",
        json={"private_rate_range": "$6,000 - $7,500", "preferred_pulse_channel": "sms"},
        headers={"Idempotency-Key": "patch-gallery-1"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["private_rate_range"] == "$6,000 - $7,500"
    assert patched.json()["preferred_pulse_channel"] == "sms"


def test_monthly_fhf_sync_preserves_owner_ratings_contracts_and_custom_homes(owner_env, tmp_path):
    client, _, _ = owner_env
    # 1. Seed a custom owner_added home that FHF does not list yet
    custom = post(
        client,
        "/communities",
        {
            "name": "Synthetic Gallery",
            "city": "Brandon",
            "category": "Assisted Living Facility",
            "licensed_beds": 300,
            "miles_from_office": 1.0,
        },
    ).json()
    post(client, f"/communities/{custom['id']}/rating", {"stars": 3, "note": "Brand new, spotless"})

    # 2. First monthly FHF sync adds 2 licensed homes
    sync1 = post(
        client,
        "/communities/sync-directory",
        {
            "source_label": "florida_health_finder_2026_11",
            "items": [
                {
                    "name": "Synthetic Palms ALF",
                    "city": "Brandon",
                    "category": "Assisted Living Facility",
                    "licensed_beds": 40,
                    "ahca_license": "ALF #11111",
                    "miles_from_office": 2.1,
                    "contact_phone": "813-555-0111",
                },
                {
                    "name": "Synthetic Gallery",
                    "city": "Brandon",
                    "category": "Assisted Living Facility",
                    "licensed_beds": 250,
                    "miles_from_office": 1.2,
                },
            ],
        },
    )
    assert sync1.status_code == 200, sync1.text
    assert sync1.json()["added"] == 1
    assert sync1.json()["preserved_custom"] == 1

    # Owner rates and contracts Synthetic Palms ALF
    state = client.get("/api/vhin/state").json()
    palms = next(c for c in state["communities"] if c["name"] == "Synthetic Palms ALF")
    post(client, f"/communities/{palms['id']}/contract", {"status": "contracted", "agreement_ref": "agr-1", "human_confirmed": True})
    post(client, f"/communities/{palms['id']}/rating", {"stars": 3, "note": "Warm staff"})

    # 3. Second monthly FHF sync updates bed count on Palms but preserves contract + 3-star rating
    sync2 = post(
        client,
        "/communities/sync-directory",
        {
            "source_label": "florida_health_finder_2026_12",
            "items": [
                {
                    "name": "Synthetic Palms ALF",
                    "city": "Brandon",
                    "category": "Assisted Living Facility",
                    "licensed_beds": 46,
                    "ahca_license": "ALF #11111",
                    "miles_from_office": 2.1,
                }
            ],
        },
    )
    assert sync2.status_code == 200, sync2.text
    assert sync2.json()["updated"] == 1
    after = client.get("/api/vhin/state").json()
    palms_after = next(c for c in after["communities"] if c["id"] == palms["id"])
    assert palms_after["licensed_beds"] == 46
    assert palms_after["contract_status"] == "contracted"
    assert palms_after["owner_rating"]["stars"] == 3
    assert palms_after["owner_rating"]["note"] == "Warm staff"
    gallery_after = next(c for c in after["communities"] if c["id"] == custom["id"])
    assert gallery_after["licensed_beds"] == 300  # untouched custom record


def test_weekly_five_facility_contracting_sprint(owner_env):
    client, _, _ = owner_env
    # Create 6 uncontracted ALFs + 1 contracted ALF + 1 non-residential companion agency
    for i in range(1, 7):
        post(
            client,
            "/communities",
            {
                "name": f"Synthetic Target {i}",
                "city": "Brandon",
                "category": "Assisted Living Facility",
                "licensed_beds": 20 * i,
                "miles_from_office": float(i),
            },
        )
    signed = post(
        client,
        "/communities",
        {
            "name": "Already Contracted Home",
            "city": "Brandon",
            "category": "Assisted Living Facility",
            "licensed_beds": 100,
            "miles_from_office": 0.5,
        },
    ).json()
    post(client, f"/communities/{signed['id']}/contract", {"status": "contracted", "agreement_ref": "agr-signed", "human_confirmed": True})
    post(
        client,
        "/communities",
        {
            "name": "Companion Agency",
            "city": "Brandon",
            "category": "Homemaker & Companion Services",
            "miles_from_office": 0.2,
        },
    )

    sprint = client.get("/api/vhin/contract-sprint", params={"max_miles": 10, "limit": 5})
    assert sprint.status_code == 200, sprint.text
    data = sprint.json()
    assert data["total_uncontracted_in_radius"] == 6
    assert [t["name"] for t in data["targets"]] == [
        "Synthetic Target 1",
        "Synthetic Target 2",
        "Synthetic Target 3",
        "Synthetic Target 4",
        "Synthetic Target 5",
    ]


def test_monday_zero_typing_vacancy_pulse_three_buckets_and_rates(owner_env):
    client, service, _ = owner_env
    contracted_home = post(
        client,
        "/communities",
        {
            "name": "Synthetic Contracted ALF",
            "city": "Brandon",
            "category": "Assisted Living Facility",
            "contact_email": "director@contracted.test",
            "contact_sms_phone": "813-555-0123",
            "preferred_pulse_channel": "both",
        },
    ).json()
    post(client, f"/communities/{contracted_home['id']}/contract", {"status": "contracted", "agreement_ref": "agr-2", "human_confirmed": True})
    uncontracted_home = post(
        client,
        "/communities",
        {
            "name": "Synthetic Uncontracted ALF",
            "city": "Brandon",
            "category": "Assisted Living Facility",
            "contact_email": "director@uncontracted.test",
        },
    ).json()
    assert uncontracted_home["id"]

    generated = client.post("/api/vhin/pulse/generate")
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["sent"] is False
    assert payload["count"] == 1
    link = payload["links"][0]
    assert link["community_id"] == contracted_home["id"]
    assert link["preferred_pulse_channel"] == "both"
    assert link["contact_sms_phone"] == "813-555-0123"
    token = link["pulse_url"].rsplit("/", 1)[-1]

    # Inspect + submit public 3-bucket vacancy pulse (no session needed)
    info = service.inspect_public_pulse(token)
    assert info["community_name"] == "Synthetic Contracted ALF"

    recorded = service.record_public_pulse(
        token,
        PulseSubmission(
            private_rooms="2",
            semi_private_male_rooms="1",
            semi_private_female_rooms="5+",
            rate_changed=True,
            rate_change_note="Private rooms now $5,900/mo",
        ),
    )
    assert recorded["pulse"]["private_rooms"] == "2"
    assert recorded["pulse"]["semi_private_male_rooms"] == "1"
    assert recorded["pulse"]["semi_private_female_rooms"] == "5+"
    assert recorded["pulse"]["rate_changed"] is True
    assert recorded["pulse"]["rate_change_note"] == "Private rooms now $5,900/mo"

    state = client.get("/api/vhin/state").json()
    updated = next(c for c in state["communities"] if c["id"] == contracted_home["id"])
    assert updated["availability"]["status"] == "verified"
    assert updated["availability"]["vacancies"] == 8  # 2 + 1 + 5
    assert updated["availability"]["room_vacancies"] == {"private": "2", "semi_private_male": "1", "semi_private_female": "5+"}
    assert updated["pulse"]["status"] == "current"


def test_post_placement_day_7_30_60_checkin_cadence(owner_env):
    client, _, _ = owner_env
    referral = qualified(client)
    home = post(client, "/communities", {"name": "Synthetic Haven", "city": "Brandon", "category": "Assisted Living Facility"}).json()
    move_in = (BASE - timedelta(days=10)).date()
    placed = post(
        client,
        "/placements",
        {
            "referral_id": referral["id"],
            "community_id": home["id"],
            "move_in_date": move_in.isoformat(),
            "agreement_ref": "agr-movein-1",
            "agreement_signed_on": (move_in - timedelta(days=2)).isoformat(),
            "fee_cents": 600000,
            "terms": "50_50_day30_day60",
            "refund_terms": "Prorated 30 days",
        },
    )
    assert placed.status_code == 201, placed.text
    p = placed.json()
    assert p["checkin_cadence_status"] == "active"
    assert len(p["post_placement_checkins"]) == 6
    assert {(c["day"], c["audience"]) for c in p["post_placement_checkins"]} == {
        (7, "family"),
        (7, "facility"),
        (30, "family"),
        (30, "facility"),
        (60, "family"),
        (60, "facility"),
    }
    assert all(c["sent"] is False for c in p["post_placement_checkins"])

    # Since move-in was 10 days ago, Day 7 family + facility check-ins are due today
    state = client.get("/api/vhin/state").json()
    due = state["briefing"]["due_post_placement_checkins"]
    assert {(d["day"], d["audience"]) for d in due} == {(7, "family"), (7, "facility")}

    # Resolve all 6 check-ins -> cadence flips to completed
    for day in (7, 30, 60):
        for audience in ("family", "facility"):
            r = post(client, f"/placements/{p['id']}/checkins/{day}/{audience}", {"status": "completed", "note": "Checked in"})
            assert r.status_code == 200, r.text
    final_state = client.get("/api/vhin/state").json()
    assert final_state["placements"][0]["checkin_cadence_status"] == "completed"
    assert final_state["briefing"]["due_post_placement_checkins"] == []


def test_extension_model_tools_and_fail_closed_auth(tmp_path, clock):
    service = Service(
        {
            "data_dir": str(tmp_path),
            "organization_id": "vhin-org",
            "allowed_user_ids": ["owner", "advisor"],
            "placement_confirmer_user_ids": ["owner"],
        }
    )
    service.ready = True
    plugin = build_plugin(service)
    tools_by_name = {t.name: t for t in plugin.tools}
    assert set(tools_by_name) == {
        "search_facilities",
        "rate_facility",
        "set_contract_status",
        "add_or_update_facility",
        "weekly_contract_targets",
        "save_referral",
    }

    owner_ctx = ToolContext(ExtensionPrincipal("storage-bucket"), MappingProxyType({}), "t-1", actor_user_id="owner", organization_id="vhin-org")
    wrong_org_ctx = ToolContext(ExtensionPrincipal("storage-bucket"), MappingProxyType({}), "t-1", actor_user_id="owner", organization_id="other-org")
    advisor_ctx = ToolContext(ExtensionPrincipal("storage-bucket"), MappingProxyType({}), "t-1", actor_user_id="advisor", organization_id="vhin-org")

    async def run():
        # Cross-org fails closed
        with pytest.raises(PermissionError):
            await tools_by_name["search_facilities"].handler(MappingProxyType({}), wrong_org_ctx)

        # Owner adds custom pre-listing facility (The Gallery) with 3-star rating
        added = await tools_by_name["add_or_update_facility"].handler(
            MappingProxyType(
                {
                    "name": "Synthetic Gallery",
                    "city": "Brandon",
                    "miles_from_office": 1.0,
                    "licensed_beds": 300,
                    "category": "Assisted Living Facility",
                    "care_levels": ["Assisted Living", "Memory Care", "Independent Living"],
                    "stars": 3,
                    "tour_note": "Brand new, bright dining area",
                }
            ),
            owner_ctx,
        )
        assert added["saved"] is True
        assert added["community"]["owner_rating"]["stars"] == 3
        assert "UNCONTRACTED" in added["contract_warning"]

        # Non-owner advisor cannot rate or set contract
        with pytest.raises(PermissionError):
            await tools_by_name["rate_facility"].handler(MappingProxyType({"facility": "Synthetic Gallery", "stars": 2}), advisor_ctx)
        with pytest.raises(PermissionError):
            await tools_by_name["set_contract_status"].handler(MappingProxyType({"facility": "Synthetic Gallery", "contracted": True}), advisor_ctx)

        # Weekly 5-facility contract targets returns Synthetic Gallery while uncontracted
        sprint = await tools_by_name["weekly_contract_targets"].handler(MappingProxyType({"max_miles": 10, "limit": 5}), advisor_ctx)
        assert [t["name"] for t in sprint["targets"]] == ["Synthetic Gallery"]

        # Owner marks contracted and re-rates via voice/chat tools
        contracted = await tools_by_name["set_contract_status"].handler(
            MappingProxyType({"facility": "Synthetic Gallery", "contracted": True, "agreement_ref": "agr-gallery"}),
            owner_ctx,
        )
        assert contracted["contracted"] is True and contracted["contract_warning"] is None
        rated = await tools_by_name["rate_facility"].handler(
            MappingProxyType({"facility": "Synthetic Gallery", "stars": 3, "tour_note": "Updated after second visit"}),
            owner_ctx,
        )
        assert rated["owner_rating"]["note"] == "Updated after second visit"

        # Search returns contracted 3-star home cleanly
        found = await tools_by_name["search_facilities"].handler(MappingProxyType({"city": "Brandon", "max_miles": 10}), advisor_ctx)
        assert found["recommendations"][0]["name"] == "Synthetic Gallery"
        assert found["recommendations"][0]["contracted"] is True

    asyncio.run(run())
