"""M4 entitlement evaluator — one shared server evaluator (design §3, §7.3 of
``docs/momo-week/m4-entitlement.md``, task ``e6``).

Two kinds of key, distinguished by whether the caller passes ``current_usage``:

- Gate key (``current_usage=None``): allow iff a row exists with
  ``status="active"``. No row = no grant (fail closed), not "allow by
  default".
- Limit key (``current_usage`` given): allow iff
  ``current_usage + requested_amount <= limit_value``. A missing row (or a
  suspended one) is treated as limit ``0``, never "unlimited". The caller
  computes ``current_usage`` live from the owning table (mirrors how
  ``ClientRepository``/``BoardRepository`` always query live, org-scoped rows
  rather than trusting a denormalized count) — the evaluator itself has no
  opinion on what a key counts.

Degraded provider handling (design §3): a process-level cache keeps the last
successfully-read snapshot per ``organization_id``. An outage spans many
requests, so this is deliberately not a per-request cache. Once
``entitlements.grace_period_seconds`` has elapsed since that cached read,
every key fails closed except ``console.read`` (design §5: "leaving
export/account access available").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deerflow.config.entitlement_config import EntitlementConfig

logger = logging.getLogger(__name__)

# Keys that stay allowed through a degraded-provider outage even after the
# grace period elapses (design §5's export/account-access carve-out).
ALWAYS_ALLOWED_DURING_OUTAGE: frozenset[str] = frozenset({"console.read"})


class EntitlementRepositoryProtocol(Protocol):
    async def list_for_org(self, organization_id: str) -> list[dict]: ...


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    """The evaluator's answer for one (organization, key) check."""

    key: str
    allowed: bool
    limit: int | None = None
    used: int | None = None
    degraded: bool = False
    reason: str | None = None  # "no_organization" | "no_row" | "suspended" | "limit_exceeded" | "provider_error" | None


class _OrganizationSnapshotCache:
    """Process-level cache of each organization's last successfully-read snapshot.

    Keyed by ``organization_id``, not by request — see module docstring.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, dict]] = {}
        self._read_at: dict[str, float] = {}

    def store(self, organization_id: str, snapshot: dict[str, dict]) -> None:
        self._snapshots[organization_id] = snapshot
        self._read_at[organization_id] = time.monotonic()

    def get(self, organization_id: str) -> tuple[dict[str, dict] | None, float | None]:
        return self._snapshots.get(organization_id), self._read_at.get(organization_id)

    def reset(self) -> None:
        self._snapshots.clear()
        self._read_at.clear()


_cache = _OrganizationSnapshotCache()


def reset_entitlement_cache() -> None:
    """Clear the process-level snapshot cache. Test-only."""
    _cache.reset()


def _decide_from_row(row: dict | None, key: str, *, requested_amount: int, current_usage: int | None, degraded: bool) -> EntitlementDecision:
    if current_usage is not None:
        limit = row.get("limit_value") if row and row.get("status") == "active" else None
        if limit is None:
            limit = 0
        allowed = (current_usage + requested_amount) <= limit
        return EntitlementDecision(
            key=key,
            allowed=allowed,
            limit=limit,
            used=current_usage,
            degraded=degraded,
            reason=None if allowed else "limit_exceeded",
        )

    allowed = bool(row and row.get("status") == "active")
    reason = None if allowed else ("suspended" if row else "no_row")
    return EntitlementDecision(key=key, allowed=allowed, degraded=degraded, reason=reason)


def _degraded_decision(organization_id: str, key: str, *, requested_amount: int, current_usage: int | None, config: EntitlementConfig) -> EntitlementDecision:
    snapshot, read_at = _cache.get(organization_id)
    if snapshot is None or read_at is None:
        return EntitlementDecision(key=key, allowed=key in ALWAYS_ALLOWED_DURING_OUTAGE, degraded=True, reason="provider_error")

    elapsed = time.monotonic() - read_at
    if elapsed > config.grace_period_seconds:
        return EntitlementDecision(key=key, allowed=key in ALWAYS_ALLOWED_DURING_OUTAGE, degraded=True, reason="provider_error")

    row = snapshot.get(key)
    return _decide_from_row(row, key, requested_amount=requested_amount, current_usage=current_usage, degraded=True)


async def evaluate_entitlement(
    repo: EntitlementRepositoryProtocol,
    organization_id: str | None,
    key: str,
    *,
    requested_amount: int = 1,
    current_usage: int | None = None,
    config: EntitlementConfig | None = None,
) -> EntitlementDecision:
    """Evaluate one entitlement key for an organization.

    Pass ``current_usage`` (the caller's live count from the owning table)
    for a limit key; omit it for a gate key.
    """
    if config is None:
        from deerflow.config.app_config import get_app_config

        config = get_app_config().entitlements

    if not config.enabled:
        return EntitlementDecision(key=key, allowed=True)

    if organization_id is None:
        return EntitlementDecision(key=key, allowed=False, reason="no_organization")

    try:
        rows = await repo.list_for_org(organization_id)
    except Exception:
        logger.warning("entitlement provider read failed for org=%s key=%s; falling back to cached snapshot", organization_id, key, exc_info=True)
        return _degraded_decision(organization_id, key, requested_amount=requested_amount, current_usage=current_usage, config=config)

    snapshot: dict[str, dict[str, Any]] = {r["key"]: r for r in rows}
    _cache.store(organization_id, snapshot)
    return _decide_from_row(snapshot.get(key), key, requested_amount=requested_amount, current_usage=current_usage, degraded=False)


__all__ = [
    "ALWAYS_ALLOWED_DURING_OUTAGE",
    "EntitlementDecision",
    "EntitlementRepositoryProtocol",
    "evaluate_entitlement",
    "reset_entitlement_cache",
]
