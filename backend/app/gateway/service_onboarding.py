"""Turn a pasted contract scope into a work plan and recurring task schedules.

Deterministic and offline: no model call, no network, no writes. The same text
always gives the same plan, so a seller can preview it on the onboarding call
and apply exactly what they saw.

What it reads: one deliverable per line (bullets, numbers or plain lines that
name a cadence such as "4 blog posts per month" or "weekly social posts").
What it never keeps: money. Currency amounts are cut from every title, and
billing lines (fees, invoices, payment terms) are skipped, so no price, budget
or revenue figure from a contract ends up in a task or the stored plan.

Cadence to schedule (09:00 in the workspace timezone):

* daily -> every day
* N per week -> N weekdays (2: Mon/Thu, 3: Mon/Wed/Fri, 5: Mon-Fri)
* weekly, every week, 4 per month -> Monday
* twice a month, biweekly, every two weeks, 2 per month -> the 1st and 15th
* monthly, once a month -> the 1st
* quarterly -> the 1st of January, April, July and October
* no cadence -> a one-off plan item with no scheduled task

"Biweekly" is read as every two weeks (twice a month), never twice a week.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

MAX_CONTRACT_CHARS = 50_000
MAX_PLAN_ITEMS = 40
MAX_TITLE_CHARS = 120

#: Cadence id -> (plain label, cron). ``None`` cron is a one-off item.
CADENCES: dict[str, tuple[str, str | None]] = {
    "daily": ("Every day", "0 9 * * *"),
    "weekdays": ("Every weekday", "0 9 * * 1-5"),
    "6_per_week": ("6 times a week", "0 9 * * 1-6"),
    "4_per_week": ("4 times a week", "0 9 * * 1,2,4,5"),
    "3_per_week": ("3 times a week", "0 9 * * 1,3,5"),
    "2_per_week": ("Twice a week", "0 9 * * 1,4"),
    "weekly": ("Every week", "0 9 * * 1"),
    "3_per_month": ("3 times a month", "0 9 1,11,21 * *"),
    "twice_monthly": ("Twice a month", "0 9 1,15 * *"),
    "monthly": ("Every month", "0 9 1 * *"),
    "quarterly": ("Every quarter", "0 9 1 1,4,7,10 *"),
    "once": ("One time", None),
}

#: Kind id -> plain label. Matched in this order, first hit wins.
KINDS: dict[str, str] = {
    "reporting": "Reporting",
    "ads": "Ads",
    "email": "Email",
    "social": "Social",
    "seo": "SEO and content",
    "website": "Website",
    "other": "Other",
}

_KIND_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("reporting", re.compile(r"\b(report|reporting|reports|dashboard|analytics review|performance review)\b")),
    ("ads", re.compile(r"\b(ads?|ppc|paid search|paid social|campaigns?|google ads|meta ads|adwords)\b")),
    ("email", re.compile(r"\b(emails?|newsletters?|e-?blasts?|drip)\b")),
    ("social", re.compile(r"\b(social|instagram|facebook|linkedin|tiktok|x\.com|twitter|reels?|stories)\b")),
    ("seo", re.compile(r"\b(seo|blogs?|articles?|keywords?|backlinks?|content|press releases?|aeo|geo)\b")),
    ("website", re.compile(r"\b(website|web ?site|landing pages?|web pages?|site updates?|pages?)\b")),
)

_ADS = _KIND_WORDS[1][1]

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
}
#: A count ("4", "4x", "four"), a few words of what is counted, then "per".
#: "4 blog posts per month", "3x per week", "five posts a week", "8/mo".
_N = r"\b(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")(?:x\b|\b)"
_PER = r"(?:\s+[a-z][\w'&-]*){0,3}?(?:\s+(?:per|a|an|each|every)\s+|\s*/\s*)"

_PER_WEEK = re.compile(_N + _PER + r"(?:week|wk)\b|" + _N + r"\s*x?\s*weekly\b")
_PER_MONTH = re.compile(_N + _PER + r"(?:month|mo)\b|" + _N + r"\s*x?\s*monthly\b")
_DAILY = re.compile(r"\b(daily|every day|each day|per day|a day)\b")
_TWICE_WEEK = re.compile(r"\b(twice|two times)\s*(a|per|each)\s*week\b")
_TWICE_MONTH = re.compile(r"\b(twice|two times)\s*(a|per|each)\s*month\b|\bbi-?weekly\b|\bevery (other|two|2) weeks?\b|\bsemi-?monthly\b|\bfortnightly\b")
_WEEKLY = re.compile(r"\b(weekly|every week|each week|per week|a week|once a week)\b")
_MONTHLY = re.compile(r"\b(monthly|every month|each month|per month|a month|once a month|/mo)\b")
_QUARTERLY = re.compile(r"\b(quarterly|every quarter|each quarter|per quarter|every (three|3) months)\b")

_BULLET = re.compile(r"^\s*(?:[-*•·▪●–—]+|\(?\d{1,3}[.)]|\(?[a-z][.)])\s+", re.IGNORECASE)
_MONEY = re.compile(r"(?:[$£€]\s?\d[\d,]*(?:\.\d+)?\s*(?:k|m)?(?:\s*(?:/|per)\s*(?:mo|month|week|year|yr))?|\b\d[\d,]*(?:\.\d+)?\s*(?:usd|dollars)\b)", re.IGNORECASE)
_BILLING = re.compile(r"\b(fee|fees|invoice|invoiced|invoicing|payment|payments|pricing|price|retainer|billing|billed|net ?\d+|deposit|refund|late charge|total cost|subtotal|tax)\b", re.IGNORECASE)
_LEGAL = re.compile(r"\b(terminat|cancel|indemnif|liabilit|governing law|confidential|warrant|agreement is|hereby|whereas|signature|signed)\w*", re.IGNORECASE)


@dataclass(frozen=True)
class PlanItem:
    title: str
    kind: str
    kind_label: str
    cadence: str
    cadence_label: str
    cron: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def contract_digest(text: str) -> str:
    """SHA-256 of the pasted text. The plan stores this, never the text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count(raw: str) -> int | None:
    raw = raw.lower()
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORDS.get(raw)


