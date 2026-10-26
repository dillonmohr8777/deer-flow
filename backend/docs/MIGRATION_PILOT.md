# Fixed-schema data assessment and recovery pilot

This extends the existing disposable SQLite lab. It accepts only the `customers`
to `momentum_accounts` contract in `scripts/momentum_migration_pilot.py`. It is
neither a general migration engine nor a production recovery service.

## Read-only assessment

Call `assess_source(path)` before a reviewed migration. It opens the source with
SQLite `mode=ro` and reports source, accepted and rejected counts. Accepted plus
rejected must equal source count. Duplicate IDs, missing text and invalid or
negative integer-cent amounts are rejected with row numbers and reasons. The
report omits names and field values. Missing required columns are an error, never
an empty successful export. Migration refuses rejected input before opening its
target. Rejected rows need an explicit mapping/data-owner decision; do not repair
them by inventing values or silently discarding them.

## Resume and recovery

Each applied row and its exact written value commit with the existing checkpoint.
A fresh process resumes from that checkpoint and reconciles counts, amounts and
digests. Source drift, a changed migrated row or a changed pending target row
stops the run for forward reconciliation.

Recovery now undoes only the unchanged writes actually made by this pilot. It
restores a replaced row's original value or removes a pilot-created row. Later
inserts and updates to unrelated target rows are preserved. If a migrated row has
changed, recovery refuses the whole operation under the SQLite writer lock,
preserving the row and checkpoint. Review that current row against the original
and expected applied value, agree the desired forward state with the data owner,
and prepare a separate reviewed repair. Never rewind a whole pre-cutover table
after writers reopen. Old checkpoints lacking applied-write evidence also hold;
their evidence cannot safely be reconstructed from the current target alone.

The `rollback_migration` return remains the final target-row count. It does not
promise restoration of database bytes or schema. This fixed-schema lab stores
one before snapshot and one active migration; it is not a live backup strategy.

## Reproducible acceptance

```sh
python -m pytest tests/test_momentum_migration_pilot.py -q
ruff check scripts/momentum_migration_pilot.py tests/test_momentum_migration_pilot.py
ruff format --check scripts/momentum_migration_pilot.py tests/test_momentum_migration_pilot.py
```

The synthetic checks cover interrupted/resumed/idempotent work; separate-process
resume; target-only insert/update preservation; changed migrated/pending rows;
missing legacy evidence; read-only assessment; input/output/reject counts; and
unchanged target bytes when invalid input is rejected. They use temporary files,
no credentials, external provider, production database or client information.
An exception in the first process is not a power-loss or hardware durability test.

## Bounded service handoff

Start with the already scoped read-only assessment of one to three authorized
databases. A source owner supplies the approved data contract, a human engineer
owns implementation, an independent checker reconciles outputs/rejects and tests
recovery, and the customer's process owner accepts the result. Those are required
roles, not assigned staffing or partner commitments. Record scope, schema, source
snapshot identity, row/reject counts, mapping decisions, target writer/fence
status, repair/recovery evidence and exact acceptance destination before action.

This lab supports preparation of that pack. Production authorization, access,
backup/restore/PITR, privacy, concurrency/scale, database-specific migration,
support owner and customer acceptance remain separate gates. No price, service
level, certification, partner delivery commitment or paid revenue is established.
