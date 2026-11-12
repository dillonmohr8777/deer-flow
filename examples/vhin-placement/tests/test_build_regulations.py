"""Citation fidelity of the Florida corpus parsers, on small verbatim excerpts of the official sources.

The fixtures are public law copied from the publishers (see the first line of each file); they run offline and
on any platform because the Word-to-text step (``word_doc_text``) is kept apart from the FAC text parser.
"""

import html
import importlib.util
import json
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "fl"
SPEC = importlib.util.spec_from_file_location("build_regulations", PACKAGE / "scripts" / "build_regulations.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
SOURCES = {s["id"]: s for s in json.loads((PACKAGE / "vhin_placement" / "regulations_data" / "FL" / "sources.json").read_text())["sources"]}


def squash(text: str) -> str:
    return "".join(text.split())


def test_fac_text_units_carry_the_official_rule_numbers():
    text = (FIXTURES / "fac-59A-36-excerpt.txt").read_text(encoding="utf-8")
    units = builder.parse_fac_text(SOURCES["fac-59A-36"], text, {"effective_dates": {"59A-36.006": "11/27/2025"}})
    assert [u["citation"] for u in units] == [
        "Rule 59A-36.006(1), F.A.C.",
        "Rule 59A-36.006(1)(a), F.A.C.",
        "Rule 59A-36.006(1)(a)1., F.A.C.",
        "Rule 59A-36.006(1)(a)4., F.A.C.",
        "Rule 59A-36.006(1)(a)10., F.A.C.",
        "Rule 59A-36.006(1)(a)10.a., F.A.C.",
        "Rule 59A-36.006(1)(a)10.a.(I), F.A.C.",
        "Rule 59A-36.006(1)(a)10.a.(II), F.A.C.",
        "Rule 59A-36.006(1)(a)10.b., F.A.C.",
        "Rule 59A-36.006(1)(a)11., F.A.C.",
        "Rule 59A-36.006(1)(a)11.a., F.A.C.",
        "Rule 59A-36.006(1)(a)11.b., F.A.C.",
        "Rule 59A-36.006(5), F.A.C.",
        "Rule 59A-36.010(3), F.A.C.",
        "Rule 59A-36.010(3)(a), F.A.C.",
        "Rule 59A-36.010(3)(a)1., F.A.C.",
        "Rule 59A-36.010(3)(a)2., F.A.C.",
        "Rule 59A-36.025(1), F.A.C.",
        "Rule 59A-36.025(1)(a), F.A.C.",
        "Rule 59A-36.025(1)(a)1., F.A.C.",
        "Rule 59A-36.025(1)(a)3., F.A.C.",
        "Rule 59A-36.025(1)(a)3.a., F.A.C.",
    ]
    by = {u["citation"]: u for u in units}
    # The label is stripped and the rest of the line is the unit, word for word.
    transfer = "Be able to transfer, with assistance if necessary. The assistance of more than one person is permitted."
    assert by["Rule 59A-36.006(1)(a)4., F.A.C."]["text"] == transfer
    assert by["Rule 59A-36.006(1)(a)11.b., F.A.C."]["text"] == "Assistance with tube feeding,"
    # Unlabelled lines (here the flattened staffing table) stay with the unit above them, in source order.
    assert by["Rule 59A-36.010(3)(a)1., F.A.C."]["text"] == (
        "Facilities must maintain the following minimum staff hours per week: Number of Residents, Day Care Participants, and Respite Care Residents "
        "Staff Hours/Week 0-5 168 6-15 212 16- 25 253 26-35 294 36-45 335 46-55 375 56- 65 416 66-75 457 76-85 498 86-95 539 "
        "For every 20 total combined residents, day care participants, and respite care residents over 95 add 42 staff hours per week."
    )
    # A repealed rule (history only) yields no units; the table of contents above the body is not law text.
    assert not any(u["section"] == "59A-36.001" for u in units)
    # Each rule's history line, title, official URL and effective date attach to that rule's units only.
    assert all(u["history"].startswith("Rulemaking Authority 429.07, 429.41 FS.") for u in units if u["section"] == "59A-36.006")
    assert all(u["history"].startswith("Rulemaking Authority 429.41, FS.") for u in units if u["section"] == "59A-36.025")
    assert by["Rule 59A-36.025(1), F.A.C."]["section_title"] == "Emergency Environmental Control for Assisted Living Facilities"  # Word field code removed
    assert by["Rule 59A-36.006(5), F.A.C."]["url"] == "https://www.flrules.org/gateway/ruleNo.asp?id=59A-36.006"
    assert by["Rule 59A-36.006(1), F.A.C."]["effective"] == "11/27/2025" and by["Rule 59A-36.010(3), F.A.C."]["effective"] is None
    # Nothing is invented: every unit's text appears in the source.
    source = squash(text)
    assert all(squash(u["text"]) in source for u in units)


def test_statute_html_units_carry_the_official_section_numbers():
    raw = (FIXTURES / "fs-0429.26-excerpt.html").read_bytes()
    url = "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0400-0499/0429/Sections/0429.26.html"
    units = builder.parse_fl_statute_section(SOURCES["fs-429-part-1"], raw, {"url": url})
    # "(d)1." is one Number span in the source: paragraph (d) has no text of its own, so its first unit is (1)(d)1.
    assert [u["citation"] for u in units] == [
        "Section 429.26(1), F.S.",
        "Section 429.26(1)(a), F.S.",
        "Section 429.26(1)(d)1., F.S.",
        "Section 429.26(1)(d)1.a., F.S.",
        "Section 429.26(1)(d)1.b., F.S.",
        "Section 429.26(1)(d)1.c., F.S.",
        "Section 429.26(1)(d)2., F.S.",
        "Section 429.26(2), F.S.",
    ]
    by = {u["citation"]: u for u in units}
    assert {u["section"] for u in units} == {"429.26"}
    assert units[0]["section_title"] == "Appropriateness of placements; examinations of residents"
    assert by["Section 429.26(1)(d)1.a., F.S."]["text"] == "Move, turn, or reposition without total physical assistance;"
    assert by["Section 429.26(1)(d)1., F.S."]["text"].startswith("Except for a resident who is receiving hospice services")
    assert all(u["url"] == url and u["effective"] == "2026 Florida Statutes" for u in units)
    # The editorial note ("Former s. 400.426.") and the history are not law text; the history is kept as metadata.
    assert not any("400.426" in u["text"] or "ch. 80-198" in u["text"] for u in units)
    assert all(u["history"].startswith("History.") and "ch. 80-198" in u["history"] for u in units)
    # Word for word, including the text of inline cross-reference links.
    source = squash(html.unescape(re.sub(r"<[^>]+>", "", raw.decode("utf-8"))))
    assert all(squash(u["text"]) in source for u in units)