def _first_count(match: re.Match[str]) -> int | None:
    for group in match.groups():
        if group:
            return _count(group)
    return None


def _per_week(n: int) -> str:
    if n <= 1:
        return "weekly"
    if n == 2:
        return "2_per_week"
    if n == 3:
        return "3_per_week"
    if n == 4:
        return "4_per_week"
    if n == 5:
        return "weekdays"
    if n == 6:
        return "6_per_week"
    return "daily"


def _per_month(n: int) -> str:
    if n <= 1:
        return "monthly"
    if n == 2:
        return "twice_monthly"
    if n == 3:
        return "3_per_month"
    if n == 4:
        return "weekly"
    if n <= 8:
        return "2_per_week"
    if n <= 12:
        return "3_per_week"
    if n <= 22:
        return "weekdays"
    return "daily"


def detect_cadence(line: str) -> str:
    """The cadence id for one line, ``"once"`` when it names none.

    Money is cut first, so "$1,500 per month" is a price, never a schedule.
    """
    text = _MONEY.sub(" ", line).lower()
    match = _PER_WEEK.search(text)
    if match and (n := _first_count(match)):
        return _per_week(n)
    match = _PER_MONTH.search(text)
    if match and (n := _first_count(match)):
        return _per_month(n)
    if _TWICE_WEEK.search(text):
        return "2_per_week"
    if _TWICE_MONTH.search(text):
        return "twice_monthly"
    if _DAILY.search(text):
        return "daily"
    if _QUARTERLY.search(text):
        return "quarterly"
    if _WEEKLY.search(text):
        return "weekly"
    if _MONTHLY.search(text):
        return "monthly"
    return "once"


def detect_kind(line: str) -> str:
    text = line.lower()
    for kind, pattern in _KIND_WORDS:
        if pattern.search(text):
            return kind
    return "other"


def clean_title(line: str) -> str:
    """Bullet, money and extra spaces removed; at most 120 characters."""
    title = _BULLET.sub("", line)
    title = _MONEY.sub("", title)
    title = re.sub(r"\(\s*\)", "", title)
    title = re.sub(r"\s+", " ", title).strip(" \t-:;,.")
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def make_item(title: str, cadence: str, kind: str | None = None) -> PlanItem:
    """One validated plan item. Raises ``ValueError`` on an unknown cadence or kind."""
    if cadence not in CADENCES:
        raise ValueError("Unknown cadence")
    resolved_kind = kind or detect_kind(title)
    if resolved_kind not in KINDS:
        raise ValueError("Unknown kind")
    cleaned = clean_title(title)
    if not cleaned:
        raise ValueError("Each plan item needs a name")
    label, cron = CADENCES[cadence]
    return PlanItem(title=cleaned, kind=resolved_kind, kind_label=KINDS[resolved_kind], cadence=cadence, cadence_label=label, cron=cron)


def parse_contract(text: str) -> list[PlanItem]:
    """Every deliverable line in *text*, in order, de-duplicated, at most 40.

    A line counts when it is a bullet or numbered line, or when it names a
    cadence. Billing and legal boilerplate lines are skipped.
    """
    items: list[PlanItem] = []
    seen: set[str] = set()
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if len(line) < 3:
            continue
        cadence = detect_cadence(line)
        if not _BULLET.match(raw) and cadence == "once":
            continue
        if _BILLING.search(line) and not _ADS.search(line.lower()):
            # A pure billing line. An ads line that mentions billing ("ad spend
            # billed separately") is still a deliverable; its amount is cut.
            continue
        if _LEGAL.search(line):
            continue
        title = clean_title(line)
        if len(title) < 3 or title.endswith(":") or title.lower() in seen:
            continue
        seen.add(title.lower())
        items.append(make_item(title, cadence))
        if len(items) >= MAX_PLAN_ITEMS:
            break
    return items


def task_prompt(item: PlanItem, *, workspace_name: str, tier: str | None) -> str:
    """Drafts-only instructions for one recurring task. Never publish or send."""
    if tier == "software":
        reviewer = "The client reviews every draft in their own inbox before anything is used."
    elif tier in {"am_assisted", "standard"}:
        reviewer = "The account manager reviews every draft in Approvals before anything is used."
    else:
        reviewer = "A person on the team reviews every draft before anything is used."
    return (
        f"Work plan item for {workspace_name}: {item.title} ({item.cadence_label.lower()}).\n"
        f"Draft this period's work for review. {reviewer}\n"
        "Do not publish, post, schedule, send or email anything, and do not contact anyone. "
        "If something you need is missing, list it in the draft instead of guessing."
    )


def check_in_prompt(*, workspace_name: str, seller_name: str) -> str:
    return (
        f"Monthly check-in prep for {workspace_name}.\n"
        f"Write {seller_name} a short private summary: what was drafted and approved last month, "
        "what is waiting on review, and two or three questions worth asking on the check-in call.\n"
        "This is for the team only. Do not contact the client, and do not publish, post, schedule or send anything."
    )
