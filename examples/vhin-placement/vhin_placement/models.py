"""Bounded request contracts. Facts stay unknown until an operator records them."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StrictInt, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Money = Annotated[StrictInt, Field(ge=1, le=100_000_000)]


def check_email(value):
    if value is not None and (value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value)):
        raise ValueError("email must contain one @ and no whitespace")
    return value


def check_phone(value):
    if value is not None and (not 7 <= len("".join(filter(str.isdigit, value))) <= 15 or any(c not in "+()- .0123456789" for c in value)):
        raise ValueError("phone must contain 7 to 15 digits")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Referral(Input):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    phone: Annotated[str, Field(max_length=40)] | None = None
    email: Annotated[str, Field(max_length=254)] | None = None
    responsible_contact: Text | None = None
    location: Text | None = None
    budget_cents: Money | None = None
    care_needs: Text | None = None
    timing: Text | None = None
    source_ref: Text
    contact_preference: Literal["email", "phone", "none"] = "none"
    attention: Literal["routine", "urgent", "human_request"] = "routine"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return check_email(value)

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        return check_phone(value)


class ReferralPatch(Input):
    expected_version: Annotated[StrictInt, Field(ge=1)]
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None
    email: Annotated[str, Field(max_length=254)] | None = None
    responsible_contact: Text | None = None
    location: Text | None = None
    budget_cents: Money | None = None
    care_needs: Text | None = None
    timing: Text | None = None
    source_ref: Text | None = None
    contact_preference: Literal["email", "phone", "none"] | None = None
    attention: Literal["routine", "urgent", "human_request"] | None = None


class Transition(Input):
    status: Literal["Qualified", "Touring"]
    human_confirmed: Literal[True]


class ContactEvent(Input):
    event: Literal["stop", "decline", "reply", "booking"]
    note: Annotated[str, Field(max_length=2000)] = ""


class Draft(Input):
    reason: Literal["incomplete", "no_booking", "missed_tour", "completed_tour", "planning"]
    body: Text


Name = Annotated[str, Field(min_length=1, max_length=200)]
ContractStatus = Literal["not_contracted", "in_progress", "contracted"]


class Community(Input):
    name: Name
    city: Text
    services: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=50)] = []
    licensed_beds: Annotated[StrictInt, Field(ge=0, le=10000)] | None = None
    source_url: HttpUrl
    observed_at: AwareDatetime
    category: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    miles_from_office: Annotated[float, Field(ge=0, le=500)] | None = None
    contact_name: Name | None = None
    contact_email: Annotated[str, Field(max_length=254)] | None = None
    contact_phone: Annotated[str, Field(max_length=40)] | None = None

    @field_validator("contact_email")
    @classmethod
    def valid_contact_email(cls, value):
        return check_email(value)

    @field_validator("contact_phone")
    @classmethod
    def valid_contact_phone(cls, value):
        return check_phone(value)


class ContractUpdate(Input):
    """The owner records where a community relationship stands; the agreement itself stays external."""

    status: ContractStatus
    agreement_ref: Text | None = None
    human_confirmed: Literal[True]

    @model_validator(mode="after")
    def contracted_needs_reference(self):
        if self.status == "contracted" and not self.agreement_ref:
            raise ValueError("a contracted community needs the signed agreement reference")
        return self


class Rating(Input):
    """The owner's own 1 to 3 star rating, only for communities they have contracted."""

    stars: Annotated[StrictInt, Field(ge=1, le=3)]
    note: Annotated[str, Field(max_length=500)] = ""


class TourPlan(Input):
    """One family, up to three communities, back to back; up to three candidate start times."""

    referral_id: Text
    community_ids: Annotated[list[Text], Field(min_length=1, max_length=3)]
    options: Annotated[list[AwareDatetime], Field(min_length=1, max_length=3)]
    tour_minutes: Annotated[StrictInt, Field(ge=15, le=180)] = 45
    supersedes_plan_id: Text | None = None
    travel_minutes: Annotated[StrictInt, Field(ge=0, le=120)] = 30

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.community_ids)) != len(self.community_ids):
            raise ValueError("each community can appear once in a tour plan")
        if len(set(self.options)) != len(self.options):
            raise ValueError("candidate start times must differ")
        return self


class TourResponse(Input):
    """An operator records a reply that actually arrived from one party."""

    party: Literal["family", "owner", "community"]
    community_id: Text | None = None
    response: Literal["accepts", "declines"]
    option: Annotated[StrictInt, Field(ge=1, le=3)] | None = None
    source_ref: Text
    note: Annotated[str, Field(max_length=1000)] = ""

    @model_validator(mode="after")
    def consistent(self):
        if (self.party == "community") != (self.community_id is not None):
            raise ValueError("community_id is required for a community reply and only for one")
        if self.response == "accepts" and self.option is None:
            raise ValueError("an acceptance names the option number it accepts")
        return self


class Availability(Input):
    vacancies: Annotated[StrictInt, Field(ge=0, le=10000)]
    verified_at: AwareDatetime
    expires_at: AwareDatetime
    source_ref: Text
    human_confirmed: Literal[True]

    @model_validator(mode="after")
    def bounded_lifetime(self):
        duration = (self.expires_at - self.verified_at).total_seconds()
        if not 0 < duration <= 7 * 86400:
            raise ValueError("availability must expire within 7 days of verification")
        return self


class Tour(Input):
    referral_id: Text
    community_id: Text
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def positive_duration(self):
        if not 0 < (self.end_at - self.start_at).total_seconds() <= 8 * 3600:
            raise ValueError("tour must last between 0 and 8 hours")
        return self


class Placement(Input):
    referral_id: Text
    community_id: Text
    move_in_date: date
    agreement_ref: Text
    agreement_signed_on: date
    fee_cents: Money
    terms: Literal["50_50_day30_day60"]
    refund_terms: Text


class LedgerEntry(Input):
    kind: Literal["invoiced", "collected"]
    day: Literal[30, 60]
    amount_cents: Money
    event_date: date
    receipt_ref: Text


def contacts(record):
    phone = "".join(filter(str.isdigit, record.get("phone") or ""))
    if len(phone) == 11 and phone.startswith("1"):
        phone = phone[1:]
    return {kind: value for kind, value in {"phone": phone, "email": (record.get("email") or "").casefold()}.items() if value}


def missing_info(record):
    missing = [key for key in ("responsible_contact", "location", "budget_cents", "care_needs", "timing") if not record.get(key)]
    if not contacts(record):
        missing.append("phone_or_email")
    preference = record.get("contact_preference", "none")
    if preference == "none":
        missing.append("contact_preference")
    elif not record.get(preference):
        missing.append(preference)
    return missing


def before_now(value: datetime, now: datetime):
    if value > now:
        raise ValueError("observation or verification cannot be in the future")
