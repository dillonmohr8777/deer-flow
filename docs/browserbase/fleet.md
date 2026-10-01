# Browserbase fleet integration

The existing manual runner now has an opt-in named-job adapter, a host-private
atomic ledger and scheduler-tick API. Nothing activates on import. No model call,
proxy, persistent browser context, client mutation or report login is introduced.

## Actual workflows

- `mobile_qa`: existing bounded transport and 390/768/1440 screenshots, status,
  overflow and measured target-size diagnostics. Not a full accessibility audit.
- `public_research`: same protected capture plus at most 12,000 text characters
  and 40 bounded link records in the private receipt. Sources are untrusted data.
- `local_draft`: client-scoped exclusive local JSON draft; never fills or submits
  a live website or CMS. Operator supplies fields in the private job manifest.
- `report_retrieval`: injection interface for an existing authenticated API reader
  accepting `(canonical_client_id, job_id)` and returning client-bound JSON <=1MB.
  Named-job callers can inject `report_reader`; the default agent/CLI does not have
  an authenticated connector and reports this precise blocker. Private portal
  fallback and persistent contexts remain unimplemented pending account bindings.
- `native_agent`: runs one provisioned Browserbase Agent configuration (the
  25 "Momo Browser" roles created 2026-09-30) on an operator-written task for an
  approved public URL. The job pins `agent_id`, `task`, `url`, `allowed_hosts` and
  `max_minutes` (1-15). The provider exposes no host allowlist for agent runs, so
  the fleet appends a fixed boundary (start URL, hosts, signed-out only, no forms,
  purchases, posts, messages or downloads) and never passes a context, proxy or
  Verified mode. Model tokens are billed provider-side and are not metered here.

## Admission and budget

Only operator-defined job IDs reach the tool. The private 0600 config pins the
canonical registry, explicit source-proven exact hosts, authenticated owner ID,
Browserbase project, output path and a shared SQLite ledger. Registry email
addresses are not treated as website provenance. Historical Align HCM is refused.
No Gateway database or canonical client queue is modified.

The account proof must identify a current billing cycle, expiration, independently
verified account-wide included usage and an enforced no-overage boundary. Missing
proof refuses cloud dispatch. Proof expires after 24 hours. Ceiling cannot exceed
50 browser minutes or the included allowance. Provider project usage is also read
before each dispatch and never treated as account-wide proof.

Each 60-second browser reserves 2 minutes before create; charged reservations stay
charged for that cycle even after confirmed release. Effective spend is conservatively
`max(initial_account_usage, refreshed_account_usage, provider_project_usage) + all_charges`.
This can double-count provider-reflected usage and stop early, intentionally.
A SQLite immediate transaction serializes reservation, concurrency <=2 and each
job's cadence >=1h across callers. Scheduler starts sequentially. Repeated named
tool dispatch cannot bypass cadence by changing the occurrence UUID.

`native_agent` reserves `max_minutes + 1` browser minutes and counts against a
separate operator-attested `account.agent_runs_included` (the plan's included
Agent runs per cycle; unset means zero, so native runs stay refused). It refuses
while any agent run in the account is PENDING, RUNNING or PAUSED, requests one
stop at the cap (or immediately on PAUSED, which holds a billed browser), and
records the run as uncertain if it is still not terminal three minutes later.
Failed polls are retried inside that bound, a failed stop is retried each poll,
and any fleet-side error after start requests a stop before re-raising.
`started.json` records the reservation and run ID first; an operator repairs an
uncertain row with `reconcile_native_run(api, ledger, token, run_id)` after the
provider shows the run terminal and its session in this project.
Every `start_agent_run` call sends only documented request fields (the "Run an
agent" reference lists no `metadata`, which is a sessions-only field): the
reservation token travels in `variables` instead. Whether the provider echoes
`variables` back in the AgentRun response is unconfirmed, so it is never the
only proof trusted. If `start_agent_run` itself fails (timeout, 5xx, an
ambiguous 4xx) or returns an unparseable run id, `started.json` is never
written, but the reservation is not permanently lost. An operator reads a run
id back from the provider directly (dashboard or API) and calls
`reconcile_unbound_native_run(api, fleet, token, run_id)`, which binds
ownership once the run proves it from documented AgentRun fields: either a
`variables` echo matching this token, or `agentId` matching the reservation's
own job -- read from the job's own config, never a caller-supplied argument,
so a run read back for the wrong job can't be laundered in by also passing its
agent id -- together with `createdAt` falling inside the window
`start_agent_run`'s own http client could still have been in flight: at or
after this reservation's own `created` time (minus clock skew) and at or
before `created` plus the request timeout (plus clock skew). `reserve()`
refuses a second reservation while this one is uncertain, and the
account-busy check refuses a start while any run is active, so at most one run
for this agent could exist in that window. A `variables` echo naming a
*different* reservation is treated as proof the run belongs to someone else,
and is refused outright even if its timestamp would otherwise fall in range.
A `createdAt` given in milliseconds, or as a naive (timezone-less) string, is
never guessed at -- both are refused rather than silently misread as seconds
or as the host's own local time. Elapsed time alone or an unauthenticated
guess is never accepted. A non-terminal run is never silently accepted
either: the call raises until the provider shows it done. A start call that
confirms the request itself was rejected (HTTP 400, before any run could
exist) settles the reservation as finished right away instead -- the charge
is kept, but there is nothing left to reconcile.
The run record, messages and any screenshot parts are saved privately. Through
the tool, a native run blocks until it ends (up to `max_minutes` + 3).

Ambiguous HTTP create/cancellation persists an uncertain reservation and stops
new cloud dispatch. No automatic retry, timeout refund or credit reset exists.
Creates carry a reservation ID in provider metadata. An operator can call
`reconcile_owned_session` after exact provider readback matches project, session,
reservation metadata and terminal state. This preserves the 2-minute charge.
If a session cannot be found, no safe automatic no-create conclusion is made.

## MomoBot wiring (prepared, not activated)

After existing runtime/deployment review, add only for owner-private approved agents:

```yaml
- name: browserbase_fleet_job
  group: browserbase-readonly
  use: deerflow.community.browser_automation.browserbase_fleet_tool:browserbase_fleet_job
```

Mount `BROWSERBASE_FLEET_CONFIG` with a private operator manifest and existing
`BROWSERBASE_API_KEY` through the runtime's existing protected secret route.
macOS CLI can reuse Keychain `browserbase.api-key`; Linux containers cannot read
macOS Keychain. Do not copy credentials into Git or plaintext example manifests.
Each invocation checks the existing authenticated enabled-system-admin boundary,
then matches the trusted actor to the manifest. No model-supplied identity or URL.
The complete named-job/scheduler lifecycle runs in a worker event loop, keeping
SQLite, filesystem, Keychain and browser work off the Gateway event loop.

Do not replace the existing process-local user browser tools or their CDP policy.
Set `enabled` only after account proof; set `scheduler_enabled` only after the same
proof and master runtime review. CLI dry run is always non-spending:

```sh
python -m deerflow.community.browser_automation.browserbase_fleet --config /private/operator-config.json --dry-run
```

The scheduler-tick API is ready for a trusted existing scheduler or reviewed local
launchd adapter. No launchd job, Gateway scheduled task or recurring model run is
created by this package. Keep private outputs outside Git. The report-reader host
binding, private portal context isolation and reviewed deployment are remaining
integration gates, not capabilities proven by offline doubles.
