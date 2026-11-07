"""Build a state regulation corpus from primary sources only.

Usage (network required, run by an operator, never by the Gateway):

    python examples/vhin-placement/scripts/build_regulations.py FL [--out DIR] [--mirror DIR]

Each state is described by ``vhin_placement/regulations_data/<STATE>/sources.json``.
A source names an official URL and a parser. The builder downloads every source,
records its SHA-256 and retrieval time, splits it into citable units (one unit per
numbered subsection, paragraph or subparagraph) and writes ``<out>/<STATE>/corpus.json``.
It also writes a small-page mirror under ``<mirror>/<STATE>/`` so a chat agent whose
page fetcher truncates long pages can still read every unit verbatim.

Both outputs are bulk data and stay out of Git (see ``.gitignore``). The defaults
write inside the package for local work; a deployment builds into its data mount
(``--out`` is what the Gateway reads through ``VHIN_REGULATIONS_DIR``; ``--mirror``
is published as static pages).

Adding a state (Ohio, Arizona, ...) means adding its ``sources.json`` plus, if its
publisher uses a new format, one parser function registered in ``PARSERS``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
DATA = PACKAGE / "vhin_placement" / "regulations_data"
MIRROR = PACKAGE / "regulations-mirror"
USER_AGENT = "Mozilla/5.0 (compatible; MomoBot regulation corpus builder)"
PAGE_LIMIT = 3400  # the chat agent's fetch tool keeps the first 4096 characters


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- FAC rule chapter


FAC_LEVELS = [
    (re.compile(r"^\((\d+)\)\s+"), "({})"),
    (re.compile(r"^\(([a-z]{1,2})\)\s+"), "({})"),
    (re.compile(r"^(\d+)\.\s+"), "{}."),
    (re.compile(r"^([a-z]{1,2})\.\s+"), "{}."),
    (re.compile(r"^\(([IVX]+)\)\s+"), "({})"),
]


def word_doc_text(data: bytes) -> str:
    """Convert the publisher's Word file with macOS textutil or LibreOffice."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source.doc"
        source.write_bytes(data)
        target = Path(tmp) / "source.txt"
        try:
            subprocess.run(["textutil", "-convert", "txt", "-output", str(target), str(source)], check=True, capture_output=True)
        except FileNotFoundError:
            subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text", "--outdir", tmp, str(source)], check=True, capture_output=True)
        return target.read_text(encoding="utf-8", errors="replace")


