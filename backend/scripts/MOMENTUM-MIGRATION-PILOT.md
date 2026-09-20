# Momentum migration pilot

This disposable SQLite fixture proves the first database-delivery acceptance path without client data or provider calls.

`scripts/momentum_migration_pilot.py` validates a fixed source schema, checkpoints every migrated row, resumes after a synthetic interruption, reconciles record and revenue totals plus a deterministic digest, returns segment analytics, makes identical reruns a no-op, and restores the exact pre-pilot target rows.

Run the acceptance check from `backend/`:

```powershell
uv run pytest tests/test_momentum_migration_pilot.py -q
```

This is pilot evidence, not authorization for a production database cutover. A production adapter still requires engine/version support, client-scoped credentials, backups, maintenance-window approval, and an independent operator review.
