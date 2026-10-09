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

### Offline configuration preparation

Use the existing CLI from `backend/` to prepare a new private fragment. These
commands never merge into a live config, enable a channel, run the brief builder,
call a provider, provision credentials, or start a service:

```sh
python -m app.channels.brainforge_cli prepare \
  --brief-source /reviewed/cloud-daily-brief \
  --canonical-root /readonly/client-operations \
  --storage-root /private/brainforge \
  --out /private/brainforge/candidate.yaml
python -m app.channels.brainforge_cli check --fragment /private/brainforge/candidate.yaml
```

Optional `--bindings /private/bindings.json` accepts only `team_id`,
`bot_user_id`, `allowed_users`, `channel_clients`, `owner_user_id`, and
`connection_owner_id`. Supply exact non-secret IDs, not tokens or credentials.
Without this file, fields stay empty and the candidate is still written;
exit status **1** reports incomplete local configuration. Status **0** means
only that local fields and matching hashes validated. Rejected input, duplicate
JSON/YAML keys, unsafe paths, existing output, or drift return **2**. Reports
contain readiness flags and missing field names, never configuration values.

Prepared fragments set `enabled: false`, `require_connection: true`, and
`source_pin_status: candidate_unreviewed`. Hashes for the three brief modules and
two canonical files are captured candidates, not reviewed acceptance or a
latest-state claim. `check` reuses the workflow's pin validator without running
the builder and confirms exact active registry routes. An existing optional
`workflow.project` is preserved and validated through the current compiler.
New candidates allocate distinct artifact directories; no ledger is created.
Existing files are never overwritten. Output stays outside source trees;
symlink traversal is rejected. POSIX storage is private and the fragment is
created with mode 0600. Existing public directories are rejected, not chmodded.

This is a fragment for a reviewed merge into the existing configuration, not a
replacement for the complete config or `channels` section. It intentionally
omits Slack transport enablement, bot/app tokens, and `channel_connections`
settings. Preparation never performs that merge or changes saved runtime settings.

### Binding sequence and remaining host checks

After source review, use the existing normal Slack `/connect` flow while Brain
Forge remains disabled. `channels.slack`, `channel_connections.enabled`, and
`channel_connections.slack.enabled` must be configured on the existing Gateway
with persistent connection storage. Check effective configuration: saved
`runtime_config.json` settings can override or disable Slack after a YAML merge.
Unset `$ENV` references can fail the global config loader even in a disabled
branch; the generated candidate uses empty binding fields instead.

The identity connection alone does **not** provision a per-connection encrypted
access token. The reviewed host-only provisioning path must populate the
correct owner/workspace credential row. There is no new public provisioning
endpoint and no operator-token fallback. Both the channel worker and connection
router use the optional protected `CHANNEL_CONNECTIONS_ENCRYPTION_KEY`; use one
stable identical key across Gateway workers and restart them after key changes.
Without a key, repositories remain identity-only and Brain Forge fails closed
when bound credentials are unavailable. Do not regenerate a key to make an
existing encrypted row appear configured.

Offline `check` reports only environment-variable name presence for
`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `CHANNEL_CONNECTIONS_ENCRYPTION_KEY`;
it never reads or validates their values. Presence does not establish a valid
key, a usable encrypted token, live owner binding, Socket Mode connectivity,
persistent-host readiness, or a verified canary. Those remain explicitly
unverified until checked through the existing protected host workflow.

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

### Original pilot evidence

The server-selected `project.research.kind: original_x_pilot` alternative reads
the original bounded X pilot's saved proposal artifacts. It preserves the
existing JavaScript route when the kind is omitted or `reviewed_js`. Unknown
modes, mixed configurations and an `inputs.research` override in original mode
are rejected. The new adapter imports no original program and performs no
collection, financial-state operation, subprocess or model call.

Run the independently pinned original `marketing_signal_brief.build_brief`
separately, before compilation, using exact-hash page artifacts, a fixed UTC
observation time and a new private output directory. Save its returned producer
proof as a private JSON file. This upstream preparation writes only its original
brief/envelope artifacts. Do not invoke the collector, `Pilot` constructor or
status method to perform it. Missing original financial history must remain
missing; recovering code does not authorize initializing another ledger.

Configure only these original-mode fields, all selected by the trusted operator:

```yaml
research:
  kind: original_x_pilot
  producer_sources:
    marketing_signal_brief.py: {path: /reviewed/marketing_signal_brief.py, sha256: "<REVIEWED_SHA256>"}
    x_post_pilot.py: {path: /reviewed/x_post_pilot.py, sha256: "<REVIEWED_SHA256>"}
  profile: {path: /private/original-profile.json, sha256: "<REVIEWED_SHA256>"}
  proof: {path: /private/original-producer-proof.json, sha256: "<REVIEWED_SHA256>"}
  pages:
    - {path: /private/original-page.json, sha256: "<REVIEWED_SHA256>"}
  review: {path: /private/original-review.json, sha256: "<REVIEWED_SHA256>"}
```

Pins contain only `path` and `sha256`; paths must be absolute without symlinks.
Producer and profile fingerprints must match the original dillon-os PR447 commit
`5003cdaa1ef0171a2148592f15ff4d784c94c3d8`, recorded in the adapter's constants;
rebinding changed programs or a replacement profile does not admit another pilot.
The proof must have the original eight fields (`briefPath`, `briefSha256`,
`envelopePath`, `envelopeSha256`, `counts`, `readbackVerified`, `canonicalWrites`,
`modelCalls`) and bind the actual saved outputs, with zero writes/calls to the
canonical/model systems. The profile retains the original cumulative pilot and
post-read scope. Historical price metadata is not a current price or invoice.

The review is a closed JSON object with `kind: brain_forge_original_pilot_review`,
`pilot_id` matching the original profile, `accepted_for: owner_research_proposal`,
`proof_sha256`, `profile_sha256`, `producer_sha256` (both producer filenames),
`page_sha256` (ordered page hashes), `reviewed_by`, `reviewed_at`, `evidence_mode`,
`selected_post_ids`, and `research_question`. Its timestamp must follow the
source/proposal observations. The mode is `fixture` or `reviewed_public_subset`;
neither claims authenticated provider retrieval. The existing trusted operator
pins this reviewed file. Its contents are an attestation, not independent
authentication of a reviewer or automatic verification of the source's claims.

Whole selected posts must exist in the original pinned pages and findings.
The adapter preserves complete sanitized text, nullable publication/author
provenance, observation time, original source/program/output/review pins and
explicit omitted IDs in the private project. The original ranking excerpts and
URL-only envelope are not replacements for whole evidence. Native field limits
and the existing request-byte limit reject oversized batches without truncating
them; the reviewer must choose a smaller explicit batch. Zero selected findings
prepare zero research requests. Nonowner routes receive no personal evidence.

Compilation and saved-receipt verification remain deterministic readers and
recheck all pins after projection. They do not run the upstream producer or
change any artifact. The existing original allowance and uncertain holds remain
separate and unresolved until reconciled by their owner. Marketing lanes still
require separately reviewed exact client packets: keyword rankings cannot create
verified answers, approved claims, offers, actual leads or reporting metrics.
Native dispatch retains its normal owner/workspace, entitlement, budget,
supervisor and independent-check gates; this adapter only prepares a request.

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
