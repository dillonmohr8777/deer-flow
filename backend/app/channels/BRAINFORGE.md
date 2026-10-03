# Brain Forge: MomoBot's bounded Slack workflow

Brain Forge is an opt-in mode of the existing MomoBot Slack adapter in this
DeerFlow fork. It reuses the private cloud daily-brief implementation; it is
not another bot runtime, canonical queue, registry, or scheduler.

## First workflow

An authorized person requests `@bot brief` in an explicitly mapped channel.
The existing authenticated Slack transport admits only the configured team,
bot identity, allowed sender and exact channel-to-client route. It retrieves
the source thread with bounded pagination before proceeding. Historical
thread text is untrusted evidence, not permission or instructions. Incomplete
threads, mismatched identity, credential-shaped content and unresolved
bindings fail closed.

The workflow runs the existing deterministic brief build and protected
readback against reviewed SHA256 pins. It makes zero model calls. The private
artifact remains on the host; the Slack response contains recorded counts,
source version, freshness limitation and a receipt hash. Transport calls
still require a working, authorized Slack app binding.

The existing Chief remains the sole canonical queue writer. This mode cannot
mutate canonical data or reconcile sources automatically. Accepted canonical
sources and draft reconciliation candidates must remain distinct. Neither a
successful build nor a restored checkout establishes the latest operational
state.

## Operator configuration

Configure the existing `channels.slack.brain_forge` branch. This example is
deliberately disabled and contains placeholders, not usable identity or pins:

```yaml
channels:
  slack:
    # Configure existing transport secrets through the protected environment
    # or approved secret workflow. Do not paste them into chat or this file.
    brain_forge:
      enabled: false
      team_id: "<WORKSPACE_ID>"
      bot_user_id: "<BOT_USER_ID>"
      allowed_users: ["<AUTHORIZED_SLACK_USER_ID>"]
      channel_clients:
        "<CHANNEL_ID>": "<EXACT_CANONICAL_CLIENT_ID>"
      owner_user_id: "<SLACK_OWNER_USER_ID>"
      connection_owner_id: "<DEERFLOW_OWNER_USER_ID>"
      ledger_path: "/private/brainforge/transport.sqlite3"
      require_connection: true
      workflow:
        brief_source: "/reviewed/cloud-daily-brief"
        canonical_root: "/readonly/client-operations-canonical"
        artifact_root: "/private/brainforge/artifacts"
        brief_source_hashes:
          daily_brief.py: "<REVIEWED_SHA256>"
          checkpoint.py: "<REVIEWED_SHA256>"
          brief_items.py: "<REVIEWED_SHA256>"
        source_hashes:
          registry/clients.json: "<REVIEWED_SHA256>"
          queue/work-items.json: "<REVIEWED_SHA256>"
```

`require_connection` defaults to true. `owner_user_id` is a Slack identity;
`connection_owner_id` is the distinct backend owner identity. The authenticated
sender must resolve to that backend owner through the existing channel
connection mechanism; configuration alone does not grant membership. Review
identity and route bindings before enabling the mode. Bot membership and
thread-read access must cover the selected channel; administrator status is
not a substitute.

Keep the ledger and artifacts private and outside authoritative source trees.
The ledger stores dedupe, lease and delivery receipts, not a second work queue
or raw conversation archive. An uncertain delivery requires human readback;
it must not be automatically replayed. Output hashes and protected readback
prove the saved result, not across-host persistence.

## Verification and recovery

Restart recovery scans at most 100 queued or expired-claim receipts per page.
The cursor advances over held or changed-route rows without modifying them;
one coalesced drain follows additional pages even when the previous page ran
no workflow. Attempt-exhausted receipts are excluded before pagination. Each
eligible request still requires exact current route, requester, thread and
payload-hash readback before execution.

