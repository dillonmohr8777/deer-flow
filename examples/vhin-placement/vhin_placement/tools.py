"""Workspace-scoped ModelTool contributions for voice/chat Placement Desk operations.

Every tool fails closed unless ``ToolContext`` proves the caller belongs to the
configured VHIN organization AND explicit ``allowed_user_ids`` (plus
``confirmers`` for owner-only star ratings and contract updates).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from deerflow_extension_api.plugins import ModelTool, PluginContribution, ToolContext

from vhin_placement.api import (
    UNCONTRACTED_WARNING,
    Service,
    business_date,
    community_view,
    contract_sprint_targets,
    create_record,
    duplicate_ids,
    recommend,
    referral_view,
)
from vhin_placement.models import Community, ContractUpdate, Rating, Referral
from vhin_placement.store import encode, get, now, put, records


def _authorize_store(service: Service, ctx: ToolContext, *, require_owner: bool = False):
    actor = ctx.actor_user_id or ctx.principal.user_id
    if not ctx.organization_id or ctx.organization_id != service.organization_id:
        raise PermissionError("Placement tools are restricted to the authorized VHIN workspace.")
    if actor not in service.allowed_user_ids:
        raise PermissionError("User is not authorized for VHIN Placement Desk tools.")
    if require_owner and actor not in service.confirmers:
        raise PermissionError("Only the configured placement owner account can perform this action.")
    return service.store_for(actor), actor


def _resolve_community(connection, identifier: str) -> dict:
    needle = identifier.strip()
    all_rows = records(connection, "community")
    for row in all_rows:
        if row["id"] == needle:
            return row
    lowered = needle.casefold()
    exact = [row for row in all_rows if row["name"].strip().casefold() == lowered]
    if len(exact) == 1:
        return exact[0]
    partial = [row for row in all_rows if lowered in row["name"].strip().casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(r["name"] for r in partial[:5])
        raise ValueError(f"Multiple communities match '{identifier}': {names}. Specify the exact name or community_id.")
    raise ValueError(f"Community '{identifier}' not found. Use add_or_update_facility to add a new custom facility.")


def build_plugin(service: Service) -> PluginContribution:
    async def search_facilities(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        store, _ = _authorize_store(service, ctx)
        services = [s.strip() for s in (payload.get("services") or []) if isinstance(s, str) and s.strip()]
        limit = min(max(int(payload.get("limit") or 3), 1), 3)
        with store.transaction() as connection:
            result = recommend(
                records(connection, "community"),
                city=payload.get("city"),
                services=services,
                category=payload.get("category"),
                max_miles=payload.get("max_miles"),
                contracted_only=bool(payload.get("contracted_only", False)),
                limit=limit,
            )
        return {
            **result,
            "ranking_rule": "Contracted first, owner 1-3 star tour rating desc, verified openings, distance asc. Zero public Google/Facebook ratings.",
        }

    async def rate_facility(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        store, actor = _authorize_store(service, ctx, require_owner=True)
        rating = Rating(stars=int(payload["stars"]), note=str(payload.get("tour_note") or ""))
        target = str(payload["facility"]).strip()
        with store.transaction() as connection:
            community = _resolve_community(connection, target)
            community["rating"] = {
                "stars": rating.stars,
                "note": rating.note,
                "rated_by": actor,
                "rated_on": business_date().isoformat(),
            }
            saved = community_view(put(connection, "community", community))
            connection.execute(
                "INSERT INTO audit(at,actor,action,entity_id) VALUES (?,?,?,?)",
                (now().isoformat(), actor, "community.rating.tool", saved["id"]),
            )
            return {
                "saved": True,
                "community_id": saved["id"],
                "name": saved["name"],
                "owner_rating": saved["owner_rating"],
                "contracted": saved["contracted"],
                "contract_warning": saved["contract_warning"],
            }

    async def set_contract_status(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        store, actor = _authorize_store(service, ctx, require_owner=True)
        contracted = bool(payload["contracted"])
        status = "contracted" if contracted else str(payload.get("status") or "not_contracted")
        agreement_ref = str(payload.get("agreement_ref") or ("Signed agreement on file" if status == "contracted" else "")).strip() or None
        update = ContractUpdate(status=status, agreement_ref=agreement_ref, human_confirmed=True)
        target = str(payload["facility"]).strip()
        with store.transaction() as connection:
            community = _resolve_community(connection, target)
            community["contract_status"] = update.status
            community["contract"] = {**update.model_dump(mode="json"), "recorded_by": actor, "recorded_at": now().isoformat()}
            saved = community_view(put(connection, "community", community))
            connection.execute(
                "INSERT INTO audit(at,actor,action,entity_id) VALUES (?,?,?,?)",
                (now().isoformat(), actor, "community.contract.tool", saved["id"]),
            )
            return {
                "saved": True,
                "community_id": saved["id"],
                "name": saved["name"],
                "contract_status": saved["contract_status"],
                "contracted": saved["contracted"],
                "contract_warning": saved["contract_warning"],
                "owner_rating": saved["owner_rating"],
            }

    async def add_or_update_facility(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        want_owner = payload.get("stars") is not None or payload.get("contracted") is not None
        store, actor = _authorize_store(service, ctx, require_owner=want_owner)
        name = str(payload["name"]).strip()
        city = str(payload["city"]).strip()
        care_levels = [str(x).strip() for x in (payload.get("care_levels") or []) if str(x).strip()]
        services = [str(x).strip() for x in (payload.get("services") or care_levels) if str(x).strip()]
        community_input = Community(
            name=name,
            city=city,
            services=services,
            care_levels=care_levels,
            licensed_beds=int(payload["licensed_beds"]) if payload.get("licensed_beds") is not None else None,
            category=payload.get("category"),
            miles_from_office=float(payload["miles_from_office"]) if payload.get("miles_from_office") is not None else None,
            address=payload.get("address"),
            ahca_license=payload.get("ahca_license"),
            private_rate_range=payload.get("private_rate_range"),
            semi_private_rate_range=payload.get("semi_private_rate_range"),
            community_fee=payload.get("community_fee"),
            accepts_medicaid=payload.get("accepts_medicaid"),
            accepts_va=payload.get("accepts_va"),
            vhin_owned=bool(payload.get("vhin_owned", False)),
            contact_name=payload.get("contact_name"),
            contact_email=payload.get("contact_email"),
            contact_phone=payload.get("contact_phone"),
            contact_sms_phone=payload.get("contact_sms_phone"),
            preferred_pulse_channel=payload.get("preferred_pulse_channel") or "email",
            source_kind="owner_added",
            observed_at=now(),
        )
        rating = Rating(stars=int(payload["stars"]), note=str(payload.get("tour_note") or "")) if payload.get("stars") is not None else None
        contract_update = None
        if payload.get("contracted") is not None:
            is_c = bool(payload["contracted"])
            contract_update = ContractUpdate(
                status="contracted" if is_c else "not_contracted",
                agreement_ref=(str(payload.get("agreement_ref") or "Signed agreement on file").strip() if is_c else None),
                human_confirmed=True,
            )
        with store.transaction() as connection:
            existing = next(
                (
                    c
                    for c in records(connection, "community")
                    if c["name"].strip().casefold() == name.casefold() and c["city"].strip().casefold() == city.casefold()
                ),
                None,
            )
            if existing is not None:
                merged = dict(existing)
                for k, v in community_input.model_dump(mode="json", exclude_none=True).items():
                    if k != "source_kind" or merged.get("source_kind") == "owner_added":
                        merged[k] = v
                action = "community.update.tool"
            else:
                merged = create_record({**community_input.model_dump(mode="json"), "contract_status": "not_contracted"})
                action = "community.create.tool"
            if contract_update is not None:
                merged["contract_status"] = contract_update.status
                merged["contract"] = {**contract_update.model_dump(mode="json"), "recorded_by": actor, "recorded_at": now().isoformat()}
            if rating is not None:
                merged["rating"] = {"stars": rating.stars, "note": rating.note, "rated_by": actor, "rated_on": business_date().isoformat()}
            saved = community_view(put(connection, "community", merged))
            connection.execute(
                "INSERT INTO audit(at,actor,action,entity_id) VALUES (?,?,?,?)",
                (now().isoformat(), actor, action, saved["id"]),
            )
            return {
                "saved": True,
                "created": existing is None,
                "community": saved,
                "contract_warning": None if saved["contracted"] else UNCONTRACTED_WARNING,
            }

    async def weekly_contract_targets(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        store, _ = _authorize_store(service, ctx)
        limit = min(max(int(payload.get("limit") or 5), 1), 10)
        max_miles = float(payload["max_miles"]) if payload.get("max_miles") is not None else 30.0
        with store.transaction() as connection:
            return contract_sprint_targets(
                records(connection, "community"),
                city=payload.get("city"),
                max_miles=max_miles,
                category=payload.get("category"),
                limit=limit,
            )

    async def save_referral(payload: Mapping[str, Any], ctx: ToolContext) -> dict[str, Any]:
        store, actor = _authorize_store(service, ctx)
        source_ref = str(payload.get("source_ref") or f"chat-{uuid4().hex[:10]}").strip()
        ref = Referral(
            name=str(payload["name"]).strip(),
            phone=payload.get("phone"),
            email=payload.get("email"),
            responsible_contact=payload.get("responsible_contact"),
            location=payload.get("location"),
            budget_cents=int(payload["budget_cents"]) if payload.get("budget_cents") is not None else None,
            care_needs=payload.get("care_needs"),
            timing=payload.get("timing"),
            source_ref=source_ref,
            contact_preference=payload.get("contact_preference") or "none",
            attention=payload.get("attention") or "routine",
        )
        data = ref.model_dump(mode="json")
        with store.transaction() as connection:
            source_hash = hashlib.sha256(encode(data).encode()).hexdigest()
            prior_row = connection.execute("SELECT body FROM records WHERE kind='source' AND id=?", (source_ref,)).fetchone()
            if prior_row:
                prior = get(connection, "source", source_ref)
                if prior["digest"] != source_hash:
                    raise ValueError("This source_ref already exists with different referral data.")
                return {"saved": True, "deduped": True, "referral": referral_view(connection, get(connection, "referral", prior["referral_id"]))}
            dups = duplicate_ids(connection, data)
            if dups:
                return {"saved": False, "duplicate_ids": dups, "message": "Contact matches an existing referral; review before creating another."}
            record = create_record({**data, "status": "New", "contact_status": "active", "version": 1})
            put(connection, "source", {"id": source_ref, "digest": source_hash, "referral_id": record["id"]})
            saved = referral_view(connection, put(connection, "referral", record))
            connection.execute(
                "INSERT INTO audit(at,actor,action,entity_id) VALUES (?,?,?,?)",
                (now().isoformat(), actor, "referral.create.tool", saved["id"]),
            )
            return {"saved": True, "deduped": False, "referral": saved}

    tools = (
        ModelTool(
            name="search_facilities",
            description=(
                "Search Placement Desk facilities by city, radius (miles), care levels/services, or contracted status. "
                "Ranks contracted homes first, then owner's private 1-3 star tour rating (zero public Google/Facebook ratings)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "max_miles": {"type": "number", "minimum": 0, "maximum": 500},
                    "category": {"type": "string"},
                    "services": {"type": "array", "items": {"type": "string"}},
                    "contracted_only": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 3},
                },
                "additionalProperties": False,
            },
            handler=search_facilities,
        ),
        ModelTool(
            name="rate_facility",
            description="Save the placement owner's private 1-3 star in-person tour rating and tour notes on any facility (contracted or uncontracted).",
            input_schema={
                "type": "object",
                "required": ["facility", "stars"],
                "properties": {
                    "facility": {"type": "string", "description": "Community ID or facility name"},
                    "stars": {"type": "integer", "minimum": 1, "maximum": 3},
                    "tour_note": {"type": "string", "maxLength": 1000},
                },
                "additionalProperties": False,
            },
            handler=rate_facility,
        ),
        ModelTool(
            name="set_contract_status",
            description="Update a facility's placement contract status (Contracted Yes/No) and agreement reference.",
            input_schema={
                "type": "object",
                "required": ["facility", "contracted"],
                "properties": {
                    "facility": {"type": "string", "description": "Community ID or facility name"},
                    "contracted": {"type": "boolean"},
                    "status": {"type": "string", "enum": ["not_contracted", "in_progress", "contracted"]},
                    "agreement_ref": {"type": "string"},
                },
                "additionalProperties": False,
            },
            handler=set_contract_status,
        ),
        ModelTool(
            name="add_or_update_facility",
            description=(
                "Add a new pre-listing/custom facility (e.g. brand-new opening not yet in Florida Health Finder) "
                "or update an existing facility's beds, care levels, rates, Medicaid/VA, pulse channel, contract status, or 1-3 star tour rating."
            ),
            input_schema={
                "type": "object",
                "required": ["name", "city"],
                "properties": {
                    "name": {"type": "string"},
                    "city": {"type": "string"},
                    "miles_from_office": {"type": "number", "minimum": 0, "maximum": 500},
                    "licensed_beds": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "category": {"type": "string"},
                    "care_levels": {"type": "array", "items": {"type": "string"}},
                    "services": {"type": "array", "items": {"type": "string"}},
                    "address": {"type": "string"},
                    "ahca_license": {"type": "string"},
                    "private_rate_range": {"type": "string"},
                    "semi_private_rate_range": {"type": "string"},
                    "community_fee": {"type": "string"},
                    "accepts_medicaid": {"type": "boolean"},
                    "accepts_va": {"type": "boolean"},
                    "vhin_owned": {"type": "boolean"},
                    "contact_name": {"type": "string"},
                    "contact_email": {"type": "string"},
                    "contact_phone": {"type": "string"},
                    "contact_sms_phone": {"type": "string"},
                    "preferred_pulse_channel": {"type": "string", "enum": ["email", "sms", "both"]},
                    "contracted": {"type": "boolean"},
                    "agreement_ref": {"type": "string"},
                    "stars": {"type": "integer", "minimum": 1, "maximum": 3},
                    "tour_note": {"type": "string", "maxLength": 1000},
                },
                "additionalProperties": False,
            },
            handler=add_or_update_facility,
        ),
        ModelTool(
            name="weekly_contract_targets",
            description=(
                "Weekly 5-Facility Contracting Sprint: return the top uncontracted residential facilities "
                "(ALF, Memory Care, AFCH) within target radius, sorted by proximity and bed count."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "max_miles": {"type": "number", "minimum": 0, "maximum": 500},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "additionalProperties": False,
            },
            handler=weekly_contract_targets,
        ),
        ModelTool(
            name="save_referral",
            description="Record a family referral in Placement Desk with source deduplication and missing-field tracking.",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "responsible_contact": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "location": {"type": "string"},
                    "budget_cents": {"type": "integer", "minimum": 1},
                    "care_needs": {"type": "string"},
                    "timing": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "contact_preference": {"type": "string", "enum": ["email", "phone", "none"]},
                    "attention": {"type": "string", "enum": ["routine", "urgent", "human_request"]},
                },
                "additionalProperties": False,
            },
            handler=save_referral,
        ),
    )
    return PluginContribution(
        namespace="vhin",
        title="VHIN Placement Desk",
        description="Authenticated Placement Desk tools for facility search, 1-3 star tour ratings, contract sprints, and referral intake.",
        enabled=True,
        tools=tools,
    )
