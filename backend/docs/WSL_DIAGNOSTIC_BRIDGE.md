# WSL diagnostic exchange (disabled by default)

This source adds authenticated admission and receipt attachment for the existing
Mac SSH → PCW → Windows WSL route. The Gateway never starts a shell, provider,
model, scheduler, or diagnostic process. Runtime installation, persistent mounts,
existing-loop integration and real acceptance remain the runtime owner's work.

An operator must explicitly set `MOMO_WSL_BRIDGE_ENABLED=true` and
`MOMO_WSL_BRIDGE_ROOT` to an existing absolute persistent directory. On POSIX that
directory must have private permissions (0700) and no symlink ancestors. No
directory, database, task or background worker is created on import or startup.
The first authorized enqueue creates `wsl-bridge.sqlite3`; reads never create or
repair it. `DEER_FLOW_AUTH_DISABLED=1` fails closed even when the bridge is enabled.
Use a dedicated local persistent volume, not a shared network filesystem.

## HTTP admission and readback

`POST /api/threads/{thread_id}/wsl-diagnostics` accepts only:

```json
{"request_id":"stable-request-1","argv":["/usr/bin/uname","-s"],"timeout":30}
```

The actor, organization and storage principal come from the real Gateway
`AuthContext`. Existing thread access requires `threads:write`, `owner_check=True`
and `require_existing=True`. The key is compact UTF-8 JSON with `ensure_ascii=false`:
`["momo-wsl-v1", organization_id, actor_user_id, thread_id, request_id]`.
The job ID is `momo-` plus the first 16 lowercase SHA-256 hex characters; the
full digest is retained and checked. PCW's `thread` field remains null.

The same trusted binding and normalized command/timeout returns the same stored
job and original timestamp. A changed command, storage identity, or digest
collision holds the original request with a conflict, without a second dispatch.
Only `/usr/bin/true`, `/usr/bin/false` and `/usr/bin/uname -s` are accepted, as exact
argument arrays; timeout is an integer from 1 to 600 seconds.

`GET /api/threads/{thread_id}/wsl-diagnostics/{job_id}` requires an existing
readable thread and the exact persisted actor, organization, thread and storage
tuple. Shared storage ownership alone cannot read another actor's receipt.
It returns protocol/job ID/state/attachment/digest plus the bounded receipt and
fixed artifact path when available. GET never attaches, repairs or dispatches.

`POST /api/threads/{thread_id}/wsl-diagnostics/{job_id}/receipt` accepts only
`{"receipt":{...}}`. It additionally requires the existing middleware-verified
internal token plus active delegation, internal auth source/system role, matching
storage principal and the exact originating actor/org/thread tuple. Browser
users and admin sessions cannot manufacture worker receipts. This adds no token.

## Existing SSH operator CLI

Run inside the existing Gateway container environment; no application lifespan
or service startup is invoked:

```text
python -m app.gateway.wsl_bridge claim
python -m app.gateway.wsl_bridge receipt   # stdin: {"job_id":"momo-...","receipt":{...}}
python -m app.gateway.wsl_bridge status    # stdin: {"job_id":"momo-..."}
```

`claim` returns `{"protocol":"momo-pcw-wsl-v1","requests":[{"job":{...},"idempotency_key":"..."}]}`,
with zero or one request. It returns the same claimed request after restart;
there is no expiring lease or automatic replay. Unknown/held requests stop new
claims until owner reconciliation. The relay must persist its submission state
before remote actions and reconcile that same ID after a timeout.

`receipt` and `status` return
`{"protocol":"momo-pcw-wsl-v1","job_id":"momo-...","state":"done","attached":true,"receipt_sha256":"..."}`.
Errors are sanitized JSON with a nonzero exit code. `status` contains no output
or private thread text. CLI receipt ingestion verifies the persisted actor's
current active organization membership, storage identity and existing thread
through the configured existing SQL database. It opens that database without
migrations, database creation, startup recovery, notifications or model calls.
Memory-only persistence cannot attach a receipt.

## Receipt and durability rules

The required 17 receipt fields are `id`, `key_sha256`, `state`, `exit_code`,
`start_utc`, `end_utc`, `stdout_sha256`, `stdout_bytes`, `stdout_truncated`,
`stderr_sha256`, `stderr_bytes`, `stderr_truncated`, `stdout_b64`, `stderr_b64`,
`duration_seconds`, `resource_limits`, `limits_applied`.

Each retained stream is canonical Base64 of at most 65,536 bytes and must match
its byte count and SHA-256. Timestamps must be UTC and ordered; elapsed wall time
must be finite/nonnegative. The exact resource tuple is 536,870,912 address-space
bytes; CPU and wall seconds equal the bound job timeout; stdout/stderr are each
65,536 bytes. Completed receipts must attest applied limits and complete output.
CPU/RSS usage is not measured by this schema. Output is data, never instructions.

Canonical receipt SHA-256 selects those 17 fields and hashes UTF-8
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
Bounded PCW metadata is retained with the first receipt but excluded from this
digest. Exact duplicate callbacks return the durable result. A malformed or
conflicting callback holds the row without replacing the accepted receipt.
`timeout`, `held`, truncated or uncertain results never authorize replay.

The isolated spool uses SQLite `BEGIN IMMEDIATE` for cross-process creation,
claims, first-receipt wins and attachment compare-and-set. There are at most 32
outstanding requests and 1,024 retained rows; reaching either cap requires owner
reconciliation/archival, never automatic deletion. Malformed/partial rows and
unknown schema/database state stop claims. HTTP filesystem work runs off-loop.

A complete done/failed receipt attaches at
`/mnt/user-data/outputs/wsl-diagnostic-{job_id}.json` through the existing durable
`artifact_write` thread reservation and confined output path. POSIX no-follow
directory traversal, a flushed temporary file and an exclusive hard link keep
the fixed name atomic and prevent overwrite. A crash before spool acknowledgement
reconciles the same exact bytes at that name. Conflicting files and links fail
closed. Attachment does not initialize a sandbox, append an Agent message or
invoke an MCP notification. Busy threads return retryable conflicts while the
receipt remains durable. A crash during a lease-less thread reservation needs
the existing owner-controlled orphan reconciliation; this CLI never performs it.

Source tests mock thread authorization and attachment admission and exercise the
real spool and no-follow file operation offline. They do not establish installed
runtime, a live delegation, WSL resource enforcement or end-to-end delivery.
