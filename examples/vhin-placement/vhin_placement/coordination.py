"""Three-party tour coordination: itineraries, unsent drafts and a tentative calendar file.

Pure functions. Nothing here sends, books or calls a provider. Drafts carry no
health details, fees or private ratings, and use placeholders for anything that
is not a verified record fact.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def itinerary(start: datetime, communities: list[dict], tour_minutes: int, travel_minutes: int) -> list[dict]:
    stops, cursor = [], start
    for community in communities:
        end = cursor + timedelta(minutes=tour_minutes)
        stops.append({"community_id": community["id"], "community_name": community["name"], "start_at": cursor.isoformat(), "end_at": end.isoformat()})
        cursor = end + timedelta(minutes=travel_minutes)
    return stops


def clock(value: str) -> str:
    moment = datetime.fromisoformat(value).astimezone(ET)
    return moment.strftime("%-I:%M %p").replace(":00 ", " ")


def day(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(ET).strftime("%A, %B %-d")


def first_name(referral: dict) -> str:
    contact = referral.get("responsible_contact") or referral.get("name") or ""
    return contact.split()[0] if contact.split() else "[first name]"


def option_lines(options: list[dict]) -> list[str]:
    lines = []
    for number, option in enumerate(options, 1):
        stops = option["stops"]
        visits = "; ".join(f"{stop['community_name']} at {clock(stop['start_at'])}" for stop in stops)
        lines.append(f"Option {number}: {day(stops[0]['start_at'])}: {visits}")
    return lines


def family_drafts(referral: dict, options: list[dict]) -> dict:
    name = first_name(referral)
    lines = option_lines(options)
    count = len(options[0]["stops"])
    homes = "community" if count == 1 else f"{count} communities"
    email = "\n".join(
        [
            f"Hi {name},",
            "",
            f"I'd like to set up visits for you at {homes} that fit what you told me. "
            "I'll meet you at each one so you can see the place, meet the team and ask anything.",
            "",
            *lines,
            "",
            "Which option works best? If none of these fit, send me a couple of times that do and I'll rework it.",
            "",
            "[VHIN Cares connection line for Justin to approve]",
            "",
            "Justin",
        ]
    )
    short = " / ".join(f"{n}) {day(o['stops'][0]['start_at']).split(', ')[1]} {clock(o['stops'][0]['start_at'])}" for n, o in enumerate(options, 1))
    text = f"Hi {name}, it's Justin. I can take you to see {homes} back to back: {short}. Reply with the option number that works, or a better time."
    return {"family_email": email, "family_text": text}


def community_drafts(community: dict, options: list[dict]) -> dict:
    greeting = community.get("contact_name") or "[community contact]"
    slots = []
    for number, option in enumerate(options, 1):
        stop = next(s for s in option["stops"] if s["community_id"] == community["id"])
        slots.append(f"Option {number}: {day(stop['start_at'])} at {clock(stop['start_at'])} to {clock(stop['end_at'])}")
    email = "\n".join(
        [
            f"Hi {greeting},",
            "",
            f"I'm working with a family who would like to tour {community['name']}. Could you host a tour at one of these times?",
            "",
            *slots,
            "",
            "Please let me know which works, and whether you currently have private or semi-private openings so I can set the right expectations.",
            "",
            "Justin",
        ]
    )
    text = f"Hi {greeting}, it's Justin. Could {community['name']} host a family tour? " + "; ".join(slots) + ". Which works?"
    return {"email": email, "text": text, "to_email": community.get("contact_email"), "to_phone": community.get("contact_phone")}


def justin_summary(referral: dict, options: list[dict], blocked: bool) -> str:
    lines = [f"Tour plan for case {referral['id'][:8]} ({referral.get('location') or 'area not recorded'})", *option_lines(options)]
    lines.append("Next: approve and send the drafts yourself, then record each reply here. Nothing has been sent or booked.")
    if blocked:
        lines.append("The family has a stop or pause on record or no usable contact preference, so no family draft was prepared.")
    return "\n".join(lines)


def escape_ics(text: str) -> str:
    text = "".join(" " if ord(c) < 32 and c != "\n" else c for c in text.replace("\r\n", "\n").replace("\r", "\n"))
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    """RFC 5545 line folding at 75 octets."""
    out, current = [], ""
    for char in line:
        if len((current + char).encode()) > 75:
            out.append(current)
            current = " " + char
        else:
            current += char
    return "\r\n".join(out + [current])


def tentative_calendar(plan_id: str, option_number: int, stops: list[dict], stamp: datetime) -> str:
    """An importable calendar file for Justin. TENTATIVE, no family names or health details."""

    def utc(value: str) -> str:
        return datetime.fromisoformat(value).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    events = []
    for index, stop in enumerate(stops):
        events += [
            "BEGIN:VEVENT",
            f"UID:{plan_id}-{option_number}-{index}@vhin-placement",
            f"DTSTAMP:{utc(stamp.isoformat())}",
            f"DTSTART:{utc(stop['start_at'])}",
            f"DTEND:{utc(stop['end_at'])}",
            f"SUMMARY:{escape_ics('Family tour: ' + stop['community_name'])}",
            "DESCRIPTION:" + escape_ics(f"Tentative. Plan {plan_id[:8]} option {option_number}. Confirm family and community before treating this as booked."),
            "STATUS:TENTATIVE",
            "END:VEVENT",
        ]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//VHIN placement//tour plan//EN", "METHOD:PUBLISH", *events, "END:VCALENDAR"]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
