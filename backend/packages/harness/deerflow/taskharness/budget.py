"""Budget wiring for the harness.

The real checkpoint is MomoBot's paid-route admission gate
(`deerflow.models.paid_admission.AdmissionGate`, built on branch
`claude/admission-gate-20261005`). It is not on this branch, so this module
defines the thin interface the harness needs, an adapter that wraps the real
gate once it lands, and a fake for tests.

Interface, matching the real gate exactly:
    reserve(route, amount_micro, key) -> reservation id, or None for $0 routes
    settle(rid, actual_micro) -> True if newly settled, False if already settled
    mark_unknown(rid) -> outcome unknown, keep the full hold, never auto-retry
A refusal raises; amounts are integer micro-USD.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class BudgetDenied(RuntimeError):
    """A paid route was refused. Carries the gate's reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@runtime_checkable
class BudgetGate(Protocol):
    def reserve(self, route: str, amount_micro: int, key: str) -> str | None: ...

    def settle(self, rid: str, actual_micro: int) -> bool: ...

    def mark_unknown(self, rid: str) -> None: ...


class FreeGate:
    """Default gate: $0 routes only.

    Any priced reservation is denied, so a workflow cannot spend money just
    because nobody passed it a real gate.
    """

    def reserve(self, route: str, amount_micro: int, key: str) -> str | None:
        if amount_micro:
            raise BudgetDenied("no_paid_gate_configured")
        return None

    def settle(self, rid: str, actual_micro: int) -> bool:
        if actual_micro:
            raise BudgetDenied("no_paid_gate_configured")
        return True

    def mark_unknown(self, rid: str) -> None:
        return None


class HarnessBudgetUnavailable(RuntimeError):
    """The real admission gate is not importable on this branch."""


class AdmissionGateAdapter:
    """Wraps the real admission gate and translates its denial.

    Integration step (one line at the call site, nothing else):
        from deerflow.models.paid_admission import AdmissionGate
        gate = AdmissionGateAdapter(AdmissionGate())
    Passing no gate imports it lazily, which fails loudly if the admission
    branch is not merged yet.
    """

    def __init__(self, gate: object | None = None) -> None:
        if gate is None:
            try:
                from deerflow.models.paid_admission import AdmissionGate  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on the admission branch
                raise HarnessBudgetUnavailable("deerflow.models.paid_admission is not on this branch; merge claude/admission-gate-20261005 or pass a gate") from exc
            gate = AdmissionGate()
        self._gate = gate

    def _call(self, name: str, *args: object) -> object:
        try:
            return getattr(self._gate, name)(*args)
        except Exception as exc:  # the real gate raises its own AdmissionDenied
            reason = getattr(exc, "reason", None)
            if reason is None:
                raise
            raise BudgetDenied(str(reason)) from exc

    def reserve(self, route: str, amount_micro: int, key: str) -> str | None:
        return self._call("reserve", route, amount_micro, key)  # type: ignore[return-value]

    def settle(self, rid: str, actual_micro: int) -> bool:
        return bool(self._call("settle", rid, actual_micro))

    def mark_unknown(self, rid: str) -> None:
        self._call("mark_unknown", rid)


class FakeGate:
    """Test double. Records every call; denies on request.

    `deny` is a route -> reason map; `deny_all` refuses everything. No state
    dir, no file, no money.
    """

    def __init__(self, *, deny: dict[str, str] | None = None, deny_all: str = "") -> None:
        self.deny = dict(deny or {})
        self.deny_all = deny_all
        self.reserved: list[tuple[str, int, str]] = []
        self.settled: list[tuple[str, int]] = []
        self.unknown: list[str] = []
        self._next = 0

    def reserve(self, route: str, amount_micro: int, key: str) -> str | None:
        if self.deny_all:
            raise BudgetDenied(self.deny_all)
        if route in self.deny:
            raise BudgetDenied(self.deny[route])
        self.reserved.append((route, amount_micro, key))
        if not amount_micro:
            return None  # $0 route: audited, no reservation, like the real gate
        if any(existing == key for _, amount, existing in self.reserved[:-1] if amount):
            raise BudgetDenied("duplicate_key")
        self._next += 1
        return f"rid-{self._next}"

    def settle(self, rid: str, actual_micro: int) -> bool:
        if any(existing == rid for existing, _ in self.settled):
            return False
        self.settled.append((rid, actual_micro))
        return True

    def mark_unknown(self, rid: str) -> None:
        self.unknown.append(rid)
