"""Read-only data for the Command Center live board (admin only).

Each tile reports ``available`` plus where it came from. Missing or unreadable
sources are "unavailable" with a reason, never a zero. Spend, approvals and runs
already have their own endpoints, so the page calls those directly.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request

from app.gateway.deps import require_admin_user
from deerflow.config.runtime_paths import runtime_home
from deerflow.models.paid_admission import CEILING_MICRO, AdmissionDenied, AdmissionGate

router = APIRouter(prefix="/api/command-center", tags=["command-center"])

_MAX_FILES = 200
EVALS_HINT = "No eval results found. Run `make agency-evals` in backend/ with EVAL_OUT pointing at the gateway's DEER_FLOW_HOME/agency-evals folder."
LOBBY_HINT = "Host-only for now. The lobby driver keeps its notes on the Mac host, which the gateway container cannot read. Mount that notes folder read-only and set MOMO_LOBBY_NOTES_DIR to its container path to turn this on."


def _off(reason: str) -> dict:
    return {"available": False, "reason": reason}


def admission_tile(state_dir: Path) -> dict:
    audit = state_dir / "audit.jsonl"
    if not audit.is_file():  # AdmissionGate() creates its dir, so never build it blind
        return _off("No paid-admission ledger is visible to the gateway.")
    try:
        status = AdmissionGate(state_dir).status()
    except (AdmissionDenied, OSError) as exc:
        return _off(f"Ledger unreadable: {getattr(exc, 'reason', type(exc).__name__)}")
    return {
        "available": True,
        "as_of": datetime.fromtimestamp(audit.stat().st_mtime, UTC).isoformat(timespec="seconds"),
        "ceiling_usd": CEILING_MICRO / 1_000_000,
        "used_usd": status["used_micro"] / 1_000_000,
        "by_route": {k: v / 1_000_000 for k, v in sorted(status["by_route"].items())},
    }


def evals_tile(directory: Path) -> dict:
    weeks: dict[str, dict] = {}
    latest = ""
    files = sorted(directory.glob("*.json"))[:_MAX_FILES] if directory.is_dir() else []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            started = str(doc["started_at"])
            passed, tasks = int(doc["totals"]["passed"]), int(doc["totals"]["tasks"])
            iso = datetime.fromisoformat(started).isocalendar()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if tasks <= 0:
            continue
        w = weeks.setdefault(f"{iso.year}-W{iso.week:02d}", {"passed": 0, "tasks": 0, "runs": 0})
        w["passed"] += passed
        w["tasks"] += tasks
        w["runs"] += 1
        latest = max(latest, started)
    if not weeks:
        return _off(EVALS_HINT)
    return {
        "available": True,
        "as_of": latest,
        "weeks": [{"week": k, "pass_rate": v["passed"] / v["tasks"], "runs": v["runs"], "tasks": v["tasks"]} for k, v in sorted(weeks.items())],
    }


def lobby_tile(directory: Path | None) -> dict:
    if directory is None or not directory.is_dir():
        return _off(LOBBY_HINT)
    pairs: dict[tuple[str, str], list[float]] = {}
    nodes: set[str] = set()
    latest = ""
    for path in sorted(directory.glob("lobby-*.json"))[:_MAX_FILES]:
        me = path.stem.removeprefix("lobby-")
        try:
            items = list(json.loads(path.read_text(encoding="utf-8"))["relationships"].items())
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        for other, rel in items:
            try:
                score = float(rel["score"])
            except (KeyError, TypeError, ValueError):
                continue
            other = str(other).removeprefix("lobby-")
            nodes.update((me, other))
            pairs.setdefault(tuple(sorted((me, other))), []).append(score)
            latest = max(latest, str(rel.get("t", "")))
    if not pairs:
        return _off("The lobby notes folder has no relationship scores yet.")
    return {
        "available": True,
        "as_of": latest or None,
        "nodes": [{"id": n} for n in sorted(nodes)],
        "edges": [{"source": a, "target": b, "score": sum(s) / len(s)} for (a, b), s in sorted(pairs.items())],
    }


@router.get("/board")
async def get_board(request: Request) -> dict:
    await require_admin_user(request, detail="System administrator privileges are required.")
    adm = Path(os.environ.get("MOMO_ADMISSION_DIR") or Path.home() / ".momo" / "admission")
    lobby = os.environ.get("MOMO_LOBBY_NOTES_DIR")
    return {
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "admission": admission_tile(adm),
        "evals": evals_tile(runtime_home() / "agency-evals"),
        "lobby": lobby_tile(Path(lobby) if lobby else None),
    }
