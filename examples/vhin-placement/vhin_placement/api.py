"""Authenticated operations only: no sends, calendar writes, models, or billing.

Tour plans prepare unsent drafts and a tentative calendar file; regulation search is
read-only over bundled primary-source text.
"""

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from deerflow_extension_api import resolve_principal
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import ValidationError

from vhin_placement import coordination, regulations
from vhin_placement.models import (
    Availability,
    Community,
    ContactEvent,
    ContractUpdate,
    Draft,
    LedgerEntry,
    Placement,
    Rating,
    Referral,
    ReferralPatch,
    Tour,
    TourPlan,
    TourResponse,
    Transition,
    before_now,
    contacts,
    missing_info,
)
from vhin_placement.store import Store, encode, get, now, put, records


class Service:
    def __init__(self, config):
        self.data_dir = Path(config.get("data_dir", ""))
        if not self.data_dir.is_absolute():
            raise ValueError("VHIN requires an absolute persistent data_dir")
        self.organization_id = config.get("organization_id")
        self.workspace_id = config.get("workspace_id", "vhin-placement")
        if not isinstance(self.organization_id, str) or not self.organization_id.strip():
            raise ValueError("VHIN requires an explicit organization_id")
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise ValueError("VHIN requires a nonempty workspace_id")
        allowed = config.get("allowed_user_ids", [])
        confirmers = config.get("placement_confirmer_user_ids", [])
        if not isinstance(allowed, list) or not allowed or not all(isinstance(x, str) and x.strip() for x in allowed):
            raise ValueError("VHIN requires explicit allowed_user_ids")
        if not isinstance(confirmers, list) or not all(isinstance(x, str) and x in allowed for x in confirmers):
            raise ValueError("Placement confirmers must be explicitly allowed user IDs")
        self.allowed_user_ids = frozenset(allowed)
        self.confirmers = frozenset(confirmers)
        # Names used in unsent tour drafts; kept in deployment config, never in source.
        self.advisor_name = str(config.get("advisor_name") or "[your name]")
        self.business_line = str(config.get("business_line") or "[business connection line to approve]")
        self.ready = False

    async def start(self, deps):
        self.ready = True

    async def stop(self):
        self.ready = False

    def account(self, request: Request, response: Response):
        principal = resolve_principal(request)
        organization = getattr(request.state, "organization_id", None)
        if principal is None or getattr(request.state, "auth_source", None) != "session" or not isinstance(organization, str) or not organization:
            raise HTTPException(401, "A signed-in MomoBot workspace session is required")
        if principal.is_internal or principal.user_id not in self.allowed_user_ids or organization != self.organization_id:
            raise HTTPException(403, "VHIN is not enabled for this account")
        if not self.ready:
            raise HTTPException(503, "VHIN is not running")
        response.headers["Cache-Control"] = "no-store"
        return Store(self.data_dir, organization, self.workspace_id, principal.user_id)


def retry_key(idempotency_key: str = Header(min_length=1, max_length=200)):
    if not idempotency_key.strip():
        raise HTTPException(422, "Idempotency-Key must not be blank")
    return idempotency_key


def create_record(payload):
    return {"id": str(uuid4()), **payload, "created_at": now().isoformat()}


def business_date():
    return now().astimezone(ZoneInfo("America/New_York")).date()


def is_suppressed(connection, referral):
    return referral.get("contact_status") == "stopped" or any(
        connection.execute("SELECT 1 FROM suppressed WHERE kind=? AND value=?", (kind, value)).fetchone() for kind, value in contacts(referral).items()
    )


def referral_view(connection, referral):
    return {
        **referral,
        "missing_info": missing_info(referral),
        "contact_status": "stopped" if is_suppressed(connection, referral) else referral["contact_status"],
        "handoff_status": "unconnected" if referral["attention"] != "routine" else "not_requested",
    }


def community_view(community):
    verification = community.get("availability")
    if verification is None:
        availability = {"status": "unknown", "vacancies": None}
    else:
        fresh = datetime.fromisoformat(verification["expires_at"]) > now()
        availability = {**verification, "status": "verified" if fresh else "expired", "vacancies": verification["vacancies"] if fresh else None}
    rating = community.get("rating")
    return {
        **community,
        "availability": availability,
        "contract_status": community.get("contract_status", "not_contracted"),
        "owner_rating": {**rating, "label": f"{rating['stars']} of 3 stars"} if rating else {"stars": None, "label": "Not yet rated by the owner"},
    }


