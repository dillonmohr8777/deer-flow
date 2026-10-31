#!/usr/bin/env python3
"""Fail when a real client name appears in a tracked file or file path.

This repository is public, so the list of names to keep out can't be public
either. ``scripts/client_name_denylist.json`` holds only salted SHA-256 hashes
of normalised names (lowercase tokens joined by one space). At check time every
1..N-token window of every tracked text file, and of every tracked path, is
hashed the same way and compared. Output names the file and line only, never
the matched text, so CI logs don't repeat a name.

Normalisation: split camelCase, lowercase, keep runs of ``[a-z0-9]``. So
"Acme-Dental", "acme_dental" and "AcmeDental" all become the phrase
"acme dental". Names spelled as one word with no case boundary ("acmedental")
need their own entry; ``build`` adds the joined spelling for every phrase.

    python scripts/client_name_guard.py check              # CI entry point
    python scripts/client_name_guard.py build < names.txt > scripts/client_name_denylist.json
    python scripts/client_name_guard.py build --salt <existing> ...   # keep the salt when refreshing
    python scripts/client_name_guard.py build --merge scripts/client_name_denylist.json < new_names.txt > /tmp/merged.json
                                                       # add names to the committed list without the old plaintext

``names.txt`` is one name or alias per line and is never committed. See
``docs/CLIENT_NAME_GUARD.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DENYLIST_PATH = Path(__file__).resolve().with_name("client_name_denylist.json")

# Third-party, generated or binary material is not ours to scrub.
SKIP_NAMES = frozenset(
    {
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "uv.lock",
        "poetry.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "go.sum",
        "client_name_denylist.json",
    }
)
SKIP_DIR_PARTS = frozenset(
    {"node_modules", "vendor", "vendored", "third_party", ".git"}
)
SKIP_SUFFIXES = frozenset(
    {
        ".lock",
        ".min.js",
        ".min.css",
        ".map",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".ico",
        ".icns",
    }
)
MAX_FILE_BYTES = 5 * 1024 * 1024

_CAMEL_1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, splitting camelCase boundaries first."""
    text = _CAMEL_2.sub(r"\1 \2", _CAMEL_1.sub(r"\1 \2", text))
    return _TOKEN.findall(text.lower())


@lru_cache(maxsize=1_000_000)
def phrase_hash(salt: str, phrase: str) -> str:
    return hashlib.sha256(f"{salt}:{phrase}".encode()).hexdigest()


def normalise_name(name: str) -> str:
    return " ".join(tokens(name))


def build_denylist(names: Iterable[str], salt: str | None = None) -> dict:
    """Hash every name, plus its joined spelling ("acme dental" -> "acmedental")."""
    salt = salt or secrets.token_hex(16)
    phrases: set[str] = set()
    for name in names:
        phrase = normalise_name(name)
        if not phrase:
            continue
        phrases.add(phrase)
        joined = phrase.replace(" ", "")
        if joined != phrase:
            phrases.add(joined)
    return {
        "version": 1,
        "salt": salt,
        "max_tokens": max((len(p.split()) for p in phrases), default=1),
        "hashes": sorted(phrase_hash(salt, p) for p in phrases),
    }


def merge_denylists(base: dict, extra: dict) -> dict:
    """Union two deny-lists built with the same salt."""
    if base["salt"] != extra["salt"]:
        raise ValueError("deny-lists use different salts")
    return {
        "version": base.get("version", 1),
        "salt": base["salt"],
        "max_tokens": max(int(base["max_tokens"]), int(extra["max_tokens"])),
        "hashes": sorted(set(base["hashes"]) | set(extra["hashes"])),
    }


