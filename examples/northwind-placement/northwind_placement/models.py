"""Bounded request contracts. Facts stay unknown until an operator records them."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StrictInt, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Money = Annotated[StrictInt, Field(ge=1, le=100_000_000)]


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
        if value is not None and (value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value)):
            raise ValueError("email must contain one @ and no whitespace")
        return value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        if value is not None and (not 7 <= len("".join(filter(str.isdigit, value))) <= 15 or any(c not in "+()- .0123456789" for c in value)):
            raise ValueError("phone must contain 7 to 15 digits")
        return value


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


class Community(Input):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    city: Text
    services: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=50)] = []
    licensed_beds: Annotated[StrictInt, Field(ge=0, le=10000)] | None = None
    source_url: HttpUrl
    observed_at: AwareDatetime


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