def availability_rank(view):
    status, vacancies = view["availability"]["status"], view["availability"]["vacancies"]
    if status == "verified":
        return 0 if vacancies else 2
    return 1


def recommend(communities, city=None, services=(), category=None, max_miles=None, limit=3):
    """Fit decides who appears. Order: confirmed openings, distance, then the owner's stars as a tiebreak."""
    wanted = [s.casefold() for s in services]
    fits, excluded_unknown_distance = [], 0
    for community in communities:
        view = community_view(community)
        offered = [s.casefold() for s in view.get("services") or []]
        if city and view["city"].casefold() != city.casefold():
            continue
        if category and (view.get("category") or "").casefold() != category.casefold():
            continue
        if any(not any(w in o for o in offered) for w in wanted):
            continue
        if max_miles is not None:
            if view.get("miles_from_office") is None:
                excluded_unknown_distance += 1
                continue
            if view["miles_from_office"] > max_miles:
                continue
        fits.append(view)
    fits.sort(
        key=lambda v: (
            availability_rank(v),
            v.get("miles_from_office") if v.get("miles_from_office") is not None else float("inf"),
            -(v["owner_rating"]["stars"] or 0),
            v["name"].casefold(),
        )
    )
    picks = []
    for view in fits[:limit]:
        why = [f"in {view['city']}"] if city else []
        why += [f"offers {s}" for s in services]
        if category:
            why.append(view["category"])
        if view.get("miles_from_office") is not None:
            why.append(f"{view['miles_from_office']:g} miles from the office (straight line)")
        checks = [
            "current vacancy" if view["availability"]["status"] != "verified" else None,
            "price",
            "care capability for this resident",
            "payer acceptance",
            "tour availability",
        ]
        picks.append({**view, "why": why, "checks_needed": [c for c in checks if c]})
    return {"recommendations": picks, "fit_count": len(fits), "excluded_unknown_distance": excluded_unknown_distance}


ACTIVE_PLAN = ("awaiting_replies", "needs_new_times")


def block_family_in_plans(connection, referral_id):
    """A stop or decline removes family drafts from every plan and closes open ones."""
    for plan in records(connection, "tour_plan"):
        if plan["referral_id"] != referral_id:
            continue
        changed = plan["drafts"]["family"] is not None
        plan["drafts"]["family"] = None
        if plan["status"] in ACTIVE_PLAN:
            plan["parties"]["family"] = {"status": "blocked"}
            plan["status"] = "family_contact_blocked"
            changed = True
        if changed:
            put(connection, "tour_plan", plan)


def require_confirmer(service, store, what):
    if store.user_id not in service.confirmers:
        raise HTTPException(403, f"Only the configured placement owner account can {what}")


def overlaps(start, end, existing_start, existing_end):
    return start < datetime.fromisoformat(existing_end) and end > datetime.fromisoformat(existing_start)


def itinerary_span(stops):
    """The whole occupied block: from the first stop through the last, including internal travel."""
    return datetime.fromisoformat(stops[0]["start_at"]), datetime.fromisoformat(stops[-1]["end_at"])


def reserved_end(tour):
    return tour.get("reserved_end_at") or tour["end_at"]


def duplicate_ids(connection, candidate, exclude=None):
    values = contacts(candidate)
    return [
        row["id"] for row in records(connection, "referral") if row["id"] != exclude and any(contacts(row).get(kind) == value for kind, value in values.items())
    ]


