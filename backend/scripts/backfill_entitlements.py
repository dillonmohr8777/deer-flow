#!/usr/bin/env python3
"""One-shot operator script: backfill ``organization_entitlements`` rows.

Design ``docs/momo-week/m4-entitlement.md`` §4 step 2 (task ``f57``): before
``entitlements.enabled`` can flip to ``true``, every organization needs one
``active`` row per gate key in §5's minimum set, plus a limit row for any
``*.max``/``monthly`` key that has a configured default (``config.yaml ->
entitlements.default_limits``). The actual ceiling numbers are Dillon's call
(design §7.1, open question) -- this script never guesses one: a limit key
with no configured default is simply left alone (missing row = limit 0,
today's already-denied behavior, unchanged until a number is set).

Idempotent: an existing row, whatever its source, is left untouched, so a
manual edit or a prior run of this script is never clobbered. Non-destructive:
nothing is deleted.

Usage::

    python scripts/backfill_entitlements.py [--dry-run]

Requires ``database.backend`` to be ``sqlite`` or ``postgres`` in config.yaml
(the same database the gateway uses).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from deerflow.config.app_config import get_app_config

logger = logging.getLogger("backfill_entitlements")

# Design §5's minimum gate-key set -- every organization gets these "on"
# until billing exists (no billing provider yet = every active member can do
# everything, contract §2's single-owner-org rollout).
GATE_KEYS: tuple[str, ...] = (
    "console.read",
    "runs.create",
    "runs.cancel",
    "agents.manage",
    "schedules.manage",
)

# EntitlementDefaultLimitsConfig field name -> organization_entitlements key.
LIMIT_KEY_FIELDS: tuple[tuple[str, str], ...] = (
    ("projects_max", "projects.max"),
    ("workflows_max", "workflows.max"),
    ("brands_max", "brands.max"),
    ("repair_minutes_monthly", "repair_minutes.monthly"),
)


async def backfill_organization(repo, organization_id: str, default_limits, *, dry_run: bool) -> tuple[int, int]:
    """Backfill one organization's rows. Returns ``(created, skipped)``."""
    created = 0
    skipped = 0

    for key in GATE_KEYS:
        if await repo.get(organization_id, key) is not None:
            skipped += 1
            continue
        created += 1
        logger.info("%s org=%s key=%s -> active gate", "[dry-run] would create" if dry_run else "create", organization_id, key)
        if not dry_run:
            await repo.upsert(organization_id, key, source="manual", status="active")

    for field_name, key in LIMIT_KEY_FIELDS:
        limit_value = getattr(default_limits, field_name)
        if limit_value is None:
            logger.info("org=%s key=%s: no entitlements.default_limits.%s configured, skipping", organization_id, key, field_name)
            continue
        if await repo.get(organization_id, key) is not None:
            skipped += 1
            continue
        created += 1
        logger.info("%s org=%s key=%s -> limit %d", "[dry-run] would create" if dry_run else "create", organization_id, key, limit_value)
        if not dry_run:
            await repo.upsert(organization_id, key, limit_value=limit_value, source="manual", status="active")

    return created, skipped


async def _list_organization_ids(session_factory) -> list[str]:
    from sqlalchemy import select

    from deerflow.persistence.organizations.model import OrganizationRow

    async with session_factory() as session:
        result = await session.execute(select(OrganizationRow.id))
        return [row[0] for row in result.all()]


async def run_backfill(config, *, dry_run: bool, session_factory=None) -> int:
    """Backfill every organization. ``session_factory`` is test-only injection."""
    from deerflow.persistence.entitlements import EntitlementRepository

    if session_factory is None:
        from deerflow.persistence.engine import get_session_factory, init_engine_from_config

        await init_engine_from_config(config.database)
        session_factory = get_session_factory()

    if session_factory is None:
        logger.error(
            "database.backend is %r; this backfill needs 'sqlite' or 'postgres' (the same database the gateway uses).",
            getattr(config.database, "backend", None),
        )
        return 1

    organization_ids = await _list_organization_ids(session_factory)
    if not organization_ids:
        logger.info("No organizations found -- nothing to backfill.")
        return 0

    repo = EntitlementRepository(session_factory)
    total_created = 0
    total_skipped = 0
    for organization_id in organization_ids:
        created, skipped = await backfill_organization(repo, organization_id, config.entitlements.default_limits, dry_run=dry_run)
        total_created += created
        total_skipped += skipped

    logger.info(
        "%s%d organization(s): %d row(s) %s, %d already present.",
        "[dry-run] " if dry_run else "",
        len(organization_ids),
        total_created,
        "would be created" if dry_run else "created",
        total_skipped,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="List what would be written without writing to the database.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = get_app_config()
    return asyncio.run(run_backfill(config, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
