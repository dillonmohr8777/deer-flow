"""Authenticated operations only: no sends, calendar writes, models, or billing."""

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from deerflow_extension_api import resolve_principal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from vhin_placement.models import (
    Availability,
    Community,
    ContactEvent,
    Draft,
    LedgerEntry,
    Placement,
    Referral,
    ReferralPatch,
    Tour,
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
    return {**community, "availability": availability}


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
                "audit": [dict(row) for row in connection.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 100")],
                "connections": {"intake": "manual", "calendar": "unconnected", "sender": "unconnected", "billing": "unconnected", "handoff": "unconnected"},
                "can_confirm_placement": store.user_id in service.confirmers,
                "briefing": {
                    "new_referrals": sum(r["status"] == "New" for r in referrals),
                    "incomplete_referrals": sum(bool(r["missing_info"]) for r in referrals),
                    "qualified_referrals": sum(r["status"] == "Qualified" for r in referrals),
                    "proposed_tours": len(tours),
                    "confirmed_tours": 0,
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
            if is_suppressed(connection, referral):
                updated["contact_status"] = "stopped"
                for kind, value in contacts(updated).items():
                    connection.execute("INSERT OR IGNORE INTO suppressed VALUES (?,?)", (kind, value))
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
        return store.mutate(key, "community.create", data, lambda connection: community_view(put(connection, "community", create_record(data))))

    @router.post("/communities/{community_id}/availability")
    def verify_availability(community_id: str, payload: Availability, store: Store = account, key: str = retry):
        def operation(connection):
            community = get(connection, "community", community_id)
            if payload.verified_at > now() or payload.expires_at <= now():
                raise HTTPException(422, "Availability needs a past verification and a future expiry")
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
                if payload.start_at < datetime.fromisoformat(existing["end_at"]) and payload.end_at > datetime.fromisoformat(existing["start_at"]):
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
        if store.user_id not in service.confirmers:
            raise HTTPException(403, "Only the configured Justin account can confirm a placement")

        def operation(connection):
            referral = get(connection, "referral", payload.referral_id)
            get(connection, "community", payload.community_id)
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