def clean(text: str) -> str:
    text = re.sub(r'HYPERLINK "[^"]*"(?: \\t "[^"]*")?', "", text)
    text = text.replace("‑", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_fac_chapter(source: dict, raw: bytes, meta: dict) -> list[dict]:
    """Split a Florida Administrative Code chapter into labelled units."""
    text = word_doc_text(raw)
    prefix = re.escape(source["chapter"])
    header = re.compile(rf"^({prefix}\.\d{{3}})\s+(.+?)\.?$")
    effective = meta.get("effective_dates", {})
    units: list[dict] = []
    section = title = None
    stack: list[str] = []
    seen_body = False
    for raw_line in text.splitlines():
        line = clean(raw_line)
        if not line:
            continue
        match = header.match(line)
        if match and "\t" not in raw_line:
            seen_body = True
            section, title = match.group(1), match.group(2).rstrip(".")
            stack = []
            if "(Repealed)" in title or title.endswith("Repealed"):
                section = None
            continue
        if not seen_body or section is None:
            continue
        if line.startswith("Rulemaking Authority") or line.startswith("Specific Authority"):
            for unit in units:
                if unit["section"] == section:
                    unit["history"] = line
            continue
        level, label, body, letter = None, "", line, ""
        for depth, (pattern, fmt) in enumerate(FAC_LEVELS):
            found = pattern.match(line)
            if found:
                level, label, body, letter = depth, fmt.format(found.group(1)), line[found.end() :], found.group(1)
                break
        if level is None:
            if units and units[-1]["section"] == section:
                units[-1]["text"] += " " + line
            else:
                units.append(fac_unit(source, section, title, [], line, effective))
            continue
        # A roman "(I)" only exists under a lettered subparagraph; otherwise it is a letter.
        if level == 4 and len(stack) < 4:
            level, label = 1, f"({letter.lower()})"
        stack = stack[:level] + [label]
        units.append(fac_unit(source, section, title, list(stack), body, effective))
    return units


def fac_unit(source, section, title, path, text, effective):
    label = "".join(path)
    return {
        "source_id": source["id"],
        "section": section,
        "section_title": title,
        "path": path,
        "citation": f"Rule {section}{label}, F.A.C.",
        "text": text,
        "url": source["section_url"].format(section=section),
        "effective": effective.get(section),
    }


def fac_effective_dates(index_html: str) -> dict:
    flat = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", index_html)))
    return {m.group(1): m.group(2) for m in re.finditer(r"(\d+[A-Z]-\d+\.\d{3}) .*? (\d{1,2}/\d{1,2}/\d{4})", flat)}


# ---------------------------------------------------------------- Florida Statutes


DEPTHS = {"Subsection": 1, "Paragraph": 2, "SubParagraph": 3, "SubSubParagraph": 4, "SubSubSubParagraph": 5}


class StatuteHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.divs: list[str] = []
        self.capture: str | None = None
        self.buffer = ""
        self.number = ""
        self.section = self.title = self.history = ""
        self.labels: dict[int, str] = {}
        self.units: list[tuple[list[str], str]] = []
        self.span_stack: list[str | None] = []

    def depth(self):
        return max([DEPTHS.get(c, 0) for c in self.divs] + [0])

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "") or ""
        if tag == "div":
            self.divs.append(classes.split()[0] if classes else "")
            if classes.startswith("History"):
                self.capture, self.buffer = "history", ""
        elif tag == "span":
            kind = None
            if "SectionNumber" in classes:
                kind = "section"
            elif "CatchlineText" in classes:
                kind = "title"
            elif classes.split()[:1] == ["Number"]:
                kind = "number"
            elif classes.split()[:1] == ["Text"]:
                kind = "text"
            self.span_stack.append(kind)
            if kind and self.capture != "history":
                self.capture, self.buffer = kind, ""

    def handle_endtag(self, tag):
        if tag == "div":
            closing = self.divs.pop() if self.divs else ""
            if closing.startswith("History") and self.capture == "history":
                self.history, self.capture = clean(self.buffer), None
        elif tag == "span":
            kind = self.span_stack.pop() if self.span_stack else None
            if kind and kind == self.capture:
                value = clean(self.buffer)
                self.capture = None
                if kind == "section":
                    self.section = value
                elif kind == "title":
                    self.title = value.rstrip(".")
                elif kind == "number":
                    self.number = value
                elif kind == "text":
                    self.emit(value)

    def handle_data(self, data):
        if self.capture:
            self.buffer += data

    def emit(self, text):
        if any(c.startswith("Note") for c in self.divs):
            return  # editorial notes such as "Former s. 400.402." are not law text
        depth = self.depth()
        tokens = re.findall(r"\([0-9A-Za-z]+\)|[0-9A-Za-z]+\.", self.number) if self.number else []
        for offset, token in enumerate(tokens):
            self.labels[depth - len(tokens) + 1 + offset] = token
        self.labels = {d: v for d, v in self.labels.items() if d <= depth}
        path = [self.labels[d] for d in sorted(self.labels) if d >= 1]
        if depth == 0:
            path = []
        self.units.append((path, text))
        self.number = ""


def parse_fl_statute_section(source: dict, raw: bytes, meta: dict) -> list[dict]:
    parser = StatuteHTML()
    parser.feed(raw.decode("utf-8", errors="replace"))
    section = parser.section.strip()
    units = []
    for path, text in parser.units:
        units.append(
            {
                "source_id": source["id"],
                "section": section,
                "section_title": parser.title,
                "path": path,
                "citation": f"Section {section}{''.join(path)}, F.S.",
                "text": text,
                "url": meta["url"],
                "effective": source.get("edition"),
                "history": parser.history,
            }
        )
    return units


PARSERS = {"fac_chapter_word": parse_fac_chapter, "fl_statute_section_html": parse_fl_statute_section}


# ---------------------------------------------------------------- build


def build(state: str, out: Path = DATA, mirror: Path = MIRROR) -> dict:
    config = json.loads((DATA / state / "sources.json").read_text())
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    documents, units = [], []
    for source in config["sources"]:
        if source["parser"] == "fac_chapter_word":
            index_html = fetch(source["index_url"]).decode("latin-1")
            link = re.search(r'href="(/gateway/readFile\.asp\?[^"]+\.doc)"', index_html)
            if link is None:
                raise SystemExit(f"No Word file link on {source['index_url']}")
            doc_url = "https://www.flrules.org" + html.unescape(link.group(1))
            raw = fetch(doc_url)
            meta = {"url": doc_url, "effective_dates": fac_effective_dates(index_html)}
            documents.append({"source_id": source["id"], "url": doc_url, "index_url": source["index_url"], "sha256": sha256(raw), "bytes": len(raw)})
            units += PARSERS[source["parser"]](source, raw, meta)
        elif source["parser"] == "fl_statute_section_html":
            index = fetch(source["index_url"]).decode("utf-8", errors="replace")
            sections = sorted(
                set(re.findall(r"Sections/(\d{4}\.\d+[A-Za-z]*)\.html", index)),
                key=lambda s: float(s.split(".")[0]) + float("0." + re.sub(r"\D", "", s.split(".")[1])),
            )
            for number in sections:
                url = source["section_url"].format(file=number)
                raw = fetch(url)
                documents.append({"source_id": source["id"], "url": url, "sha256": sha256(raw), "bytes": len(raw)})
                units += PARSERS[source["parser"]](source, raw, {"url": url})
                time.sleep(0.2)
        else:
            raise SystemExit(f"Unknown parser {source['parser']}")
    for number, unit in enumerate(units, 1):
        unit["id"] = f"{state}-{number:05d}"
    corpus = {
        "state": state,
        "name": config["name"],
        "retrieved_at": retrieved_at,
        "sources": [{k: v for k, v in s.items() if k not in ("parser",)} for s in config["sources"]],
        "documents": documents,
        "lay_terms": config.get("lay_terms", {}),
        "units": units,
    }
    target = out / state / "corpus.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(corpus, indent=1, ensure_ascii=False) + "\n")
    temporary.replace(target)  # atomic: readers never see a half-written corpus
    write_mirror(corpus, mirror)
    return corpus