class Denylist:
    def __init__(self, data: dict) -> None:
        self.salt = str(data["salt"])
        self.max_tokens = int(data["max_tokens"])
        self.hashes = frozenset(data["hashes"])

    @classmethod
    def load(cls, path: Path = DENYLIST_PATH) -> Denylist:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def _first_match(self, words: Sequence[str]) -> int | None:
        """Index of the first token that starts a deny-listed window, or None."""
        for start in range(len(words)):
            for size in range(1, self.max_tokens + 1):
                if start + size > len(words):
                    break
                if (
                    phrase_hash(self.salt, " ".join(words[start : start + size]))
                    in self.hashes
                ):
                    return start
        return None

    def line_matches(self, line: str) -> bool:
        return self._first_match(tokens(line)) is not None

    def match_lines(self, text: str) -> list[int]:
        """1-based line numbers where a deny-listed window starts.

        Windows run across line breaks, so a name wrapped over two lines of prose or a docstring is
        still found (and reported at the line its first word is on).
        """
        words: list[str] = []
        lines: list[int] = []
        for number, line in enumerate(text.splitlines(), start=1):
            found = tokens(line)
            words.extend(found)
            lines.extend([number] * len(found))
        hits: set[int] = set()
        for start in range(len(words)):
            for size in range(1, self.max_tokens + 1):
                if start + size > len(words):
                    break
                if (
                    phrase_hash(self.salt, " ".join(words[start : start + size]))
                    in self.hashes
                ):
                    hits.add(lines[start])
                    break
        return sorted(hits)


def scan_text(text: str, denylist: Denylist) -> list[int]:
    """1-based line numbers containing (or starting) a deny-listed phrase."""
    return denylist.match_lines(text)


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return (
        path.name in SKIP_NAMES
        or bool(parts & SKIP_DIR_PARTS)
        or path.suffix in SKIP_SUFFIXES
        or "".join(path.suffixes[-2:]) in SKIP_SUFFIXES
    )


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    return [
        Path(item)
        for item in out.decode("utf-8", "surrogateescape").split("\0")
        if item
    ]


def iter_findings(
    root: Path, files: Sequence[Path], denylist: Denylist
) -> Iterator[tuple[str, int | None]]:
    for rel in files:
        if should_skip(rel):
            continue
        if denylist.line_matches(rel.as_posix()):
            yield rel.as_posix(), None
        full = root / rel
        try:
            if (
                not full.is_file()
                or full.is_symlink()
                or full.stat().st_size > MAX_FILE_BYTES
            ):
                continue
            data = full.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # binary
        for number in scan_text(data.decode("utf-8", "replace"), denylist):
            yield rel.as_posix(), number


def run_check(root: Path, denylist_path: Path, annotations: bool = False) -> int:
    if not denylist_path.is_file():
        print(f"client-name guard: {denylist_path} is missing", file=sys.stderr)
        return 2
    denylist = Denylist.load(denylist_path)
    findings = list(iter_findings(root, tracked_files(root), denylist))
    for path, line in findings:
        where = f"{path}:{line}" if line else path
        message = (
            "file path contains a deny-listed name"
            if line is None
            else "contains a deny-listed name"
        )
        if annotations:
            location = f"file={path},line={line}" if line else f"file={path}"
            print(f"::error {location}::{message}")
        else:
            print(f"{where}: {message}")
    if findings:
        print(
            f"\nclient-name guard: {len(findings)} finding(s). Use a synthetic name (for example Acme Dental) instead.",
            file=sys.stderr,
        )
        return 1
    print(f"client-name guard: clean ({len(denylist.hashes)} hashed names checked)")
    return 0


def run_build(salt: str | None, stdin: Iterable[str], merge: Path | None = None) -> int:
    names = [
        line.strip()
        for line in stdin
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not names:
        print("client-name guard: no names on stdin", file=sys.stderr)
        return 2
    base = json.loads(merge.read_text(encoding="utf-8")) if merge else None
    if base is not None and salt not in (None, base["salt"]):
        print("client-name guard: --salt does not match the salt of the --merge list", file=sys.stderr)
        return 2
    result = build_denylist(names, base["salt"] if base else salt)
    if base is not None:
        result = merge_denylists(base, result)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="scan tracked files and paths")
    check.add_argument("--root", type=Path, default=REPO_ROOT)
    check.add_argument("--denylist", type=Path, default=DENYLIST_PATH)
    check.add_argument(
        "--annotations", action="store_true", help="emit GitHub error annotations"
    )
    build = sub.add_parser(
        "build", help="read names on stdin, write the hashed deny-list JSON to stdout"
    )
    build.add_argument(
        "--salt", help="reuse an existing salt (default: a new random one)"
    )
    build.add_argument(
        "--merge",
        type=Path,
        help="add the names to this existing deny-list (keeps its salt and hashes)",
    )
    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check(args.root, args.denylist, args.annotations)
    return run_build(args.salt, sys.stdin, args.merge)


if __name__ == "__main__":
    raise SystemExit(main())
