"""The client-name guard: hashed deny-list, tokeniser, and the committed list staying clean."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / "scripts" / "client_name_guard.py"
_spec = importlib.util.spec_from_file_location("client_name_guard", GUARD_PATH)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

NAMES = ["Acme Dental", "Northwind Events LLC", "Zed"]


@pytest.fixture()
def denylist():
    return guard.Denylist(guard.build_denylist(NAMES, salt="test-salt"))


def test_the_deny_list_stores_only_salted_hashes():
    data = guard.build_denylist(NAMES, salt="s")
    text = json.dumps(data).lower()

    assert data["salt"] == "s" and data["max_tokens"] == 3
    assert all(len(h) == 64 for h in data["hashes"])
    for word in ("acme", "dental", "northwind", "zed"):
        assert word not in text
    # A different salt gives different hashes, so one list can't be reused to read another.
    assert set(data["hashes"]).isdisjoint(guard.build_denylist(NAMES, salt="t")["hashes"])


def test_merging_new_names_keeps_the_salt_and_every_existing_hash(tmp_path, capsys):
    import io

    base = guard.build_denylist(NAMES, salt="keep-me")
    path = tmp_path / "list.json"
    path.write_text(json.dumps(base))

    assert guard.run_build(None, io.StringIO("Jordan Ellis\n"), merge=path) == 0
    merged = json.loads(capsys.readouterr().out)

    assert merged["salt"] == "keep-me"
    assert set(base["hashes"]) < set(merged["hashes"]) and merged["hashes"] == sorted(merged["hashes"])
    found = guard.Denylist(merged)
    assert found.line_matches("Acme Dental") and found.line_matches("jordan-ellis") and found.line_matches("jordanellis")
    assert guard.run_build("another-salt", io.StringIO("Jordan Ellis\n"), merge=path) == 2


@pytest.mark.parametrize(
    "line",
    ["Call Acme Dental today", "ACME-DENTAL", "acme_dental_widget", "AcmeDental", "acmedental", "see northwind events llc.", "the Zed client"],
)
def test_names_match_whatever_the_case_spacing_or_punctuation(denylist, line):
    assert denylist.line_matches(line)


@pytest.mark.parametrize("line", ["Acme", "dental office", "northwind events", "azed", "Zeds", "nothing here"])
def test_partial_names_and_other_words_do_not_match(denylist, line):
    assert not denylist.line_matches(line)


def test_scan_reports_line_numbers_only(denylist):
    assert guard.scan_text("ok\nstill ok\nAcme Dental here\n", denylist) == [3]


def test_a_name_wrapped_across_lines_is_still_found(denylist):
    assert guard.scan_text("intro\nsee Acme\nDental for details\n", denylist) == [2]


def test_a_name_in_a_path_or_a_file_fails_the_check(tmp_path, denylist, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "ok.md").write_text("synthetic only\n")
    (repo / "acme-dental-notes.md").write_text("fine body\n")
    (repo / "body.txt").write_text("fine\nAcme Dental says hi\n")
    (repo / "pnpm-lock.yaml").write_text("acme dental\n")  # lockfiles are skipped
    (repo / "blob.bin").write_bytes(b"\0acme dental")  # binary files are skipped
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    path = tmp_path / "list.json"
    path.write_text(json.dumps(guard.build_denylist(NAMES, salt="test-salt")))

    assert guard.run_check(repo, path) == 1

    out = capsys.readouterr()
    assert "acme-dental-notes.md: file path contains" in out.out
    assert "body.txt:2: contains" in out.out
    assert "ok.md" not in out.out and "pnpm-lock" not in out.out and "blob.bin" not in out.out


def test_github_annotations_name_the_file_and_line_only(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "body.txt").write_text("fine\nAcme Dental says hi\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    path = tmp_path / "list.json"
    path.write_text(json.dumps(guard.build_denylist(NAMES, salt="s")))

    assert guard.run_check(repo, path, annotations=True) == 1

    assert capsys.readouterr().out.splitlines()[0] == "::error file=body.txt,line=2::contains a deny-listed name"


def test_a_clean_tree_passes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "ok.md").write_text("Acme Co\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    path = tmp_path / "list.json"
    path.write_text(json.dumps(guard.build_denylist(NAMES, salt="s")))

    assert guard.run_check(repo, path) == 0


def test_the_committed_deny_list_is_hashes_only_and_the_repo_is_clean():
    data = json.loads((REPO_ROOT / "scripts" / "client_name_denylist.json").read_text())

    assert set(data) == {"version", "salt", "max_tokens", "hashes"}
    assert len(data["hashes"]) > 50 and all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in data["hashes"])
    assert guard.run_check(REPO_ROOT, guard.DENYLIST_PATH) == 0