A single channel-owned timer wakes the existing drain at the next retryable
live claim's lease expiry. A restart before expiry therefore does not require
a new Slack message to recover that claim. Deadlines that expire during a scan
trigger a fresh sweep. Shutdown cancels the timer before draining workers and
closing the ledger. This is lease recovery, not a periodic channel scanner;
held and uncertain deliveries never create retry timers.

Run the focused `test_brainforge_*` tests from `backend/`, using the existing
test environment. Run a real pinned build/readback before transport rollout.
Changed source hashes block consumption: ask the existing source owner to
review and repin an accepted version; never pull, overwrite, or promote a
draft source automatically. Missing app credentials or owner connections are
binding failures, not permission to mint credentials.

Adding this source does not start a background runtime or provide a Slack
app binding. Unit tests, local adapter checks and same-family review are not
live Slack end-to-end signoff. Verify one authorized canary, its exact Slack
reply and private receipt before claiming delivery; a later unattended rollout
requires separate operational acceptance and the existing approval boundaries.

Keep deployment receipts, actual source revisions and hashes, workspace/user
identifiers, private repository references and client evidence outside this
public repository. Record them in the existing private evidence workflow.

## Unified private project

An optional `workflow.project` configuration joins the protected daily brief,
reviewed research handoff and native marketing/engineering workflow requests
in one private `project-<manifest-hash>.json` artifact. The workflow receipt binds
its hash together with the brief manifest. The Slack projection remains at most
six lines and contains counts, source limitations and the receipt hash.

The compiler uses the existing native workflow identifiers for research,
offers, SEO, social, CRM, reporting, developer dependencies and security review.
Export the catalog from the reviewed existing Momo source and pin the complete
JSON artifact; this source export does not prove the installed catalog. Each
reviewed lane packet contains only `clientId` and `inputs`. Its scope must equal
the requested exact client route; inactive and unknown routes are held. The
compiler applies the native closed input schema and prepares exact JSON bodies
and idempotency hashes for `/api/workflows/runs`. It does not call that endpoint.
Set `project.native_request_supervisor: false` when the reviewed installed API
accepts only `workflow_id`, `inputs` and `framework`; that mode preserves the
existing native maker/checker contract without claiming the later plan-review
supervisor. The default `true` prepares the newer four-field API request.
Missing inputs remain `needs_reviewed_inputs`; no facts, metrics or owners are
filled in to make a lane appear ready.

Supply `project.control` as a path/hash for `CONTROL.md` from the same canonical
root, `project.catalog` as a path/hash, and `project.inputs` as a lane-to-pinned-
packet mapping. `project.research`, when provided, supplies the existing reviewed
research CLI, absolute Node runtime, `source_root`, every JavaScript file's pin
in `source_files`, and the reviewed-evidence path/hash. The CLI runs with
`--no-network`, a restricted environment, a deadline and bounded output. Personal
research requests remain scoped to `__owner__`. Source changes before or during
compilation reject the result.

`project.collector.total_budget_usd` preserves the original one-time $16 pilot.
Its optional `ledger` is a reference to the original pinned ledger; missing
ledger identity remains unresolved and paid dispatch stays disabled. Never
create a replacement ledger, a new allowance or another scheduler. The model
route and serving acceptance are separate from deterministic project compilation.

Run from `backend/` against a private configuration file:

```sh
python -m app.channels.brainforge_cli preflight --config /private/project.json
python -m app.channels.brainforge_cli build --config /private/project.json --client-id __owner__
python -m app.channels.brainforge_cli verify --config /private/project.json \
  --receipt /private/artifacts/<job>/workflow-<hash>.json --expected-sha256 <independent-receipt-hash>
```

Local builds identify themselves as owner previews and do not establish a Slack
trigger. Verification reruns protected brief readback, checks artifact confinement,
and regenerates the project against the same pins before accepting saved bytes.
No transport, model, canonical write, live authentication or deployment is
performed by these commands. Runtime admission still belongs to the existing
owner, workspace scope, entitlement and reconciled finite allowance; accepted
output requires independent artifact review and terminal verification.
