# Upload ownership

This contract covers the Gateway HTTP upload route and project-document
attachment copies. It does not establish that every file writer uses a
reservation or that global privacy is complete.

## Durable operation admission

Uploads hold the durable, non-reclaimable `upload_write` thread operation through
staging, ingestion, and cleanup. Cancellation drains owned file work before
release. Unlike renewable run/artifact leases, it stays pending across expiry,
cancellation, takeover, and orphan recovery until the original file worker
drains. Generic store mutations, including snapshot, status, completion, and
delete paths, cannot retire or reassign it.

Only an atomic `release_upload_operation` predicate matching operation ID,
storage owner, original worker, held kind `upload_write`, and pending status can
release the reservation, after file work drains. Unsupported stores deny
admission and release. A crash or unconfirmed writer leaves a repair hold. Lease
expiry alone is not a safe repair signal: verify that no old file worker can
still publish before operator repair. Normal run and artifact recovery behavior
stays unchanged.

The upload request drains staging, ingestion, and cleanup before release. The
project-document attachment route repeats existing-thread ownership after
admission.

## Metadata reservation and finalization

Thread upload ownership is reserved in the existing metadata row before
ingestion opens any directory. `create(preserve_existing=True)` returns a
visible owned row unchanged. SQL primary-key arbitration (SQLite write
transaction; PostgreSQL unique insert) prevents another actor from taking a
missing ID. Memory uses its existing per-thread lock and remains
single-process.

A later `create(finalize_upload=True)` applies normal creation fields only to a
visible reservation, preserving owner, incarnation, and files; concurrent
retries return an already-finalized row unchanged. The internal reservation
value is bound to the server-generated incarnation, stripped from caller
metadata and all store metadata projections, and never appears in HTTP,
checkpoint, or LLM metadata.

Stateless runs reserve the same ownership before durable run admission. Checking
only before validation lets an upload win while admission yields. After
admission, SQL thread finalization rereads the reservation and revalidates its
existing project attachment; run metadata cannot change project membership. The
first run finalizes the reservation with admitted metadata and assistant plus
its existing validated project, while ordinary existing threads remain
unchanged.

## Rowless roots and rollout

Missing-row access and creation fail closed if either the scoped or old
unscoped thread root already exists, including uploads, outputs, workspace,
staging, empty directories, and symlinks. Do not inspect bytes to infer an
owner, relabel ownerless rows, or move/delete unknown uploads.

Replace every old upload writer before client uploads resume, or an old process
can still create rowless files. The native release owner inventories existing
rowless thread paths read-only, retains them as blocked unknown-owner data, and
investigates attribution separately. This source fix authorizes no automatic
migration or quarantine mutation.

Rollback retains rows and files and holds client upload traffic while any
vulnerable writer remains; reverting source alone reopens the original bug.
