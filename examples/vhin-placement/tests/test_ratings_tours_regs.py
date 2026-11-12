"""Synthetic acceptance for owner star ratings, top-3 picks, tour plans and regulation search."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_api import BASE, build_test_app, post, qualified

from vhin_placement import regulations


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr("vhin_placement.api.now", lambda: BASE)
    monkeypatch.setattr("vhin_placement.store.now", lambda: BASE)


@pytest.fixture
def owner(tmp_path, clock):
    app, _ = build_test_app(tmp_path)
    with TestClient(app) as result:
        yield result


@pytest.fixture
def coordinator(tmp_path, clock):
    app, _ = build_test_app(tmp_path, user_id="coordinator")
    with TestClient(app) as result:
        yield result


def add_community(client, name, city="Brandon", services=("assisted living",), miles=None, **extra):
    body = {
        "name": name,
        "city": city,
        "services": list(services),
        "source_url": "https://example.test/" + name.replace(" ", "-"),
        "observed_at": (BASE - timedelta(days=1)).isoformat(),
        **extra,
    }
    if miles is not None:
        body["miles_from_office"] = miles
    response = post(client, "/communities", body)
    assert response.status_code == 201, response.text
    return response.json()


def contract(client, community_id, status="contracted", ref: str | None = "synthetic-agreement:1"):
    return post(client, f"/communities/{community_id}/contract", {"status": status, "agreement_ref": ref, "human_confirmed": True})


def verify(client, community_id, vacancies):
    return post(
        client,
        f"/communities/{community_id}/availability",
        {
            "vacancies": vacancies,
            "verified_at": (BASE - timedelta(hours=1)).isoformat(),
            "expires_at": (BASE + timedelta(days=3)).isoformat(),
            "source_ref": "synthetic call with community",
            "human_confirmed": True,
        },
    )


# ---------------------------------------------------------------- star ratings


def test_stars_need_contract_and_owner(owner, coordinator):
    home = add_community(owner, "Synthetic Oaks")
    assert home["contract_status"] == "not_contracted"
    assert home["owner_rating"] == {"stars": None, "label": "Not yet rated by the owner"}
    early = post(owner, f"/communities/{home['id']}/rating", {"stars": 3})
    assert early.status_code == 409 and "contracted" in early.json()["detail"]
    assert post(coordinator, f"/communities/{home['id']}/contract", {"status": "contracted", "agreement_ref": "x", "human_confirmed": True}).status_code == 403
    assert post(owner, f"/communities/{home['id']}/contract", {"status": "contracted", "human_confirmed": True}).status_code == 422
    assert contract(owner, home["id"]).status_code == 200
    assert post(coordinator, f"/communities/{home['id']}/rating", {"stars": 2}).status_code == 403
    for bad in (0, 4, 5, "3", 2.5):
        assert post(owner, f"/communities/{home['id']}/rating", {"stars": bad}).status_code == 422, bad
    rated = post(owner, f"/communities/{home['id']}/rating", {"stars": 2, "note": "Clean, responsive staff"})
    assert rated.status_code == 200, rated.text
    assert rated.json()["owner_rating"]["label"] == "2 of 3 stars"
    assert rated.json()["owner_rating"]["rated_by"] == "owner"
    state = coordinator.get("/api/vhin/state").json()
    assert state["communities"][0]["owner_rating"]["stars"] == 2  # the coordinator sees the same record
    assert any(event["action"].startswith("community.rating") for event in state["audit"])


def test_stars_clear_when_contract_ends(owner):
    home = add_community(owner, "Synthetic Pines")
    contract(owner, home["id"])
    post(owner, f"/communities/{home['id']}/rating", {"stars": 3})
    ended = contract(owner, home["id"], status="not_contracted", ref=None)
    assert ended.status_code == 200
    assert ended.json()["owner_rating"]["stars"] is None


# ---------------------------------------------------------------- recommendations


def test_top_three_fit_first_then_openings_distance_and_stars(owner):
    add_community(owner, "Near Unrated", miles=1.0)
    far_three = add_community(owner, "Far Three Star", miles=9.0)
    mid_one = add_community(owner, "Mid One Star", miles=4.0)
    full = add_community(owner, "Verified Full", miles=0.5)
    add_community(owner, "Wrong City", city="Tampa", miles=0.2)
    add_community(owner, "No Memory Care", services=("independent living",), miles=0.3)
    unknown_distance = add_community(owner, "Unknown Distance")
    for home, stars in ((far_three, 3), (mid_one, 1)):
        contract(owner, home["id"])
        post(owner, f"/communities/{home['id']}/rating", {"stars": stars})
    assert verify(owner, far_three["id"], 2).status_code == 200
    assert verify(owner, full["id"], 0).status_code == 200

    result = owner.get("/api/vhin/recommendations", params={"city": "Brandon", "services": "assisted"}).json()
    names = [r["name"] for r in result["recommendations"]]
    # confirmed openings first, then nearest; a verified-full home falls to the back
    assert names == ["Far Three Star", "Near Unrated", "Mid One Star"]
    assert len(names) == 3 and result["fit_count"] == 5
    by_name = {r["name"]: r for r in result["recommendations"]}
    assert by_name["Far Three Star"]["owner_rating"]["label"] == "3 of 3 stars"
    assert by_name["Mid One Star"]["owner_rating"]["label"] == "1 of 3 stars"
    assert by_name["Near Unrated"]["owner_rating"]["label"] == "Not yet rated by the owner"
    assert "current vacancy" in by_name["Near Unrated"]["checks_needed"]
    assert "current vacancy" not in by_name["Far Three Star"]["checks_needed"]

    capped = owner.get("/api/vhin/recommendations", params={"max_miles": 5}).json()
    assert unknown_distance["id"] not in [r["id"] for r in capped["recommendations"]]
    assert capped["excluded_unknown_distance"] == 1
    assert owner.get("/api/vhin/recommendations", params={"limit": 4}).status_code == 422


def test_stars_break_ties_but_never_outrank_fit(owner):
    a = add_community(owner, "Same Miles A", miles=3.0)
    b = add_community(owner, "Same Miles B", miles=3.0)
    add_community(owner, "Five Star Elsewhere", city="Tampa", miles=3.0)
    contract(owner, b["id"])
    post(owner, f"/communities/{b['id']}/rating", {"stars": 3})
    names = [r["name"] for r in owner.get("/api/vhin/recommendations", params={"city": "Brandon"}).json()["recommendations"]]
    assert names == ["Same Miles B", "Same Miles A"]
    assert a["id"]


# ---------------------------------------------------------------- tour plans


def tour_homes(client):
    homes = []
    for index, name in enumerate(("Synthetic Oaks", "Synthetic Pines", "Synthetic Palms")):
        homes.append(add_community(client, name, miles=float(index + 1), contact_name=f"Director {index}", contact_email=f"tours{index}@example.test"))
    return homes


def plan_body(referral_id, homes, *offsets):
    return {
        "referral_id": referral_id,
        "community_ids": [h["id"] for h in homes],
        "options": [(BASE + timedelta(days=d)).isoformat() for d in offsets],
        "tour_minutes": 45,
        "travel_minutes": 30,
    }


def test_tour_plan_builds_itinerary_and_unsent_drafts(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    response = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 3))
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["status"] == "awaiting_replies" and plan["sent"] is False and plan["calendar_connected"] is False
    stops = plan["options"][0]["stops"]
    assert [s["community_name"] for s in stops] == ["Synthetic Oaks", "Synthetic Pines", "Synthetic Palms"]
    assert stops[1]["start_at"] == (BASE + timedelta(days=2, minutes=75)).isoformat()  # 45 min tour + 30 min drive
    family = plan["drafts"]["family"]
    assert "Option 1" in family["family_email"] and "Option 2" in family["family_email"]
    assert "Help with daily tasks" not in family["family_email"]  # no care details in drafts
    assert "$" not in family["family_email"] and "$" not in family["family_text"]
    assert family["family_email"].startswith("Hi Synthetic,")
    community_draft = plan["drafts"]["communities"][homes[0]["id"]]
    assert community_draft["to_email"] == "tours0@example.test" and "Director 0" in community_draft["email"]
    assert "Synthetic Family" not in community_draft["email"]  # communities never get the family's name
    # Sender name and business line come from deployment config; without it the drafts carry placeholders.
    assert family["family_email"].rstrip().endswith("[your name]") and "[business connection line to approve]" in family["family_email"]
    assert community_draft["email"].rstrip().endswith("[your name]") and "it's [your name]." in community_draft["text"]
    state = owner.get("/api/vhin/state").json()
    saved = [d for d in state["drafts"] if d.get("tour_plan_id") == plan["id"]]
    assert len(saved) == 1 and saved[0]["status"] == "draft" and saved[0]["sent"] is False
    assert state["briefing"]["tour_plans_awaiting_replies"] == 1
    assert state["tours"] == []  # a plan is not a tour or a booking


def test_tour_plan_three_party_confirmation(owner, coordinator):
    referral = qualified(owner)
    homes = tour_homes(owner)
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 3)).json()
    path = f"/tour-plans/{plan['id']}/responses"
    assert post(coordinator, path, {"party": "family", "response": "accepts", "option": 2, "source_ref": "email 1"}).json()["status"] == "awaiting_replies"
    assert post(coordinator, path, {"party": "community", "response": "accepts", "option": 2, "source_ref": "x"}).status_code == 422
    assert post(coordinator, path, {"party": "family", "response": "accepts", "source_ref": "x"}).status_code == 422
    assert post(coordinator, path, {"party": "community", "community_id": "nope", "response": "accepts", "option": 2, "source_ref": "x"}).status_code == 422
    assert post(coordinator, path, {"party": "family", "response": "accepts", "option": 3, "source_ref": "x"}).status_code == 422
    for home in homes:
        result = post(coordinator, path, {"party": "community", "community_id": home["id"], "response": "accepts", "option": 2, "source_ref": "call"})
        assert result.status_code == 200, result.text
    done = post(owner, path, {"party": "owner", "response": "accepts", "option": 2, "source_ref": "owner in person"})
    assert done.json()["status"] == "ready_to_book" and done.json()["chosen_option"] == 2
    tours = owner.get("/api/vhin/state").json()["tours"]
    assert len(tours) == 3 and all(t["status"] == "proposed" and t["parties_confirmed"] and not t["calendar_connected"] for t in tours)
    assert post(owner, path, {"party": "owner", "response": "declines", "source_ref": "late"}).status_code == 409
    # the agreed time now blocks a second plan at the same time
    second = post(owner, "/tour-plans", plan_body(referral["id"], homes[:1], 3))
    assert second.status_code == 409


def test_tour_plan_decline_or_split_answers_need_new_times(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)[:1]
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 3)).json()
    path = f"/tour-plans/{plan['id']}/responses"
    post(owner, path, {"party": "family", "response": "accepts", "option": 1, "source_ref": "a"})
    post(owner, path, {"party": "community", "community_id": homes[0]["id"], "response": "accepts", "option": 2, "source_ref": "b"})
    assert post(owner, path, {"party": "owner", "response": "accepts", "option": 1, "source_ref": "c"}).json()["status"] == "needs_new_times"
    other = post(owner, "/tour-plans", {**plan_body(referral["id"], homes, 4), "supersedes_plan_id": plan["id"]}).json()
    # The family's reply paused contact, but new times for the same conversation still get a family draft.
    assert other["status"] == "awaiting_replies" and other["parties"]["family"]["status"] == "pending"
    assert "Option 1" in other["drafts"]["family"]["family_email"]
    declined = post(owner, f"/tour-plans/{other['id']}/responses", {"party": "family", "response": "declines", "source_ref": "text"})
    assert declined.json()["status"] == "needs_new_times"


def test_family_tour_reply_pauses_followups_and_keeps_plan_open(owner):
    referral = qualified(owner)
    home = tour_homes(owner)[:1]
    assert post(owner, f"/referrals/{referral['id']}/drafts", {"reason": "no_booking", "body": "Synthetic stale follow-up"}).status_code == 201
    plan = post(owner, "/tour-plans", plan_body(referral["id"], home, 2)).json()
    path = f"/tour-plans/{plan['id']}/responses"
    assert post(owner, path, {"party": "family", "response": "accepts", "option": 1, "source_ref": "family text"}).json()["status"] == "awaiting_replies"
    state = owner.get("/api/vhin/state").json()
    assert next(r for r in state["referrals"] if r["id"] == referral["id"])["contact_status"] == "paused"
    followup = next(d for d in state["drafts"] if d["referral_id"] == referral["id"] and d["reason"] == "no_booking")
    assert followup["status"] == "paused"
    assert post(owner, f"/referrals/{referral['id']}/drafts", {"reason": "planning", "body": "No longer timely"}).status_code == 409
    # The pause must not close the plan; the remaining parties can still confirm.
    confirmed = post(owner, path, {"party": "community", "community_id": home[0]["id"], "response": "accepts", "option": 1, "source_ref": "community call"})
    assert confirmed.status_code == 200 and confirmed.json()["parties"]["family"]["status"] == "accepts"


def test_plan_after_family_reply_stays_open_and_completes_three_party_flow(owner, coordinator):
    referral = qualified(owner)
    homes = tour_homes(owner)
    assert post(owner, f"/referrals/{referral['id']}/contact-events", {"event": "reply"}).status_code == 200
    state = owner.get("/api/vhin/state").json()
    assert next(r for r in state["referrals"] if r["id"] == referral["id"])["contact_status"] == "paused"
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 3)).json()
    assert plan["status"] == "awaiting_replies" and plan["drafts"]["family"] is None
    assert plan["parties"]["family"]["status"] == "pending"
    assert all(p["status"] == "pending" for p in plan["parties"]["communities"].values())
    path = f"/tour-plans/{plan['id']}/responses"
    assert post(coordinator, path, {"party": "family", "response": "accepts", "option": 1, "source_ref": "family text"}).status_code == 200
    for home in homes:
        result = post(coordinator, path, {"party": "community", "community_id": home["id"], "response": "accepts", "option": 1, "source_ref": "call"})
        assert result.status_code == 200, result.text
    done = post(owner, path, {"party": "owner", "response": "accepts", "option": 1, "source_ref": "owner in person"})
    assert done.status_code == 200 and done.json()["status"] == "ready_to_book"


def test_tour_plan_respects_stop_and_drops_conflicting_options(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    assert (
        post(
            owner,
            "/tours",
            {
                "referral_id": referral["id"],
                "community_id": homes[0]["id"],
                "start_at": (BASE + timedelta(days=2)).isoformat(),
                "end_at": (BASE + timedelta(days=2, hours=1)).isoformat(),
            },
        ).status_code
        == 201
    )
    post(owner, f"/referrals/{referral['id']}/contact-events", {"event": "stop"})
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 3)).json()
    assert plan["dropped_conflicting_options"] == 1 and len(plan["options"]) == 1
    assert plan["drafts"]["family"] is None and plan["parties"]["family"]["status"] == "blocked"
    assert plan["status"] == "family_contact_blocked"
    assert "no family draft" in plan["drafts"]["owner_summary"]
    blocked = post(owner, f"/tour-plans/{plan['id']}/responses", {"party": "family", "response": "accepts", "option": 1, "source_ref": "x"})
    assert blocked.status_code == 409
    assert post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).status_code == 409


def test_tour_plan_inputs_and_calendar_file(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    assert post(owner, "/tour-plans", plan_body(referral["id"], homes + homes[:1], 2)).status_code == 422
    assert post(owner, "/tour-plans", plan_body(referral["id"], homes, 2, 2)).status_code == 422
    assert post(owner, "/tour-plans", plan_body(referral["id"], homes, -1)).status_code == 422
    new = post(owner, "/referrals", {"name": "Unqualified", "source_ref": "synthetic:2", "email": "u@example.test"}).json()
    assert post(owner, "/tour-plans", plan_body(new["id"], homes, 2)).status_code == 409
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).json()
    ics = owner.get(f"/api/vhin/tour-plans/{plan['id']}/calendar.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert ics.text.count("BEGIN:VEVENT") == 3 and "STATUS:TENTATIVE" in ics.text
    assert "Synthetic Family" not in ics.text and "daily tasks" not in ics.text
    assert owner.get(f"/api/vhin/tour-plans/{plan['id']}/calendar.ics", params={"option": 2}).status_code == 404


def test_tour_plan_retry_is_idempotent(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    key = str(uuid4())
    first = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2), key=key).json()
    again = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2), key=key).json()
    assert first["id"] == again["id"]
    assert len(owner.get("/api/vhin/state").json()["tour_plans"]) == 1


# ---------------------------------------------------------------- regulations
# The built Florida corpus is bulk data kept out of Git. These tests run against it
# when it is present (scripts/build_regulations.py FL, or VHIN_REGULATIONS_DIR set to
# a deployment's data mount) and skip otherwise; the synthetic-corpus test below
# always runs and covers loading, gating and the routes.

requires_fl = pytest.mark.skipif(
    regulations.load("FL") is None,
    reason="Florida corpus not built: run scripts/build_regulations.py FL or set VHIN_REGULATIONS_DIR",
)

SYNTHETIC_CORPUS = {
    "state": "ZZ",
    "name": "Synthetic rules",
    "retrieved_at": "2026-11-06T00:00:00Z",
    "sources": [{"id": "zz-rules", "url": "https://rules.example.test/"}],
    "documents": [{"source_id": "zz-rules", "url": "https://rules.example.test/1", "sha256": "0" * 64, "bytes": 1}],
    "lay_terms": {"lift": ["transfer"]},
    "units": [
        {
            "id": "ZZ-00001",
            "source_id": "zz-rules",
            "section": "1.001",
            "section_title": "Admission",
            "path": [],
            "citation": "Rule 1.001, Z.A.C.",
            "text": "Admission criteria for residents.",
            "url": "https://rules.example.test/1",
        },
        {
            "id": "ZZ-00002",
            "source_id": "zz-rules",
            "section": "1.001",
            "section_title": "Admission",
            "path": ["(1)"],
            "citation": "Rule 1.001(1), Z.A.C.",
            "text": "A resident who needs total assistance with transfer is not appropriate.",
            "url": "https://rules.example.test/1",
        },
        {
            "id": "ZZ-00003",
            "source_id": "zz-rules",
            "section": "1.002",
            "section_title": "Notice",
            "path": ["(1)"],
            "citation": "Rule 1.002(1), Z.A.C.",
            "text": "Discharge notice is given in writing.",
            "url": "https://rules.example.test/1",
        },
    ],
}


@pytest.fixture
def synthetic_rules(tmp_path, monkeypatch):
    root = tmp_path / "regs"
    (root / "ZZ").mkdir(parents=True)
    (root / "ZZ" / "corpus.json").write_text(json.dumps(SYNTHETIC_CORPUS))
    monkeypatch.setenv("VHIN_REGULATIONS_DIR", str(root))
    return root


def test_corpus_is_read_from_the_data_mount(owner, synthetic_rules, tmp_path):
    assert regulations.available_states() == ["ZZ"] and regulations.load("FL") is None
    assert regulations.load("../ZZ") is None and regulations.load("zz").state == "ZZ"
    assert owner.get("/api/vhin/regulations").json()["states"][0]["state"] == "ZZ"
    found = owner.get("/api/vhin/regulations/ZZ/search", params={"q": "can a lift be used"}).json()
    assert found["results"][0]["citation"] == "Rule 1.001(1), Z.A.C."
    assert found["results"][0]["context"][0]["citation"] == "Rule 1.001, Z.A.C."
    unit = owner.get("/api/vhin/regulations/zz/unit", params={"citation": "Rule 1.001, Z.A.C."}).json()
    assert [u["citation"] for u in unit["units"]] == ["Rule 1.001, Z.A.C.", "Rule 1.001(1), Z.A.C."]
    assert owner.get("/api/vhin/regulations/FL/search", params={"q": "lift"}).status_code == 404
    assert owner.get("/api/vhin/regulations/ZZ/unit", params={"citation": "Rule 9.999, Z.A.C."}).status_code == 404
    outsider, _ = build_test_app(tmp_path, user_id="mallory")
    with TestClient(outsider) as client:
        assert client.get("/api/vhin/regulations/ZZ/search", params={"q": "lift"}).status_code == 403


def test_no_corpus_means_not_loaded(owner, tmp_path, monkeypatch):
    monkeypatch.setenv("VHIN_REGULATIONS_DIR", str(tmp_path / "empty"))
    assert regulations.available_states() == [] and regulations.load("FL") is None
    assert owner.get("/api/vhin/regulations").json()["states"] == []


@requires_fl
def test_florida_corpus_is_primary_source_only():
    corpus = regulations.load("FL")
    assert corpus is not None and regulations.available_states() == ["FL"]
    hosts = {doc["url"].split("/")[2] for doc in corpus.documents}
    assert hosts <= {"www.flrules.org", "www.leg.state.fl.us"}
    assert all(len(doc["sha256"]) == 64 for doc in corpus.documents)
    sections = {u["section"] for u in corpus.units}
    assert "59A-36.006" in sections and "429.26" in sections and "429.28" in sections
    assert all(u["citation"].endswith((", F.A.C.", ", F.S.")) for u in corpus.units)
    assert len({u["citation"] for u in corpus.units}) == len(corpus.units)  # every citation is unique
    assert regulations.load("OH") is None and regulations.load("../FL") is None


@requires_fl
@pytest.mark.parametrize(
    ("question", "citation"),
    [
        ("Can a Hoyer lift be used in a standard ALF?", "Rule 59A-36.006(1)(a)4., F.A.C."),
        ("Can a Hoyer lift be used in a standard ALF?", "Section 429.26(1)(b), F.S."),
        ("Can a Hoyer lift be used in a standard ALF?", "Section 429.02(6), F.S."),
        ("Can a Hoyer lift be used in a standard ALF?", "Rule 59A-36.002(7), F.A.C."),
        ("Can an assisted living facility admit a resident who is bedridden?", "Section 429.26(1)(d)1., F.S."),
        ("Can a resident with a stage 3 pressure sore be admitted?", "Rule 59A-36.006(1)(a)10., F.A.C."),
        ("How much notice must a facility give before discharging a resident?", "Section 429.28(1)(k), F.S."),
        ("Can a resident with a feeding tube live in a standard ALF?", "Rule 59A-36.006(1)(a)11.b., F.A.C."),
    ],
)
def test_search_finds_the_governing_unit(question, citation):
    hits = [h["citation"] for h in regulations.load("FL").search(question, 10)]
    assert citation in hits


@requires_fl
def test_regulation_routes_are_gated_and_cite(owner, tmp_path):
    states = owner.get("/api/vhin/regulations").json()["states"]
    assert states[0]["state"] == "FL" and states[0]["units"] > 1000
    found = owner.get("/api/vhin/regulations/FL/search", params={"q": "stage 3 pressure sore"}).json()
    top = found["results"][0]
    assert top["citation"].startswith("Rule 59A-36.006(1)(a)10") and top["official_url"].startswith("https://www.flrules.org/")
    assert top["context"][0]["citation"] == "Rule 59A-36.006(1), F.A.C."
    unit = owner.get("/api/vhin/regulations/fl/unit", params={"citation": "Section 429.26(1)(d)1., F.S."}).json()
    assert unit["text"].startswith("Except for a resident who is receiving hospice services")
    assert [u["citation"] for u in unit["units"]][1:] == ["Section 429.26(1)(d)1.a., F.S.", "Section 429.26(1)(d)1.b., F.S.", "Section 429.26(1)(d)1.c., F.S."]
    assert owner.get("/api/vhin/regulations/OH/search", params={"q": "lift"}).status_code == 404
    assert owner.get("/api/vhin/regulations/FL/unit", params={"citation": "Rule 59A-36.999, F.A.C."}).status_code == 404
    outsider, _ = build_test_app(tmp_path, user_id="mallory")
    with TestClient(outsider) as client:
        assert client.get("/api/vhin/regulations/FL/search", params={"q": "lift"}).status_code == 403


def test_stop_after_plan_pulls_family_drafts_and_closes_plan(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).json()
    assert plan["drafts"]["family"] is not None
    post(owner, f"/referrals/{referral['id']}/contact-events", {"event": "stop"})
    state = owner.get("/api/vhin/state").json()
    closed = state["tour_plans"][0]
    assert closed["status"] == "family_contact_blocked" and closed["drafts"]["family"] is None
    assert all(d["status"] == "suppressed" for d in state["drafts"] if d.get("tour_plan_id") == plan["id"])
    late = post(owner, f"/tour-plans/{plan['id']}/responses", {"party": "family", "response": "accepts", "option": 1, "source_ref": "x"})
    assert late.status_code == 409


def test_only_owner_records_owners_reply(owner, coordinator):
    referral = qualified(owner)
    plan = post(owner, "/tour-plans", plan_body(referral["id"], tour_homes(owner)[:1], 2)).json()
    path = f"/tour-plans/{plan['id']}/responses"
    assert post(coordinator, path, {"party": "owner", "response": "accepts", "option": 1, "source_ref": "x"}).status_code == 403
    assert post(owner, path, {"party": "owner", "response": "accepts", "option": 1, "source_ref": "x"}).status_code == 200


def test_one_open_plan_per_family_and_supersede(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    first = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).json()
    assert post(owner, "/tour-plans", plan_body(referral["id"], homes, 4)).status_code == 409
    second = post(owner, "/tour-plans", {**plan_body(referral["id"], homes, 4), "supersedes_plan_id": first["id"]})
    assert second.status_code == 201, second.text
    state = owner.get("/api/vhin/state").json()
    statuses = {p["id"]: p["status"] for p in state["tour_plans"]}
    assert statuses[first["id"]] == "superseded" and statuses[second.json()["id"]] == "awaiting_replies"
    assert [d["status"] for d in state["drafts"] if d.get("tour_plan_id") == first["id"]] == ["superseded"]


def test_failed_supersede_rolls_back_and_keeps_the_open_plan(owner):
    referral = qualified(owner)
    homes = tour_homes(owner)
    first = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).json()
    booked = {
        "referral_id": referral["id"],
        "community_id": homes[0]["id"],
        "start_at": (BASE + timedelta(days=5)).isoformat(),
        "end_at": (BASE + timedelta(days=5, hours=1)).isoformat(),
    }
    assert post(owner, "/tours", booked).status_code == 201
    before = owner.get("/api/vhin/state").json()
    # The replacement marks the open plan and its draft superseded, then finds every new time taken: the whole
    # transaction must roll back, or the family would be left with no open plan and a dead draft.
    replace = {**plan_body(referral["id"], homes, 5), "supersedes_plan_id": first["id"]}
    failed = post(owner, "/tour-plans", replace, key="replace-plan")
    assert failed.status_code == 409 and "overlaps" in failed.json()["detail"]
    after = owner.get("/api/vhin/state").json()
    for kind in ("tour_plans", "drafts", "tours", "referrals"):
        assert after[kind] == before[kind]
    assert [p["status"] for p in after["tour_plans"]] == ["awaiting_replies"]
    assert [d["status"] for d in after["drafts"] if d.get("tour_plan_id") == first["id"]] == ["draft"]
    # No retry receipt was stored for the failed attempt, so the same key with a free time goes through.
    second = post(owner, "/tour-plans", {**replace, "options": [(BASE + timedelta(days=6)).isoformat()]}, key="replace-plan")
    assert second.status_code == 201, second.text
    state = owner.get("/api/vhin/state").json()
    statuses = {p["id"]: p["status"] for p in state["tour_plans"]}
    assert statuses == {first["id"]: "superseded", second.json()["id"]: "awaiting_replies"}
    assert [d["status"] for d in state["drafts"] if d.get("tour_plan_id") == first["id"]] == ["superseded"]
    assert [d["status"] for d in state["drafts"] if d.get("tour_plan_id") == second.json()["id"]] == ["draft"]


def test_agreement_after_the_time_passed_is_refused(owner, monkeypatch):
    referral = qualified(owner)
    homes = tour_homes(owner)[:1]
    plan = post(owner, "/tour-plans", plan_body(referral["id"], homes, 2)).json()
    path = f"/tour-plans/{plan['id']}/responses"
    post(owner, path, {"party": "family", "response": "accepts", "option": 1, "source_ref": "a"})
    post(owner, path, {"party": "community", "community_id": homes[0]["id"], "response": "accepts", "option": 1, "source_ref": "b"})
    monkeypatch.setattr("vhin_placement.api.now", lambda: BASE + timedelta(days=3))
    late = post(owner, path, {"party": "owner", "response": "accepts", "option": 1, "source_ref": "c"})
    assert late.status_code == 409 and "passed" in late.json()["detail"]
    assert owner.get("/api/vhin/state").json()["tours"] == []


def test_calendar_file_strips_control_characters_and_folds():
    from vhin_placement import coordination

    stops = [{"community_name": "Evil\r\nBEGIN:VALARM, Home; " + "x" * 120, "start_at": BASE.isoformat(), "end_at": (BASE + timedelta(hours=1)).isoformat()}]
    text = coordination.tentative_calendar("plan-id-1234", 1, stops, BASE)
    assert "\r\nBEGIN:VALARM" not in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_drafts_sign_with_the_configured_advisor(tmp_path, clock):
    from vhin_placement import coordination

    options = [
        {
            "stops": [
                {"community_id": "c1", "community_name": "Synthetic Oaks", "start_at": BASE.isoformat(), "end_at": (BASE + timedelta(minutes=45)).isoformat()}
            ]
        }
    ]
    family = coordination.family_drafts({"name": "Synthetic Family"}, options, "Sam", "Sam at Example Placement")
    assert family["family_email"].rstrip().endswith("Sam") and "Sam at Example Placement" in family["family_email"]
    assert family["family_text"].startswith("Hi Synthetic, it's Sam.")
    community = coordination.community_drafts({"id": "c1", "name": "Synthetic Oaks"}, options, "Sam")
    assert community["email"].rstrip().endswith("Sam") and "it's Sam." in community["text"]
