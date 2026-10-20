# Fleet project jobs

The four Daily Cloud work bindings (`philadelphia`, `backend`, `prospect-radar`,
`outreach`) use the existing `subagent_batches` / `subagent_batch_items` rows.
They do not create a client registry, client task queue, or scheduler. Marketing
Chief remains the canonical client queue writer. A caller supplies an existing
safe source reference; the reference is provenance metadata and does not grant
permission to read credentials or mutate the source system.

## Admission and readback

An authenticated caller with `fleet:work` submits to
`POST /api/fleet/work/batches` with existing batch fields plus both `project` and
`source_ref`. `source_ref` is a bounded identifier containing letters, numbers,
dots, underscores, colons, slashes and hyphens; no raw secrets belong here. The
validator also rejects `..` and doubled slashes so a later owner adapter cannot
mistake a traversal-shaped string for a canonical source. The
submission must name an existing thread owned by the caller's active
organization storage principal. A missing, foreign or unowned thread is
rejected before enqueue; project rows with null organization IDs are not
created. The
project-scoped submission key is hashed to fit persistence limits. Replaying a
key in the same project returns the existing batch; callers must read it back,
since the existing repository's idempotency contract returns the first accepted
payload rather than comparing all retry content.

Project jobs persist `output_policy=draft-only` in execution metadata. Host
claims include the project and output policy, and the host checkpoint retains
those safe fields with its existing claim identity. The proposal worker is not
an authority to send, publish, change budgets or write the canonical queue.
Claude workers run one turn with an empty tool list and strict MCP configuration.

An optional `client_id` binds a private Haiku project job to exactly
`client-operations-canonical:client/<client_id>` in `source_ref`. Gateway
requires an active imported registry row, a current organization owner/admin
or client assignment for the authenticated actor, and a real thread owned by
the organization's storage principal. The imported roster is an admission
index, not a live substitute for the canonical file: the host broker re-reads
the canonical client's current active status for each metadata read. Missing
organization, import, assignment, thread, or exact source binding denies.
Client-scoped project submission keys include the client ID; existing
non-client project replay keys keep their previous hash format.

Only an active internal `fleet:work` delegation may claim work. The claim
query filters by its validated storage owner and organization, so one host
cannot receive another owner's prompt. Native executor claims retain their
existing partition. Renew, running, finalize and release also join the item
to its batch and require that same delegated storage owner and organization
before applying the lease-owner fence. A client-bound claim carries only its safe client/source
identifiers as routing hints; these are not authorization proof. After the
host marks the item running, `GET /api/fleet/work/{item_id}/client-lease`
re-reads the joined durable item/batch rows on every call. It requires the
same internal delegation, exact lease owner, running status, unexpired lease,
no cancellation, batch owner/organization, private Haiku executor and
draft-only canonical binding. Its small response contains only the fields
needed by `VerifiedLease`; prompts, results and credential values are absent.
The host must invoke this endpoint before each broker admission/read. A host
UUID per claim is still required; a server-issued lease generation is not yet
present.

The optional `ultrafast` lane is public/synthetic only. Gateway submission
admits at most 16,000 UTF-8 prompt bytes per item, 4,096 output tokens and
one attempt, with a default of one attempt. Claims expose `max_attempts`, and
legacy Ultrafast rows with a different durable value are not claimed. The
Windows host must also reject such a row; an uncertain paid call is never
retried implicitly. After an Ultrafast item is marked running, the repository
refuses `/release` and leaves its attempt and lease intact; expiry or a
fenced finalize then yields the terminal result.

- `GET /api/fleet/work/projects` returns the four bindings and explicitly reports
  `schedule_active=false`.
- `GET /api/fleet/work/projects/{project}/batches/{batch_id}` requires the stored
  owner and matching project, and returns durable progress/counts.
- `POST /api/fleet/work/projects/{project}/batches/{batch_id}/cancel` applies the
  existing durable cancellation. It does not require a native worker service to
  be enabled. The cancel invalidates host leases; the existing host renew loop
  stops the running subprocess and discards results after lost ownership.

The standard thread batch items/result routes remain the detailed result read
surface. Quiet hours and protected launchers remain enforced by the host runner.
No recurrence is activated by this change: the existing owner must submit a
bounded occurrence after checking its current source bookmark and preferences.

## Verification and deployment gates

`tests/test_fleet_project_jobs.py` exercises the four durable bindings,
replay, reconstruction, cancellation and project isolation. The synthetic
`tests/test_fleet_client_lease.py` uses real organization middleware,
delegations and SQLite rows to prove owner/client admission, two-org claim
and mutation isolation, exact client source, scoped verifier access, expiry, reassignment,
cancellation and no prompt/result leakage. These offline tests do not prove
deployed host-to-Gateway integration, production lease concurrency or CSRF.

Before enabling always-on operation, independently verify the deployed Gateway
identity, real internal-token/delegation scope and CSRF path, production route
readback, synthetic provider-to-terminal readback, reboot recovery, per-source
bookmarks, source re-check, result acceptance and recurring owner binding.
Windows Ultrafast transport currently has its own route; this controller change
does not claim it is a fleet executor lane. Client credential resolution and
multi-tenant rate/capacity controls remain separate acceptance gates.

## Desktop lane (MomoBot desktop bridge)

`lane: "desktop"` queues a prompt for a Mac host running
`scripts/momobot_desktop_runner.py` (`claude -p ... --model haiku`, limited to the
client's folder). Submit with `client_id` and `requester` (a Slack user ID), no
`project`. Private data is allowed, `max_attempts` is always 1, and the
`execution_spec` stores `requester`, `client_id` and `approval_state`.

- **Roster gate.** Submit is refused (403) unless the `roster` config
  (`deerflow/config/roster_config.py`, `scope_for`) lists the requester for that
  client. An empty roster denies everyone.
- **Approval.** New desktop batches are `approval_state: pending`.
  `claim_items` skips pending batches; `POST /api/fleet/work/batches/{id}/approve`
  (org owner/admin, `approvals:write`) flips it to `approved`. Repeat approvals
  are no-ops. Other lanes report `approval_state: none`.
- **Runner.** Polls outbound, honors a STOP file and the quiet-hours gate
  command, kills claude after 20 minutes, and reports through the standard
  running/renew/finalize routes. `--dry-run` prints gates and the command only.
  Env vars and the client-folder mapping are in the script's docstring.
- **Slack.** `channels.slack.reply_in_thread: false` posts replies top-level
  (and skips the "Working on it" thread reply; the eyes reaction remains).
