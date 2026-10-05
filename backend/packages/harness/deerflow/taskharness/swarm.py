"""Swarm helper: fan out cheap, fan in strong.

N variants run on the cheap model, then one verifier picks the best and
summarizes. Three guards, all in code:

* data classification -- a spec marked `client_private` cannot be sent to a
  contributor-tier model. This reads `spec.data_class`, not a prompt sentence,
  so no wording change can defeat it.
* scale guard -- a new fan-out key is allowed 1 run, then up to 10, then any N.
  You cannot start at N.
* budget -- each variant reserves and settles through the admission gate, and
  an optional total cap refuses the whole fan-out before the first call.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .budget import BudgetDenied, BudgetGate, FreeGate
from .contract import HarnessError, RunOutput, TaskSpec

# Tiers that never see client-private data (Spark 1.3 Contributor and friends).
CONTRIBUTOR_TIERS = frozenset({"contributor", "spark_contributor", "community"})

# Scale rungs: prove 1, then up to 10, then unbounded.
RUNGS = (1, 10)


class ScaleRefused(RuntimeError):
    """The requested fan-out skips a rung, or busts the total cap."""


class DataClassRefused(RuntimeError):
    """Client-private data was about to reach a contributor-tier model."""


@dataclass(frozen=True)
class SwarmPick:
    index: int
    summary: str
    why: str = ""


@dataclass(frozen=True)
class SwarmResult:
    pick: SwarmPick
    best: RunOutput
    variants: tuple[RunOutput, ...]
    cost_micro: int
    scale: int


class ScaleGuard:
    """Remembers the largest fan-out proven for a key. One small JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ScaleRefused("scale_state_unreadable") from exc
        if not isinstance(data, dict):
            raise ScaleRefused("scale_state_unreadable")
        return {str(k): int(v) for k, v in data.items()}

    def limit(self, key: str) -> int | None:
        """Largest N allowed next. None means unbounded."""
        proven = self._load().get(key)
        if proven is None:
            return RUNGS[0]
        if proven < RUNGS[1]:
            return RUNGS[1]
        return None

    def record(self, key: str, scale: int) -> None:
        state = self._load()
        state[key] = max(scale, state.get(key, 0))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


Variant = Callable[[TaskSpec, int], RunOutput]
Verifier = Callable[[TaskSpec, Sequence[RunOutput]], SwarmPick]


def fan_out(
    spec: TaskSpec,
    variant: Variant,
    *,
    n: int,
    verifier: Verifier,
    guard: ScaleGuard,
    gate: BudgetGate | None = None,
    tier: str = "contributor",
    key: str = "",
    cap_micro_per_variant: int = 0,
    cap_micro_total: int = 0,
) -> SwarmResult:
    """Run `n` variants, then let `verifier` pick and summarize one."""
    if type(n) is not int or n < 1:
        raise HarnessError("swarm_n_invalid")
    if tier in CONTRIBUTOR_TIERS and spec.data_class != "public":
        raise DataClassRefused(f"{spec.data_class}_data_blocked_from_{tier}")

    guard_key = key or f"{spec.id}:{tier}"
    limit = guard.limit(guard_key)
    if limit is not None and n > limit:
        raise ScaleRefused(f"scale_guard: {n} requested, {limit} allowed")
    if cap_micro_total and n * cap_micro_per_variant > cap_micro_total:
        raise ScaleRefused(f"cap_exceeded: {n * cap_micro_per_variant} > {cap_micro_total}")

    gate = gate or FreeGate()
    run_key = spec.run_key
    outputs: list[RunOutput] = []
    spent = 0
    # ponytail: sequential fan-out. Wrap in a ThreadPoolExecutor if latency,
    # rather than determinism, becomes the thing that hurts.
    for index in range(n):
        try:
            rid = gate.reserve(spec.route, cap_micro_per_variant, f"{run_key}:swarm:{index}")
        except BudgetDenied as denied:
            raise ScaleRefused(f"budget_denied:{denied.reason}") from denied
        try:
            output = variant(spec, index)
        except Exception:
            if rid is not None:
                gate.mark_unknown(rid)
            raise
        if not isinstance(output, RunOutput):
            if rid is not None:
                gate.mark_unknown(rid)
            raise HarnessError("swarm_variant_output_invalid")
        spent += max(0, int(output.cost_micro))
        if rid is not None:
            gate.settle(rid, max(0, int(output.cost_micro)))
        outputs.append(output)

    pick = verifier(spec, tuple(outputs))
    if not isinstance(pick, SwarmPick) or not 0 <= pick.index < n:
        raise HarnessError("swarm_pick_invalid")

    guard.record(guard_key, n)  # only a completed fan-in proves the rung
    return SwarmResult(pick=pick, best=outputs[pick.index], variants=tuple(outputs), cost_micro=spent, scale=n)
