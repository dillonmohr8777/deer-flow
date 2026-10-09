# Postgres migration rehearsal

Rehearsed for real on 2026-09-23 under Docker project `pgtest-pg1` (ports
2090-2099 range, `pgtest-` volumes/containers only). Live (`deer-flow`) and
rehearsal (`deer-flow-rehearsal`) stacks were never stopped, reconfigured, or
written to; the only read against either was a fresh, read-only
`backup_volume.py` snapshot of `deer-flow-rehearsal_gateway-data` into a new
`pgtest-` volume. Everything created for this rehearsal (containers, volumes,
network, the throwaway image) was removed afterward.

**Head has moved since.** This rehearsal ran at `0032_org_delegation_backfill`.
The integration branch is now at `0034_clients`, after the audit log (`0033`)
and client roster (`0034`) migrations. Re-run it against a fresh snapshot
before any live cutover.

## Receipt

**1. Source snapshot** (`backup_volume.py`, `deer-flow-rehearsal_gateway-data`
-> `pgtest-pg1-source-data`):

```
{"state": "PASS", "files_verified": 300, "bytes_verified": 3810579}
```

`data/deerflow.db` (the app's SQLite file) was already at alembic head
`0032_org_delegation_backfill`, 988 total rows across all its tables, 775 of
those belong to LangGraph's own checkpoint/store tables (`checkpoints` 344,
`writes` 426, `store` 0, `store_migrations` 5), which are out of scope for this
migrator (see `backend/scripts/migrate_sqlite_to_postgres.py`'s docstring).
The remaining 212 rows across 27 Alembic-owned tables are what got migrated.

**2. Migration** (`backend/scripts/migrate_sqlite_to_postgres.py`, target an
empty `postgres:16-alpine` from `compose.postgres.yaml`):

```
alembic upgrade: baseline -> 0032_org_delegation_backfill (32 revisions, clean)
table                       source    target  status
organization_members            10        10  OK
organizations                    9         9  OK
project_documents               94        94  OK
projects                         2         2  OK
run_change_clock                 1         1  OK
run_events                      58        58  OK
runs                            10        10  OK
threads_meta                    10        10  OK
users                            9         9  OK
subagent_batches                 1         1  OK
subagent_batch_items             2         2  OK
user_preferences                 4         4  OK
workspace_invitations             2         2  OK
(+ 14 more tables, all 0/0)
TOTAL                          212       212  OK
sequences reset: run_change_clock.id, run_events.id
```

Wall time: 22.9s (cold `uv run` interpreter/import startup dominates; the DB
work itself is sub-second at this data size).

**3. Verify** (`backend/scripts/verify_cutover.py`):

```
alembic head (this checkout): 0032_org_delegation_backfill
alembic head (source):        0032_org_delegation_backfill  OK
alembic head (target):        0032_org_delegation_backfill  OK
... (all 27 tables OK, 212/212 total)
project_documents: 94 source / 94 target rows
document hash digest (source): c4e6afa2245ca520818d891b68fc2dee24c9413e50ddfd3b965b15145ecd9aaf
document hash digest (target): c4e6afa2245ca520818d891b68fc2dee24c9413e50ddfd3b965b15145ecd9aaf  OK
PASS
```

Wall time: 23.5s (same cold-start cost as above).

**4. Gateway boot on the migrated Postgres:** `pgtest-pg1-gateway` reached
`healthy` (healthcheck is literally `GET /health/ready` -> expect 200; 5
consecutive `ExitCode 0` probes observed). Alembic revision read directly from
Postgres afterward: `0032_org_delegation_backfill`, which matches this checkout's
head with no drift from gateway startup.

## Finding: the shipped gateway image cannot run in Postgres mode yet

`deer-flow-gateway:momentum-m3b-20260923` (the image the live and rehearsal
stacks currently run) was built without the `postgres` extra --
`psycopg`/`asyncpg`/`langgraph-checkpoint-postgres` are not installed
(confirmed: `ModuleNotFoundError: No module named 'psycopg'` inside the
image). `backend/packages/harness/pyproject.toml` keeps these optional
(`[project.optional-dependencies] postgres = [...]`), and the Docker build
arg that pulls them in, `UV_EXTRAS`, defaults to empty in
`docker/docker-compose.yaml`. The step-4 gateway boot above used a throwaway
image built from this checkout with `--build-arg UV_EXTRAS=postgres`
(tagged `pgtest-gateway:postgres`, removed after the rehearsal) specifically
to prove the app code works against Postgres. **The live image itself is
not yet built with that flag.** This is the first thing a live cutover needs
from Dillon (see below).

## Live cutover runbook

1. **Fresh backup.** Snapshot `deer-flow_gateway-data` into a new volume with
   `backup_volume.py` (see "Back up" above). Keep it: it's the rollback
   path, untouched by every step that follows.
2. **Stop writers.** Stop the `gateway` container (`docker compose -p
   deer-flow stop gateway`, or the full stack) so nothing writes to the
   SQLite file mid-copy.
3. **Extract the SQLite file** from the fresh backup volume (same technique as
   this rehearsal: a `--network none` container copies `data/deerflow.db` to a
   scratch host path). Extracting from the *backup*, not the live volume,
   means step 2's stop is what makes the read safe, not the extraction step.
4. **Rebuild the gateway image with Postgres support:**
   `docker build --build-arg UV_EXTRAS=postgres -f backend/Dockerfile -t
   <new-tag> .` (redis stays always-on per the existing default). Tag it
   deliberately (not `momentum-m3b-20260923`) and update
   `MOMENTUM_GATEWAY_IMAGE` before starting.
5. **Migrate:** `python backend/scripts/migrate_sqlite_to_postgres.py
   <extracted deerflow.db> <postgres DSN>` against the Postgres from
   `compose.postgres.yaml` (started empty, `POSTGRES_PASSWORD` set in `.env`).
6. **Verify:** `python backend/scripts/verify_cutover.py <extracted
   deerflow.db> <postgres DSN>`; it must print `PASS` before continuing.
7. **Switch config and start:** `restart.ps1 -ExtraComposeFile
   deploy/momentum/compose.postgres.yaml -ConfigPath
   deploy/momentum/workspace.config.postgres.yaml` (with
   `MOMENTUM_GATEWAY_IMAGE` from step 4). Wait for `gateway` healthy.
8. **Smoke test:** both real logins, open a thread, confirm the Projects
   document list, confirm `/health/ready` 200 through nginx at the normal
   URL.
9. **Rollback, if anything in 5-8 fails:** stop the Postgres-config stack;
   start the stack again with the previous config
   (`workspace.config.yaml` + `compose.momentum.yaml`, no
   `compose.postgres.yaml`, previous `MOMENTUM_GATEWAY_IMAGE`) against
   `deer-flow_gateway-data`, untouched by steps 3-8, since the migration only
   ever *reads* the extracted copy. Rollback is "start the old config again,"
   nothing to undo.

## What live cutover needs from Dillon

1. **Approve rebuilding and re-tagging the live gateway image** with
   `--build-arg UV_EXTRAS=postgres` (runbook step 4), required before
   Postgres mode can start at all.
2. **A `POSTGRES_PASSWORD`** for `.env` (strong, generated; `compose.postgres.yaml`
   refuses to start without one).
3. **A maintenance window** for runbook steps 2-8 (gateway stop through smoke
   test); writers must be stopped before the SQLite file is safe to read.
4. **Confirm Postgres's own storage** (named volume `postgres-data`, on the
   same host disk as everything else here) is covered by whatever
   off-machine backup plan M0 already set up for `gateway-data`.