def build_router(service):
    router = APIRouter(prefix="/api/vhin", tags=["vhin"])
    account = Depends(service.account)
    retry = Depends(retry_key)

    @router.get("/state")
    def state(store: Store = account):
        with store.transaction() as connection:
            referrals = [referral_view(connection, r) for r in records(connection, "referral")]
            communities = [community_view(c) for c in records(connection, "community")]
            tours, placements, ledger = (records(connection, kind) for kind in ("tour", "placement", "ledger"))
            due = sum(
                max(
                    0,
                    installment["amount_cents"]
                    - sum(e["amount_cents"] for e in ledger if e["kind"] == "collected" and e["placement_id"] == p["id"] and e["day"] == installment["day"]),
                )
                for p in placements
                for installment in p["installments"]
                if date.fromisoformat(installment["due_date"]) <= business_date()
            )
            return {
                "referrals": referrals,
                "communities": communities,
                "tours": tours,
                "placements": placements,
                "ledger": ledger,
                "drafts": records(connection, "draft"),
                "tour_plans": records(connection, "tour_plan"),
                "regulation_states": regulations.available_states(),
                "audit": [dict(row) for row in connection.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 100")],
                "connections": {
                    "intake": "manual",
                    "calendar": "unconnected",
                    "sender": "unconnected",
                    "billing": "unconnected",
                    "handoff": "unconnected",
                    "regulations": "loaded: " + ", ".join(regulations.available_states()) if regulations.available_states() else "none loaded",
                },
                "can_confirm_placement": store.user_id in service.confirmers,
                "briefing": {
                    "new_referrals": sum(r["status"] == "New" for r in referrals),
                    "incomplete_referrals": sum(bool(r["missing_info"]) for r in referrals),
                    "qualified_referrals": sum(r["status"] == "Qualified" for r in referrals),
                    "proposed_tours": len(tours),
                    "confirmed_tours": 0,
                    "tour_plans_awaiting_replies": sum(p["status"] == "awaiting_replies" for p in records(connection, "tour_plan")),
                    "tour_plans_ready_to_book": sum(p["status"] == "ready_to_book" for p in records(connection, "tour_plan")),
                    "placements": len(placements),
                    "availability_needs_verification": sum(c["availability"]["status"] != "verified" for c in communities),
                    "human_callback_needed": sum(r["attention"] != "routine" for r in referrals),
                    "callback_referral_ids": [r["id"] for r in referrals if r["attention"] != "routine"],
                    "contracted_cents": sum(p["fee_cents"] for p in placements),
                    "invoiced_cents": sum(e["amount_cents"] for e in ledger if e["kind"] == "invoiced"),
                    "collected_cents": sum(e["amount_cents"] for e in ledger if e["kind"] == "collected"),
                    "due_cents": due,
                    "costs_cents": None,
                    "handling_minutes": None,
                    "next_owner": store.user_id,
                },
            }

    @router.post("/referrals", status_code=201)
    def create_referral(payload: Referral, store: Store = account, key: str = retry):
        data = payload.model_dump(mode="json")

        def operation(connection):
            source_hash = hashlib.sha256(encode(data).encode()).hexdigest()
            source = connection.execute("SELECT body FROM records WHERE kind='source' AND id=?", (payload.source_ref,)).fetchone()
            if source:
                prior = get(connection, "source", payload.source_ref)
                if prior["digest"] != source_hash:
                    raise HTTPException(409, "This source submission already exists with different information; review its referral")
                return referral_view(connection, get(connection, "referral", prior["referral_id"]))
            duplicates = duplicate_ids(connection, data)
            if duplicates:
                raise HTTPException(409, {"message": "Contact matches an existing referral; review that record", "duplicate_ids": duplicates})
            result = create_record({**data, "status": "New", "contact_status": "active", "version": 1})
            put(connection, "source", {"id": payload.source_ref, "digest": source_hash, "referral_id": result["id"]})
            return referral_view(connection, put(connection, "referral", result))

        return store.mutate(key, "referral.create", data, operation)

    @router.get("/referrals/{referral_id}")
    def read_referral(referral_id: str, store: Store = account):
        with store.transaction() as connection:
            return referral_view(connection, get(connection, "referral", referral_id))

    @router.patch("/referrals/{referral_id}")
    def update_referral(referral_id: str, payload: ReferralPatch, store: Store = account, key: str = retry):
        data = payload.model_dump(mode="json", exclude_unset=True)

        def operation(connection):
            referral = get(connection, "referral", referral_id)
            if referral["version"] != payload.expected_version:
                raise HTTPException(409, "Referral changed; reload before editing")
            if "source_ref" in data and data["source_ref"] != referral["source_ref"]:
                raise HTTPException(409, "The original intake source is immutable")
            fields = {k: v for k, v in referral.items() if k in Referral.model_fields}
            fields.update({k: v for k, v in data.items() if k != "expected_version"})
            try:
                fields = Referral.model_validate(fields).model_dump(mode="json")
            except ValidationError:
                raise HTTPException(422, "Referral fields are invalid") from None
            duplicates = duplicate_ids(connection, fields, exclude=referral_id)
            if duplicates:
                raise HTTPException(409, {"message": "Contact matches another referral", "duplicate_ids": duplicates})
            updated = {**referral, **fields, "version": referral["version"] + 1}
            if updated["status"] != "New" and missing_info(updated):
                raise HTTPException(409, "A qualified referral must retain its required intake information")
            if is_suppressed(connection, updated):
                updated["contact_status"] = "stopped"
                for kind, value in contacts(updated).items():
                    connection.execute("INSERT OR IGNORE INTO suppressed VALUES (?,?)", (kind, value))
                for draft in records(connection, "draft"):
                    if draft["referral_id"] == referral_id:
                        put(connection, "draft", {**draft, "status": "suppressed"})
                block_family_in_plans(connection, referral_id)
            return referral_view(connection, put(connection, "referral", updated))

        return store.mutate(key, f"referral.update:{referral_id}", data, operation)

    @router.post("/referrals/{referral_id}/transition")
    def transition(referral_id: str, payload: Transition, store: Store = account, key: str = retry):
        def operation(connection):
            referral = get(connection, "referral", referral_id)
            previous = {"Qualified": "New", "Touring": "Qualified"}[payload.status]
            if referral["status"] != previous or missing_info(referral):
                raise HTTPException(409, "Transition requires complete intake and the preceding lifecycle stage")
            if payload.status == "Touring" and not any(t["referral_id"] == referral_id for t in records(connection, "tour")):
                raise HTTPException(409, "A proposed tour is required")
            referral.update(status=payload.status, version=referral["version"] + 1, reviewed_by=store.user_id)
            return referral_view(connection, put(connection, "referral", referral))

        return store.mutate(key, f"referral.transition:{referral_id}", payload.model_dump(mode="json"), operation)

    @router.post("/referrals/{referral_id}/contact-events")
    def contact_event(referral_id: str, payload: ContactEvent, store: Store = account, key: str = retry):
        def operation(connection):
            referral = get(connection, "referral", referral_id)
            stopped = payload.event == "stop" or is_suppressed(connection, referral)
            referral.update(contact_status="stopped" if stopped else "paused", version=referral["version"] + 1)
            if stopped:
                for kind, value in contacts(referral).items():
                    connection.execute("INSERT OR IGNORE INTO suppressed VALUES (?,?)", (kind, value))
            put(connection, "contact_event", create_record({**payload.model_dump(mode="json"), "referral_id": referral_id}))
            if stopped or payload.event == "decline":
                block_family_in_plans(connection, referral_id)
            for draft in records(connection, "draft"):
                if draft["referral_id"] == referral_id:
                    draft["status"] = "suppressed" if stopped else "paused"
                    put(connection, "draft", draft)
            return referral_view(connection, put(connection, "referral", referral))

        return store.mutate(key, f"referral.contact_event:{referral_id}", payload.model_dump(mode="json"), operation)

    @router.post("/referrals/{referral_id}/drafts", status_code=201)
    def draft_followup(referral_id: str, payload: Draft, store: Store = account, key: str = retry):
        def operation(connection):
            referral = get(connection, "referral", referral_id)
            preference = referral["contact_preference"]
            if is_suppressed(connection, referral) or referral["contact_status"] != "active" or preference == "none" or not referral.get(preference):
                raise HTTPException(409, "Follow-up is paused, stopped, or lacks a usable contact preference")
            return put(connection, "draft", create_record({**payload.model_dump(mode="json"), "referral_id": referral_id, "status": "draft", "sent": False}))

        return store.mutate(key, f"referral.draft:{referral_id}", payload.model_dump(mode="json"), operation)

    @router.post("/communities", status_code=201)
    def create_community(payload: Community, store: Store = account, key: str = retry):
        try:
            before_now(payload.observed_at, now())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        data = payload.model_dump(mode="json")
        return store.mutate(
            key,
            "community.create",
            data,
            lambda connection: community_view(put(connection, "community", create_record({**data, "contract_status": "not_contracted"}))),
        )

    @router.post("/communities/{community_id}/availability")
    def verify_availability(community_id: str, payload: Availability, store: Store = account, key: str = retry):
        def operation(connection):
            community = get(connection, "community", community_id)
            if payload.verified_at > now() or payload.expires_at <= now():
                raise HTTPException(422, "Availability needs a past verification and a future expiry")
            current = community.get("availability")
            if current and payload.verified_at <= datetime.fromisoformat(current["verified_at"]):
                raise HTTPException(409, "Availability verification must be newer than the current record")
            if community["licensed_beds"] is not None and payload.vacancies > community["licensed_beds"]:
                raise HTTPException(422, "Verified vacancies exceed the sourced licensed capacity")
            community["availability"] = {**payload.model_dump(mode="json"), "verified_by": store.user_id}
            return community_view(put(connection, "community", community))

        return store.mutate(key, f"community.availability:{community_id}", payload.model_dump(mode="json"), operation)

    @router.post("/tours", status_code=201)
    def propose_tour(payload: Tour, store: Store = account, key: str = retry):
        def operation(connection):
            referral = get(connection, "referral", payload.referral_id)
            community = get(connection, "community", payload.community_id)
            if referral["status"] not in ("Qualified", "Touring"):
                raise HTTPException(409, "A human-qualified referral is required")
            if payload.start_at <= now():
                raise HTTPException(422, "Propose a future tour")
            for existing in records(connection, "tour"):
                if overlaps(payload.start_at, payload.end_at, existing["start_at"], reserved_end(existing)):
                    raise HTTPException(409, {"message": "Conflicts with an existing tour proposal", "tour_id": existing["id"]})
            data = {
                **payload.model_dump(mode="json"),
                "status": "proposed",
                "calendar_connected": False,
                "availability_at_proposal": community_view(community)["availability"],
            }
            return put(connection, "tour", create_record(data))

        return store.mutate(key, "tour.propose", payload.model_dump(mode="json"), operation)

    @router.post("/placements", status_code=201)
    def confirm_placement(payload: Placement, store: Store = account, key: str = retry):
        require_confirmer(service, store, "confirm a placement")

        def operation(connection):
            referral = get(connection, "referral", payload.referral_id)
            get(connection, "community", payload.community_id)
            if any(p["referral_id"] == payload.referral_id for p in records(connection, "placement")):
                raise HTTPException(409, "This referral already has a placement")
            if referral["status"] not in ("Qualified", "Touring") or missing_info(referral):
                raise HTTPException(409, "Placement requires a qualified referral with no existing placement")
            if payload.move_in_date > business_date() or payload.agreement_signed_on > payload.move_in_date:
                raise HTTPException(422, "Move-in must have occurred and the agreement must be signed by move-in")
            data = {
                **payload.model_dump(mode="json"),
                "confirmed_by": store.user_id,
                "confirmed_at": now().isoformat(),
                "installments": [
                    {"day": day, "due_date": (payload.move_in_date + timedelta(days=day)).isoformat(), "amount_cents": amount}
                    for day, amount in [(30, payload.fee_cents // 2), (60, payload.fee_cents - payload.fee_cents // 2)]
                ],
            }
            referral.update(status="Placed", contact_status="paused" if referral["contact_status"] != "stopped" else "stopped", version=referral["version"] + 1)
            put(connection, "referral", referral)
            for draft in records(connection, "draft"):
                if draft["referral_id"] == referral["id"] and draft["status"] == "draft":
                    put(connection, "draft", {**draft, "status": "paused"})
            return put(connection, "placement", create_record(data))

        return store.mutate(key, "placement.confirm", payload.model_dump(mode="json"), operation)

    @router.post("/placements/{placement_id}/ledger", status_code=201)
    def record_receipt(placement_id: str, payload: LedgerEntry, store: Store = account, key: str = retry):
        def operation(connection):
            placement = get(connection, "placement", placement_id)
            if payload.event_date > business_date() or payload.event_date < date.fromisoformat(placement["agreement_signed_on"]):
                raise HTTPException(422, "Receipt date must be between agreement signing and today")
            ledger = records(connection, "ledger")
            if any(e["receipt_ref"] == payload.receipt_ref and e["kind"] == payload.kind for e in ledger):
                raise HTTPException(409, "This receipt is already recorded")
            entries = [e for e in ledger if e["placement_id"] == placement_id and e["day"] == payload.day]
            invoiced = sum(e["amount_cents"] for e in entries if e["kind"] == "invoiced")
            collected = sum(e["amount_cents"] for e in entries if e["kind"] == "collected")
            contracted = next(x["amount_cents"] for x in placement["installments"] if x["day"] == payload.day)
            room = contracted - invoiced if payload.kind == "invoiced" else invoiced - collected
            if payload.amount_cents > room:
                raise HTTPException(409, "Amount exceeds the installment contract or its recorded unpaid invoices")
            return put(
                connection,
                "ledger",
                create_record({**payload.model_dump(mode="json"), "placement_id": placement_id, "recorded_by": store.user_id, "record_type": "manual_receipt"}),
            )

        return store.mutate(key, f"placement.ledger:{placement_id}", payload.model_dump(mode="json"), operation)

    @router.post("/communities/{community_id}/contract")
    def update_contract(community_id: str, payload: ContractUpdate, store: Store = account, key: str = retry):
        require_confirmer(service, store, "record a community contract")

        def operation(connection):
            community = get(connection, "community", community_id)
            community["contract_status"] = payload.status
            community["contract"] = {**payload.model_dump(mode="json"), "recorded_by": store.user_id, "recorded_at": now().isoformat()}
            if payload.status != "contracted" and community.get("rating"):
                community["rating"] = None  # stars apply only while contracted; history stays in the audit log
            return community_view(put(connection, "community", community))

        return store.mutate(key, f"community.contract:{community_id}", payload.model_dump(mode="json"), operation)

    @router.post("/communities/{community_id}/rating")
    def rate_community(community_id: str, payload: Rating, store: Store = account, key: str = retry):
        require_confirmer(service, store, "rate a community")

        def operation(connection):
            community = get(connection, "community", community_id)
            if community.get("contract_status") != "contracted":
                raise HTTPException(409, "Stars are for communities the owner has contracted; record the contract first")
            community["rating"] = {"stars": payload.stars, "note": payload.note, "rated_by": store.user_id, "rated_on": business_date().isoformat()}
            return community_view(put(connection, "community", community))

        return store.mutate(key, f"community.rating:{community_id}", payload.model_dump(mode="json"), operation)

    @router.get("/recommendations")
    def recommendations(
        store: Store = account,
        city: str | None = Query(None, max_length=200),
        services: str | None = Query(None, max_length=1000, description="Comma-separated services the family needs"),
        category: str | None = Query(None, max_length=100),
        max_miles: float | None = Query(None, ge=0, le=500),
        limit: int = Query(3, ge=1, le=3),
    ):
        wanted = [s.strip() for s in (services or "").split(",") if s.strip()]
        with store.transaction() as connection:
            result = recommend(records(connection, "community"), city=city, services=wanted, category=category, max_miles=max_miles, limit=limit)
        result["criteria"] = {"city": city, "services": wanted, "category": category, "max_miles": max_miles}
        result["note"] = "Fit decides which communities appear. Contract status and fees never outrank fit. Licensed capacity is not vacancy."
        return result

    @router.post("/tour-plans", status_code=201)
    def create_tour_plan(payload: TourPlan, store: Store = account, key: str = retry):
        def operation(connection):
            referral = get(connection, "referral", payload.referral_id)
            if referral["status"] not in ("Qualified", "Touring"):
                raise HTTPException(409, "A human-qualified referral is required")
            communities = [get(connection, "community", community_id) for community_id in payload.community_ids]
            if any(option <= now() for option in payload.options):
                raise HTTPException(422, "Every candidate start time must be in the future")
            plans = [p for p in records(connection, "tour_plan") if p["referral_id"] == referral["id"] and p["status"] in ACTIVE_PLAN]
            if any(p["id"] != payload.supersedes_plan_id for p in plans):
                raise HTTPException(
                    409, {"message": "This family already has an open tour plan; pass supersedes_plan_id to replace it", "plan_ids": [p["id"] for p in plans]}
                )
            if payload.supersedes_plan_id and not plans:
                raise HTTPException(409, "The plan to supersede is not open for this family")
            for old in plans:
                put(connection, "tour_plan", {**old, "status": "superseded"})
                for draft in records(connection, "draft"):
                    if draft.get("tour_plan_id") == old["id"] and draft["status"] == "draft":
                        put(connection, "draft", {**draft, "status": "superseded"})
            existing = records(connection, "tour")
            options = []
            for start in sorted(payload.options):
                stops = coordination.itinerary(start, communities, payload.tour_minutes, payload.travel_minutes)
                span_start, span_end = itinerary_span(stops)
                conflicts = [t["id"] for t in existing if overlaps(span_start, span_end, t["start_at"], reserved_end(t))]
                options.append({"stops": stops, "conflicts_with_tours": conflicts})
            if all(o["conflicts_with_tours"] for o in options):
                raise HTTPException(409, "Every candidate time overlaps an existing proposed tour")
            usable = [o for o in options if not o["conflicts_with_tours"]]
            plan_id = str(uuid4())
            # Only a stop, suppression, or no usable contact preference closes the family slot.
            # A reply/booking pause keeps the plan open so every party's reply can be recorded. It withholds a new family
            # draft, except when this plan supersedes the family's open plan: the operator is continuing that conversation.
            blocked = is_suppressed(connection, referral) or referral["contact_preference"] == "none"
            withhold_family = blocked or (referral["contact_status"] == "paused" and not payload.supersedes_plan_id)
            family = None if withhold_family else coordination.family_drafts(referral, usable, service.advisor_name, service.business_line)
            if family:
                channel = referral["contact_preference"]
                body = family["family_email"] if channel == "email" else family["family_text"]
                put(
                    connection,
                    "draft",
                    create_record(
                        {"referral_id": referral["id"], "reason": "tour_coordination", "body": body, "status": "draft", "sent": False, "tour_plan_id": plan_id}
                    ),
                )
            plan = {
                "id": plan_id,
                **payload.model_dump(mode="json"),
                "status": "family_contact_blocked" if blocked else "awaiting_replies",
                "options": usable,
                "dropped_conflicting_options": len(options) - len(usable),
                "parties": {
                    "family": {"status": "blocked" if blocked else "pending"},
                    "owner": {"status": "pending"},
                    "communities": {c["id"]: {"status": "pending"} for c in communities},
                },
                "drafts": {
                    "family": family,
                    "communities": {c["id"]: coordination.community_drafts(c, usable, service.advisor_name) for c in communities},
                    "owner_summary": coordination.owner_summary(referral, usable, withhold_family),
                },
                "sent": False,
                "calendar_connected": False,
                "created_by": store.user_id,
                "created_at": now().isoformat(),
            }
            return put(connection, "tour_plan", plan)

        return store.mutate(key, "tour_plan.create", payload.model_dump(mode="json"), operation)

    @router.post("/tour-plans/{plan_id}/responses")
    def record_tour_response(plan_id: str, payload: TourResponse, store: Store = account, key: str = retry):
        if payload.party == "owner":
            require_confirmer(service, store, "record the owner's reply")

        def operation(connection):
            plan = get(connection, "tour_plan", plan_id)
            referral = get(connection, "referral", plan["referral_id"])
            if is_suppressed(connection, referral):
                block_family_in_plans(connection, referral["id"])
                raise HTTPException(409, "The family asked to stop contact; this tour plan is closed")
            if plan["status"] not in ("awaiting_replies", "needs_new_times"):
                raise HTTPException(409, f"This tour plan is {plan['status']}")
            if payload.option is not None and payload.option > len(plan["options"]):
                raise HTTPException(422, "That option number is not in this plan")
            if payload.party == "community":
                if payload.community_id not in plan["parties"]["communities"]:
                    raise HTTPException(422, "That community is not in this plan")
                slot = plan["parties"]["communities"][payload.community_id]
            else:
                slot = plan["parties"][payload.party]
                if payload.party == "family" and slot["status"] == "blocked":
                    raise HTTPException(409, "Family contact is stopped or has no usable contact preference; this plan cannot record a family reply")
            if payload.party == "family":
                # Share the reply pause with /contact-events: paused contact stops new follow-ups, the plan stays open.
                referral.update(contact_status="paused", version=referral["version"] + 1)
                put(connection, "referral", referral)
                for draft in records(connection, "draft"):
                    if draft["referral_id"] == referral["id"] and draft["status"] == "draft":
                        put(connection, "draft", {**draft, "status": "paused"})
            slot.update(
                status=payload.response,
                option=payload.option,
                source_ref=payload.source_ref,
                note=payload.note,
                recorded_by=store.user_id,
                at=now().isoformat(),
            )
            parties = [plan["parties"]["family"], plan["parties"]["owner"], *plan["parties"]["communities"].values()]
            agreed = {p.get("option") for p in parties}
            everyone_accepted = all(p["status"] == "accepts" for p in parties)
            if everyone_accepted and len(agreed) == 1:
                chosen = plan["options"][agreed.pop() - 1]
                if referral["status"] not in ("Qualified", "Touring"):
                    raise HTTPException(409, "The family's case is no longer qualified for tours")
                if datetime.fromisoformat(chosen["stops"][0]["start_at"]) <= now():
                    raise HTTPException(409, "The agreed time has passed; prepare a new plan with supersedes_plan_id")
                tours = records(connection, "tour")
                span_start, span_end = itinerary_span(chosen["stops"])
                clash = next((t for t in tours if overlaps(span_start, span_end, t["start_at"], reserved_end(t))), None)
                if clash:
                    raise HTTPException(409, {"message": "The agreed time now overlaps another proposed tour", "tour_id": clash["id"]})
                for index, stop in enumerate(chosen["stops"]):
                    # Reserve the drive after each stop so later proposals cannot book the owner in it.
                    next_start = chosen["stops"][index + 1]["start_at"] if index + 1 < len(chosen["stops"]) else stop["end_at"]
                    put(
                        connection,
                        "tour",
                        create_record(
                            {
                                "referral_id": plan["referral_id"],
                                "community_id": stop["community_id"],
                                "start_at": stop["start_at"],
                                "end_at": stop["end_at"],
                                "reserved_end_at": next_start,
                                "status": "proposed",
                                "parties_confirmed": True,
                                "calendar_connected": False,
                                "tour_plan_id": plan_id,
                            }
                        ),
                    )
                plan.update(status="ready_to_book", chosen_option=plan["options"].index(chosen) + 1)
            elif everyone_accepted or any(p["status"] == "declines" for p in parties):
                plan["status"] = "needs_new_times"  # a decline, or everyone said yes to different options
            else:
                plan["status"] = "awaiting_replies"
            return put(connection, "tour_plan", plan)

        return store.mutate(key, f"tour_plan.response:{plan_id}", payload.model_dump(mode="json"), operation)

    @router.get("/tour-plans/{plan_id}/calendar.ics")
    def tour_plan_calendar(plan_id: str, store: Store = account, option: int = Query(1, ge=1, le=3)):
        with store.transaction() as connection:
            plan = get(connection, "tour_plan", plan_id)
        if option > len(plan["options"]):
            raise HTTPException(404, "That option number is not in this plan")
        body = coordination.tentative_calendar(plan_id, option, plan["options"][option - 1]["stops"], now())
        return PlainTextResponse(
            body,
            media_type="text/calendar",
            headers={"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="tour-{plan_id[:8]}-option-{option}.ics"'},
        )

    @router.get("/regulations")
    def regulation_states(store: Store = account):
        loaded = []
        for state in regulations.available_states():
            corpus = regulations.load(state)
            loaded.append(
                {
                    "state": state,
                    "name": corpus.name,
                    "retrieved_at": corpus.retrieved_at,
                    "sources": corpus.sources,
                    "units": len(corpus.units),
                    "documents": len(corpus.documents),
                }
            )
        return {"states": loaded, "rule": "Answers come only from these primary sources and cite the exact rule or statute section."}

    @router.get("/regulations/{state}/search")
    def regulation_search(state: str, store: Store = account, q: str = Query(min_length=2, max_length=500), limit: int = Query(6, ge=1, le=20)):
        corpus = regulations.load(state)
        if corpus is None:
            raise HTTPException(404, f"No primary-source regulation corpus is loaded for {state.upper()[:2]}")
        return {"state": corpus.state, "query": q, "retrieved_at": corpus.retrieved_at, "results": corpus.search(q, limit)}

    @router.get("/regulations/{state}/unit")
    def regulation_unit(state: str, store: Store = account, citation: str = Query(min_length=3, max_length=200)):
        corpus = regulations.load(state)
        if corpus is None:
            raise HTTPException(404, f"No primary-source regulation corpus is loaded for {state.upper()[:2]}")
        unit = corpus.section(citation)
        if unit is None:
            raise HTTPException(404, "No unit with that exact citation, for example 'Rule 59A-36.006(1)(a)4., F.A.C.'")
        return unit

    @router.get("/dashboard", include_in_schema=False)
    def dashboard_redirect(store: Store = account):
        return RedirectResponse("/api/vhin/dashboard/", headers={"Cache-Control": "no-store"})

    @router.get("/dashboard/{asset:path}", include_in_schema=False)
    def dashboard(asset: str, store: Store = account):
        if asset not in ("", "index.html", "app.js", "style.css"):
            raise HTTPException(404, "Asset not found")
        path = Path(__file__).parent / "static" / (asset or "index.html")
        if not path.is_file():
            raise HTTPException(404, "Dashboard asset not installed")
        return FileResponse(path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return router
