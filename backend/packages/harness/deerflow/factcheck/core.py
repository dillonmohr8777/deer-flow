"""Deterministic fact-checker for outbound drafts (client email, Slack post, report copy).

Extracts numeric/date/source claims from a draft, maps each to evidence available
in the run, and returns a verdict per claim:

- ``supported``     value found in evidence (pointer attached)
- ``contradicted``  evidence says otherwise (wrong value, wrong scope/platform,
                    missing data stated as 0, improvement direction flipped)
- ``unsupported``   no evidence for it (e.g. an unsourced "55% CTR")
- ``unverifiable``  ambiguous; an optional ``judge`` callable may settle it

Gate: any contradicted claim -> ``block``; else any unsupported/unverifiable -> ``flag``
(surface to Dillon); else ``pass``. Pure functions, no IO. The only model call is the
optional ``judge`` hook, used for ambiguous claims only.

Rules baked in: missing data is "unavailable", never 0; improvement claims
("up 12%") need before/after values from one evidence source; scope labels
("Reddit Ads") must match the evidence's actual source.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

SUPPORTED, CONTRADICTED, UNSUPPORTED, UNVERIFIABLE = "supported", "contradicted", "unsupported", "unverifiable"
_MAX_EVIDENCE_CHARS = 50_000
_MAX_NUMS_PER_EVIDENCE = 60  # bounds the before/after pair scan
_WINDOW = 60

_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?\b", re.I)
_MONEY = re.compile(r"\$\s?(\d+(?:,\d{3})*(?:\.\d+)?)([kKmM]\b)?")
_PCT = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)\s?(?:%|percent\b)")
_PLAIN = re.compile(r"(?<![\w.$])(\d+(?:,\d{3})*(?:\.\d+)?)([kKmM]\b)?(?![\w.]*\d)")
_SCALE = {"k": 1e3, "m": 1e6}

_UP = re.compile(r"\b(up|increas\w*|improv\w*|grew|grow\w*|rose|rise\w*|higher|lift\w*|boost\w*|gain\w*|jump\w*)\b", re.I)
_DOWN = re.compile(r"\b(down|decreas\w*|declin\w*|drop\w*|fell|fall\w*|lower|reduc\w*|cut|dip\w*|slump\w*)\b", re.I)
_MISSING = re.compile(r"\b(unavailable|n/?a|null|none|missing|undefined|not available|no data|not tracked)\b", re.I)
_SOURCE = re.compile(r"\b(?i:according to|per|source:|data from|via)\s+(?:the\s+)?([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})")

_SCOPE_ALIASES = {
    "google ads": ("google ads", "adwords", "google_ads"),
    "meta ads": ("meta ads", "facebook ads", "instagram ads", "meta_ads", "facebook_ads"),
    "reddit ads": ("reddit ads", "reddit_ads"),
    "tiktok ads": ("tiktok ads", "tiktok_ads"),
    "linkedin ads": ("linkedin ads", "linkedin_ads"),
    "microsoft ads": ("microsoft ads", "bing ads", "microsoft_ads", "bing_ads"),
    "ga4": ("ga4", "google analytics"),
    "search console": ("search console", "gsc", "search_console"),
    "gbp": ("gbp", "google business profile", "google_business_profile"),
    "email": ("mailchimp", "klaviyo", "brevo"),
}
_STOP = set(
    "a an the of in on at to for from by with and or is are was were be been it its this that these those we our you your "
    "as per than over under about up down increase increased decrease decreased improved grew rose fell dropped from last "
    "week month year days day total more less approximately around nearly just only also now".split()
)


@dataclass
class Evidence:
    source: str
    text: str


@dataclass
class _Num:
    kind: str  # money | pct | plain | date
    value: object  # float, or (month, day, year|None) for dates
    tol: float
    raw: str
    start: int
    end: int


@dataclass
class Claim:
    id: int
    text: str
    raw: str
    kind: str
    verdict: str = UNSUPPORTED
    reason: str = ""
    evidence: str | None = None
    conflicting: str | None = None


@dataclass
class FactCheckReport:
    claims: list[Claim] = field(default_factory=list)

    @property
    def gate(self) -> str:
        verdicts = {c.verdict for c in self.claims}
        if CONTRADICTED in verdicts:
            return "block"
        return "flag" if verdicts & {UNSUPPORTED, UNVERIFIABLE} else "pass"

    @property
    def blocked(self) -> bool:
        return self.gate == "block"

    def to_dict(self) -> dict:
        counts = {v: sum(c.verdict == v for c in self.claims) for v in (SUPPORTED, CONTRADICTED, UNSUPPORTED, UNVERIFIABLE)}
        return {"gate": self.gate, "counts": counts, "claims": [asdict(c) for c in self.claims]}


def draft_text(title: str, payload: object) -> str:
    """The exact text a reviewer approves: the title plus every string payload value."""
    return "\n".join(v for v in (title, *payload.values()) if isinstance(v, str)) if isinstance(payload, dict) else title


def _num(s: str, suffix: str | None = None) -> tuple[float, float]:
    """Parse '1,234.5' (+ optional k/m) -> (value, rounding tolerance)."""
    s = s.replace(",", "")
    decimals = len(s.split(".")[1]) if "." in s else 0
    scale = _SCALE.get((suffix or "").lower(), 1)
    return float(s) * scale, 0.5 * 10**-decimals * scale + 1e-9


def _scan(text: str) -> list[_Num]:
    """Find dates, money, percentages, then plain numbers; earlier kinds mask later ones."""
    out: list[_Num] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(m.start() < e and s < m.end() for s, e in taken)

    def add(m: re.Match, kind: str, value: object, tol: float = 0.0) -> None:
        out.append(_Num(kind, value, tol, m.group(0), m.start(), m.end()))
        taken.append((m.start(), m.end()))

    for m in _ISO_DATE.finditer(text):
        add(m, "date", (int(m[2]), int(m[3]), int(m[1])))
    for m in _TEXT_DATE.finditer(text):
        if free(m):
            add(m, "date", (_MONTHS[m[1].lower()[:3]], int(m[2]), int(m[3]) if m[3] else None))
    for pat, kind in ((_MONEY, "money"), (_PCT, "pct"), (_PLAIN, "plain")):
        for m in pat.finditer(text):
            if free(m):
                v, tol = _num(m[1], m[2] if m.lastindex and m.lastindex >= 2 else None)
                add(m, kind, v, tol)
    return sorted(out, key=lambda n: n.start)


def _scopes(text: str) -> set[str]:
    low = text.lower()
    return {canon for canon, aliases in _SCOPE_ALIASES.items() if any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", low) for a in aliases)}


def _labels(sentence: str, n: _Num) -> set[str]:
    """Metric words next to the number, e.g. '55% CTR' -> {'ctr'}; platform words excluded."""
    scoped = {w for a in _SCOPE_ALIASES.values() for alias in a for w in alias.replace("_", " ").split()}
    before = re.findall(r"[a-z0-9]+", sentence[: n.start].lower())[-3:]
    after = re.findall(r"[a-z0-9]+", sentence[n.end :].lower())[:3]
    return {w.rstrip("s") if len(w) > 3 else w for w in before + after if w not in _STOP and w not in scoped and not w.isdigit()}


_SEGMENT_BREAK = re.compile(r"[;\n{}|]|(?<!\d),|,(?!\d)")


def _near(ev: Evidence, n: _Num) -> str:
    """The label-bearing segment around an evidence number: bounded by delimiters (',', ';', newline, braces)."""
    lo = max((m.end() for m in _SEGMENT_BREAK.finditer(ev.text, max(0, n.start - _WINDOW), n.start)), default=max(0, n.start - _WINDOW))
    hi = next((m.start() for m in _SEGMENT_BREAK.finditer(ev.text, n.end, n.end + _WINDOW)), n.end + _WINDOW)
    return ev.text[lo:hi].lower().replace("_", " ")


def _label_hit(labels: set[str], context: str) -> bool:
    return any(lab in context for lab in labels)


def _equal(claim: _Num, ev: _Num) -> bool:
    if "date" in (claim.kind, ev.kind):
        if claim.kind != ev.kind:
            return False
        (cm, cd, cy), (em, ed, ey) = claim.value, ev.value  # type: ignore[misc]
        return (cm, cd) == (em, ed) and (cy is None or ey is None or cy == ey)
    if claim.kind == "pct" and ev.kind == "plain" and abs(ev.value * 100 - claim.value) <= claim.tol:  # ratio 0.032 == 3.2%
        return True
    # raw evidence numbers (JSON, CSV) carry no unit, so a plain evidence number can satisfy any claim kind
    return abs(ev.value - claim.value) <= claim.tol and (claim.kind == ev.kind or ev.kind == "plain")


def _pointer(ev: Evidence, n: _Num) -> str:
    snip = ev.text[max(0, n.start - 30) : n.end + 30].replace("\n", " ").strip()
    return f"{ev.source}: ...{snip}..."


def _improvement(sentence: str, n: _Num) -> int:
    """+1 / -1 for an 'up X%' / 'down X%' claim (nearest direction word wins), else 0."""
    best, direction = 41, 0
    for pat, d in ((_UP, 1), (_DOWN, -1)):
        for m in pat.finditer(sentence):
            dist = n.start - m.end() if m.end() <= n.start else m.start() - n.end
            if 0 <= dist < best:
                best, direction = dist, d
    return direction


def _pair_check(claim: _Num, direction: int, labels: set[str], evs: list[tuple[Evidence, list[_Num]]]) -> tuple[str, str, str | None] | None:
    """Look for before/after values in ONE evidence item. Returns (verdict, pointer, conflicting)."""
    for ev, nums in evs:
        cand = [x for x in nums if x.kind in ("plain", "money")]
        scoped = [x for x in cand if _label_hit(labels, _near(ev, x))] if labels else []
        cand = (scoped if len(scoped) >= 2 else cand)[:_MAX_NUMS_PER_EVIDENCE]
        for a in cand:
            for b in cand:
                if a is b or a.kind != b.kind or not a.value:
                    continue
                change = (b.value - a.value) / a.value * 100
                if abs(abs(change) - claim.value) <= max(claim.tol, 0.5):
                    ptr = f"{ev.source}: before {a.raw} -> after {b.raw}"
                    if (change > 0) == (direction > 0):
                        return SUPPORTED, ptr, None
                    return CONTRADICTED, ptr, f"{change:+.1f}%"
    return None


def verify_draft(draft: str, evidence: list[Evidence], judge: Callable[[str, list[str]], str | None] | None = None) -> FactCheckReport:
    """Check every numeric/date/named-source claim in ``draft`` against ``evidence``."""
    evs = [(e, _scan(e.text)) for e in (Evidence(e.source, e.text[:_MAX_EVIDENCE_CHARS]) for e in evidence)]
    all_text_missing = [e for e, _ in evs if _MISSING.search(e.text)]
    report = FactCheckReport()

    for sentence in (s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", draft)):
        if not sentence:
            continue
        clauses = [m.span() for m in re.finditer(r"(?:(?! and | but )(?:(?<=\d),(?=\d)|[^;,]))+", sentence)]
        for n in _scan(sentence):
            sent_scopes = _scopes(next((sentence[a:b] for a, b in clauses if a <= n.start < b), sentence))  # scope = the number's own clause
            c = Claim(len(report.claims) + 1, sentence, n.raw, n.kind)
            report.claims.append(c)
            labels = _labels(sentence, n)
            direction = _improvement(sentence, n) if n.kind == "pct" else 0

            if direction:
                r = _pair_check(n, direction, labels, evs)
                if r:
                    c.verdict, c.evidence, c.conflicting = r
                    c.reason = "before/after values from the same source" if r[0] == SUPPORTED else "direction/magnitude contradicts the source's before/after values"
                else:
                    c.reason = "improvement claim needs before/after values from the same source"
                continue

            strong, weak = [], []
            for ev, nums in evs:
                for x in nums:
                    if _equal(n, x):
                        (strong if not labels or _label_hit(labels, _near(ev, x)) else weak).append((ev, x))
            if strong:
                ev_scopes = lambda ev: _scopes(ev.source + " " + ev.text)  # noqa: E731
                fit = [(ev, x) for ev, x in strong if not sent_scopes or sent_scopes & ev_scopes(ev)]
                if fit:
                    c.verdict, c.evidence, c.reason = SUPPORTED, _pointer(*fit[0]), "value found in evidence"
                elif all(ev_scopes(ev) for ev, _ in strong):
                    seen = sorted({s for ev, _ in strong for s in ev_scopes(ev)})
                    c.verdict, c.evidence, c.conflicting = CONTRADICTED, _pointer(*strong[0]), ", ".join(seen)
                    c.reason = f"scope mismatch: draft says {', '.join(sorted(sent_scopes))}, evidence is {', '.join(seen)}"
                else:
                    c.reason = f"scope unconfirmed: draft says {', '.join(sorted(sent_scopes))} but the evidence names no platform"
                continue
            if weak:
                c.verdict, c.reason = UNVERIFIABLE, "value appears in evidence but not next to the claimed metric"
                if judge and (j := judge(sentence, [_pointer(ev, x) for ev, x in weak[:3]])) in (SUPPORTED, UNSUPPORTED, CONTRADICTED):
                    c.verdict, c.reason, c.evidence = j, "model-judged ambiguous claim", _pointer(*weak[0])
                continue
            if n.kind == "date":
                c.reason = "date not found in evidence"
                continue

            if n.value == 0 and any(_MISSING.search(ev.text[max(0, x - 80) : x + 80]) for ev in all_text_missing for x in ([m.start() for lab in labels for m in re.finditer(re.escape(lab), ev.text.lower())] or [0])):
                c.verdict, c.conflicting = CONTRADICTED, "unavailable"
                c.reason = "evidence marks this data unavailable/null; missing data is never 0"
                continue
            conflicts = [(ev, x) for ev, nums in evs for x in nums if labels and x.kind != "date" and _label_hit(labels, _near(ev, x)) and (x.kind == n.kind or "plain" in (x.kind, n.kind))]
            if conflicts:
                ev, x = conflicts[0]
                c.verdict, c.evidence, c.conflicting = CONTRADICTED, _pointer(ev, x), x.raw
                c.reason = f"evidence shows {x.raw} for this metric, draft says {n.raw}"
            else:
                c.reason = "no evidence for this number in the run" if evs else "no evidence available"

    for m in _SOURCE.finditer(draft):
        name = m[1].strip()
        c = Claim(len(report.claims) + 1, m.group(0), name, "source")
        hit = next((e for e, _ in evs if name.lower() in (e.source + " " + e.text).lower().replace("_", " ")), None)
        c.verdict, c.reason, c.evidence = (SUPPORTED, "named source present in evidence", hit.source) if hit else (UNSUPPORTED, "named source not among run evidence", None)
        report.claims.append(c)
    return report
