"""Read-only state regulation corpus: primary-source text, exact citations, BM25 search.

Each state lives in ``regulations_data/<STATE>/corpus.json`` built by
``scripts/build_regulations.py`` from official publishers only. A state without a
corpus is reported as not loaded; nothing falls back to general web text.
"""

import json
import math
import re
from collections import Counter
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "regulations_data"
STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from has have how i if in into is it its may me must my of on or our should "
    "that the their them there these they this to use used using was what when where which who will with would you your".split()
)


def stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokens(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z0-9]+", text.casefold()) if t not in STOPWORDS]


def available_states() -> list[str]:
    return sorted(p.parent.name for p in DATA.glob("*/corpus.json"))


class Corpus:
    k1, b = 1.4, 0.75

    def __init__(self, data: dict):
        self.state = data["state"]
        self.name = data["name"]
        self.retrieved_at = data["retrieved_at"]
        self.sources = data["sources"]
        self.documents = data["documents"]
        self.lay_terms = {k.casefold(): v for k, v in data.get("lay_terms", {}).items()}
        self.units = data["units"]
        self.by_citation = {u["citation"]: u for u in self.units}
        by_id = {u["id"]: u for u in self.units}
        self.parents = {}
        for unit in self.units:
            path = unit["path"]
            for cut in range(len(path) - 1, -1, -1):
                parent = next(
                    (p for p in self.units if p["section"] == unit["section"] and p["path"] == path[:cut] and p["source_id"] == unit["source_id"]),
                    None,
                )
                if parent is not None:
                    self.parents[unit["id"]] = parent["id"]
                    break
        self._by_id = by_id
        self.docs = [Counter(tokens(f"{u['section_title']} {self.context(u)} {u['text']}")) for u in self.units]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / max(len(self.lengths), 1)
        frequency = Counter(term for d in self.docs for term in d)
        total = len(self.docs)
        self.idf = {term: math.log(1 + (total - n + 0.5) / (n + 0.5)) for term, n in frequency.items()}

    def ancestors(self, unit: dict) -> list[dict]:
        chain, current = [], unit
        while current["id"] in self.parents:
            current = self._by_id[self.parents[current["id"]]]
            chain.append(current)
        return list(reversed(chain))

    def context(self, unit: dict) -> str:
        return " ".join(a["text"][:240] for a in self.ancestors(unit))

    def expand(self, query: str) -> dict[str, float]:
        terms: dict[str, float] = dict(Counter(tokens(query)))
        for word in re.findall(r"[a-z0-9]+", query.casefold()):
            for extra in self.lay_terms.get(word, self.lay_terms.get(stem(word), [])):
                for term in tokens(extra):
                    terms[term] = terms.get(term, 0.0) + 0.8
        return terms

    def search(self, query: str, limit: int = 5) -> list[dict]:
        terms = self.expand(query)
        scored = []
        for index, doc in enumerate(self.docs):
            score = 0.0
            for term, weight in terms.items():
                count = doc.get(term)
                if count:
                    norm = count * (self.k1 + 1) / (count + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average))
                    score += weight * self.idf.get(term, 0.0) * norm
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        # Keep the answer set diverse: at most two hits from one numbered subsection.
        picked, per_group = [], Counter()
        for score, index in scored:
            unit = self.units[index]
            group = (unit["source_id"], unit["section"], unit["path"][0] if unit["path"] else "")
            if per_group[group] < 2:
                per_group[group] += 1
                picked.append(self.view(unit, round(score, 3)))
            if len(picked) == limit:
                break
        return picked

    def view(self, unit: dict, score: float | None = None) -> dict:
        result = {
            "citation": unit["citation"],
            "section": unit["section"],
            "section_title": unit["section_title"],
            "text": unit["text"],
            "context": [{"citation": a["citation"], "text": a["text"]} for a in self.ancestors(unit)],
            "official_url": unit["url"],
            "effective": unit.get("effective"),
            "source_id": unit["source_id"],
            "retrieved_at": self.retrieved_at,
        }
        if score is not None:
            result["score"] = score
        return result

    def section(self, citation: str) -> dict | None:
        unit = self.by_citation.get(citation)
        if unit is None:
            return None
        prefix = unit["path"]
        children = [u for u in self.units if u["section"] == unit["section"] and u["source_id"] == unit["source_id"] and u["path"][: len(prefix)] == prefix]
        return {**self.view(unit), "units": [{"citation": u["citation"], "text": u["text"]} for u in children]}


@cache
def load(state: str) -> Corpus | None:
    state = state.upper()
    if not re.fullmatch(r"[A-Z]{2}", state):
        return None
    path = DATA / state / "corpus.json"
    if not path.is_file():
        return None
    return Corpus(json.loads(path.read_text(encoding="utf-8")))
