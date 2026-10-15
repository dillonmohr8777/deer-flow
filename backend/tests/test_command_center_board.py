"""Command Center board: each tile reads real files or says it is unavailable (never 0)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.gateway.routers import command_center as mod
from deerflow.models.paid_admission import AdmissionGate


def test_admission_missing_ledger_is_unavailable(tmp_path):
    tile = mod.admission_tile(tmp_path / "nope")
    assert tile["available"] is False and "used_usd" not in tile and tile["reason"]
    assert not (tmp_path / "nope").exists()  # reading never creates ledger state


def test_admission_reads_used_and_ceiling(tmp_path):
    gate = AdmissionGate(tmp_path)
    (tmp_path / "holds.json").write_text('{"holds":[]}')
    rid = gate.reserve("openrouter", 2_000_000, "k1")
    gate.settle(rid, 1_500_000)
    tile = mod.admission_tile(tmp_path)
    assert tile["available"] is True
    assert tile["used_usd"] == 1.5 and tile["ceiling_usd"] == 20.0
    assert tile["by_route"] == {"openrouter": 1.5}
    assert tile["as_of"]


def test_admission_corrupt_ledger_is_unavailable(tmp_path):
    (tmp_path / "audit.jsonl").write_text("not json\n")
    tile = mod.admission_tile(tmp_path)
    assert tile["available"] is False and "ledger_corrupt" in tile["reason"]


def _result(path, started, passed, tasks):
    path.write_text(json.dumps({"model": "m", "started_at": started, "totals": {"passed": passed, "tasks": tasks}}))


def test_evals_missing_dir_explains_wiring(tmp_path):
    tile = mod.evals_tile(tmp_path / "none")
    assert tile["available"] is False and "make agency-evals" in tile["reason"]


def test_evals_groups_by_iso_week_and_skips_junk(tmp_path):
    _result(tmp_path / "a.json", "2026-10-05T10:00:00+00:00", 20, 25)
    _result(tmp_path / "b.json", "2026-10-06T10:00:00+00:00", 25, 25)
    _result(tmp_path / "c.json", "2026-09-28T10:00:00+00:00", 10, 25)
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "report.html").write_text("x")
    tile = mod.evals_tile(tmp_path)
    assert [w["week"] for w in tile["weeks"]] == ["2026-W40", "2026-W41"]
    assert tile["weeks"][0]["pass_rate"] == 0.4
    assert tile["weeks"][1] == {"week": "2026-W41", "pass_rate": 0.9, "runs": 2, "tasks": 50}
    assert tile["as_of"] == "2026-10-06T10:00:00+00:00"


def test_evals_dir_without_valid_runs_is_unavailable(tmp_path):
    (tmp_path / "bad.json").write_text("{")
    assert mod.evals_tile(tmp_path)["available"] is False


def test_lobby_unset_says_host_only():
    tile = mod.lobby_tile(None)
    assert tile["available"] is False and "host" in tile["reason"].lower()


def test_lobby_builds_undirected_graph(tmp_path):
    (tmp_path / "lobby-dex.json").write_text(json.dumps({"relationships": {"lobby-maya": {"score": 4, "why": "x", "t": "2026-10-06T09:55"}}}))
    (tmp_path / "lobby-maya.json").write_text(json.dumps({"relationships": {"lobby-dex": {"score": 2, "t": "2026-10-06T10:00"}, "lobby-gus": {"score": "bad"}}}))
    (tmp_path / "notes.txt").write_text("ignore")
    tile = mod.lobby_tile(tmp_path)
    assert tile["available"] is True
    assert sorted(n["id"] for n in tile["nodes"]) == ["dex", "maya"]
    assert tile["edges"] == [{"source": "dex", "target": "maya", "score": 3.0}]
    assert tile["as_of"] == "2026-10-06T10:00"
    assert "why" not in json.dumps(tile)


def test_lobby_empty_dir_is_unavailable(tmp_path):
    assert mod.lobby_tile(tmp_path)["available"] is False


@pytest.mark.asyncio
async def test_endpoint_admin_only_and_shape(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(mod.router)
    monkeypatch.setenv("MOMO_ADMISSION_DIR", str(tmp_path / "adm"))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.delenv("MOMO_LOBBY_NOTES_DIR", raising=False)

    async def deny(request, *, detail):
        raise HTTPException(status_code=403, detail=detail)

    async def allow(request, *, detail):
        return None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        monkeypatch.setattr(mod, "require_admin_user", deny)
        assert (await c.get("/api/command-center/board")).status_code == 403
        monkeypatch.setattr(mod, "require_admin_user", allow)
        body = (await c.get("/api/command-center/board")).json()
    assert set(body) == {"as_of", "admission", "evals", "lobby"}
    assert all(body[k]["available"] is False for k in ("admission", "evals", "lobby"))
    assert not (tmp_path / "adm").exists()