def slug(citation: str) -> str:
    return re.sub(r"[^0-9A-Za-z.-]+", "_", citation.replace(", F.A.C.", "").replace(", F.S.", "").replace("Rule ", "").replace("Section ", "")).strip("_")


def write_mirror(corpus: dict, mirror: Path = MIRROR) -> None:
    """Small pages: index -> section page -> subsection page, each under PAGE_LIMIT."""
    state = corpus["state"]
    root = mirror / state
    if root.exists():
        for old in root.rglob("*.md"):
            old.unlink()
    (root / "s").mkdir(parents=True, exist_ok=True)
    sections: dict[str, list[dict]] = {}
    for unit in corpus["units"]:
        sections.setdefault(unit["section"], []).append(unit)
    stamp = f"Primary sources retrieved {corpus['retrieved_at']}. Text is verbatim from the official publisher; check the official URL before relying on it."
    index_lines = [f"# {corpus['name']}: index", stamp, ""]
    for section, members in sections.items():
        index_lines.append(f"- {section} {members[0]['section_title']} -> s/{section}.md")
    write_paged(root, "index", index_lines)
    for section, members in sections.items():
        top: dict[str, list[dict]] = {}
        for unit in members:
            key = unit["path"][0] if unit["path"] else "intro"
            top.setdefault(key, []).append(unit)
        lines = [
            f"# {section} {members[0]['section_title']}",
            f"Official: {members[0]['url']}",
            f"Effective/edition: {members[0].get('effective') or 'see official page'}",
            "",
        ]
        for key, group in top.items():
            first = group[0]
            name = slug(first["citation"]) if key != "intro" else f"{section}_intro"
            lines.append(f"- {first['citation'] if key != 'intro' else section + ' (opening text)'}: {first['text'][:90]} -> {name}.md")
            body = [
                f"# {first['citation'] if key != 'intro' else section + ' opening text'}",
                f"Section: {section} {first['section_title']}",
                f"Official: {first['url']}",
                "",
            ]
            for unit in group:
                body.append(f"[{unit['citation']}] {unit['text']}")
            write_paged(root / "s", name, body)
        write_paged(root / "s", section, lines)


def write_paged(folder: Path, name: str, lines: list[str]) -> None:
    pages, current = [], []
    for line in lines:
        while len(line) > PAGE_LIMIT:
            if current:
                pages.append(current)
                current = []
            cut = line.rfind(" ", 0, PAGE_LIMIT - 200)
            if cut <= 0:
                cut = PAGE_LIMIT - 200
            current.append(line[:cut])
            pages.append(current)
            current, line = [], "(continued) " + line[cut + 1 :]
        if sum(len(x) + 1 for x in current) + len(line) > PAGE_LIMIT - 120:
            pages.append(current)
            current = []
        current.append(line)
    pages.append(current)
    for number, page in enumerate(pages, 1):
        filename = f"{name}.md" if number == 1 else f"{name}.p{number}.md"
        footer = [f"Next page: {name}.p{number + 1}.md"] if number < len(pages) else []
        (folder / filename).write_text("\n".join(page + footer) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("state", nargs="?", default="FL")
    parser.add_argument("--out", type=Path, default=DATA, help="corpus root; writes <out>/<STATE>/corpus.json")
    parser.add_argument("--mirror", type=Path, default=MIRROR, help="mirror root; writes <mirror>/<STATE>/")
    args = parser.parse_args()
    result = build(args.state, args.out, args.mirror)
    print(json.dumps({"state": result["state"], "documents": len(result["documents"]), "units": len(result["units"]), "retrieved_at": result["retrieved_at"]}))
