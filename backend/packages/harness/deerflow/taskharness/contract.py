"""The Momo task contract: spec -> worker -> verifier -> receipt.

Thin on purpose. There is no graph, no scheduler and no framework here: a
workflow is a `TaskSpec`, a worker callable and a tuple of checks. Everything
else in this module is bookkeeping that proves what actually happened, so a
receipt can never claim more than the evidence supports.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Layers a run can reach, lowest first. "prepared" means the worker produced
# artifacts; "tested"/"installed"/"accepted" are each claimed by the spec's own
# checks; "billed" means real money was settled for an accepted run.
LAYERS = ("prepared", "tested", "installed", "accepted", "billed")
CHECK_LAYERS = ("tested", "installed", "accepted")

# Data classification. The swarm enforces this flag in code (see swarm.py); it
# is deliberately not a sentence in a prompt.
DATA_CLASSES = ("public", "client_private")


class HarnessError(RuntimeError):
    """A harness contract was violated. Always fails a run closed."""


def canonical_json(value: Any) -> str:
    """Stable JSON for hashing: sorted keys, compact, non-JSON types as str."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckResult:
    name: str
    layer: str
    ok: bool
    detail: str = ""
    evidence: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "layer": self.layer, "ok": self.ok, "detail": self.detail, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class RunOutput:
    """What a worker hands back.

    `done` is advisory and never ends the loop: the runner stops on evidence
    (acceptance checks passing), never on a worker saying it finished.
    """

    output: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    cost_micro: int = 0
    model: str = ""
    done: bool = False


@runtime_checkable
class Check(Protocol):
    """A verifier. Deterministic or judge-style; both answer the same way."""

    name: str
    layer: str

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult: ...


@dataclass(frozen=True)
class TaskSpec:
    """One unit of work, fully declared before anything runs.

    `checks` is the machine-readable stop rule; `stop_rule` is the sentence a
    human reads. A spec with no checks is rejected, because a run with nothing
    to verify can only ever stop on a self-report.
    """

    id: str
    client_id: str
    goal: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()
    route: str = "local"
    cap_micro: int = 0
    stop_rule: str = ""
    checks: tuple[Check, ...] = ()
    data_class: str = "client_private"
    max_retries: int = 1
    escalate_to: str = "dillon"

    def __post_init__(self) -> None:
        for name in ("id", "client_id", "goal", "route"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise HarnessError(f"spec_{name}_required")
        if self.data_class not in DATA_CLASSES:
            raise HarnessError("spec_data_class_invalid")
        if type(self.cap_micro) is not int or self.cap_micro < 0:
            raise HarnessError("spec_cap_invalid")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise HarnessError("spec_max_retries_invalid")
        if not self.checks:
            raise HarnessError("spec_checks_required")
        seen: set[str] = set()
        for check in self.checks:
            if getattr(check, "layer", None) not in CHECK_LAYERS:
                raise HarnessError("spec_check_layer_invalid")
            name = getattr(check, "name", "")
            if not name or name in seen:
                raise HarnessError("spec_check_name_invalid")
            seen.add(name)
        if not any(check.layer == "accepted" for check in self.checks):
            raise HarnessError("spec_accepted_check_required")

    @property
    def run_key(self) -> str:
        """Identity of this unit of work, used for idempotency.

        Changing the goal, the inputs or the acceptance checks makes a new unit,
        so a re-run is honest work rather than a silently reused receipt.
        """
        return sha256_text(
            canonical_json(
                {
                    "id": self.id,
                    "client_id": self.client_id,
                    "goal": self.goal,
                    "inputs": dict(self.inputs),
                    "checks": [[c.name, c.layer] for c in self.checks],
                }
            )
        )


def layer_reached(results: Sequence[CheckResult], *, prepared: bool, billed: bool = False) -> str | None:
    """Highest layer the evidence supports. None means nothing ran."""
    if not prepared:
        return None
    reached = "prepared"
    for layer in CHECK_LAYERS:
        claimed = [r for r in results if r.layer == layer]
        if not claimed:
            continue  # this spec does not claim the layer; pass through it
        if not all(r.ok for r in claimed):
            return reached
        reached = layer
    if billed and reached == "accepted":
        return "billed"
    return reached


@dataclass(frozen=True)
class Receipt:
    """What a run is allowed to claim. Written append-only, never edited."""

    task_id: str
    client_id: str
    run_key: str
    layer: str | None
    ok: bool
    route: str
    model: str
    cost_micro: int
    duration_s: float
    attempts: int
    checks: tuple[CheckResult, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str = ""
    escalated_to: str = ""
    started_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "client_id": self.client_id,
            "run_key": self.run_key,
            "layer": self.layer,
            "ok": self.ok,
            "route": self.route,
            "model": self.model,
            "cost_micro": self.cost_micro,
            "duration_s": self.duration_s,
            "attempts": self.attempts,
            "checks": [c.to_json() for c in self.checks],
            "evidence": list(self.evidence),
            "reason": self.reason,
            "escalated_to": self.escalated_to,
            "started_at": self.started_at,
        }

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> Receipt:
        try:
            checks = tuple(CheckResult(name=c["name"], layer=c["layer"], ok=bool(c["ok"]), detail=c.get("detail", ""), evidence=tuple(c.get("evidence", ()))) for c in row["checks"])
            return cls(
                task_id=row["task_id"],
                client_id=row["client_id"],
                run_key=row["run_key"],
                layer=row["layer"],
                ok=bool(row["ok"]),
                route=row["route"],
                model=row.get("model", ""),
                cost_micro=int(row["cost_micro"]),
                duration_s=float(row["duration_s"]),
                attempts=int(row["attempts"]),
                checks=checks,
                evidence=tuple(row.get("evidence", ())),
                reason=row.get("reason", ""),
                escalated_to=row.get("escalated_to", ""),
                started_at=row.get("started_at", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HarnessError("receipt_log_corrupt") from exc


class ReceiptLog:
    """Append-only receipts on disk, one JSON object per line.

    The log is also the checkpoint: a completed unit is one that already has an
    accepted receipt, so a restart never replays paid work it already paid for.
    A corrupt line fails closed (nothing is treated as completed) rather than
    being skipped quietly.
    """

    # ponytail: sync file I/O and an O(file) scan. Call it from asyncio.to_thread
    # in async code, and add an index only if the log outgrows a linear read.
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, receipt: Receipt) -> None:
        line = canonical_json(receipt.to_json()) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def __iter__(self) -> Iterator[Receipt]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError as exc:
                    raise HarnessError("receipt_log_corrupt") from exc
                yield Receipt.from_json(row)

    def accepted(self, run_key: str) -> Receipt | None:
        """The receipt that makes this unit complete, if there is one."""
        found = None
        for receipt in self:
            if receipt.run_key == run_key and receipt.ok and receipt.layer in ("accepted", "billed"):
                found = receipt
        return found
