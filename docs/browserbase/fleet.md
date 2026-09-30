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
  This instruction trailer is not a technical host/write restriction. Native
  agent jobs remain unactivated pending a reviewed provider capability boundary
  and current account evidence; deterministic QA retains its enforced request
  guard and is the preferred initial public-page executor.

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

`native_agent` reserves `max_minutes + 4` browser minutes (the three-minute stop
grace plus rounding margin) and counts against separate operator-attested
`account.agent_runs_included` and `account.agent_runs_used` values. The latter
must cover account-wide use, including runs outside this fleet. Unknown usage
refuses admission. Its cycle baseline and local charges are durable and remain
charged after termination and manifest job renames. Refreshed provider usage may
double-count local charges conservatively. It refuses
while any agent run in the account is PENDING, RUNNING or PAUSED, requests one
stop at the cap (or immediately on PAUSED, which holds a billed browser), and
records the run as uncertain if it is still not terminal three minutes later.
Failed polls are retried inside that bound, a failed stop is retried each poll,
and any fleet-side error after start requests a stop before re-raising.
The shared SQLite reservation transaction also permits only one active native
reservation across workers and billing cycles; a lagging provider list cannot
admit a second native run after the first moves to `running`. Deterministic QA
can still use the other generic concurrency slot when its admission passes.
The ledger binds the reservation to the exact provider run ID, agent and project
before polling or artifact writes. Polls cannot replace that run/session identity.
`started.json` mirrors this ownership; an operator repairs an
uncertain row with `reconcile_native_run(api, ledger, token, run_id)` after the
provider shows the owned run terminal and its exact session terminal in this
project. An unrelated run from the same project cannot settle the reservation.
Older uncertain runs without a durable run binding remain blocked; elapsed time
or a supplied run ID does not establish ownership. Normal completion also needs
this exact terminal session readback before the reservation can finish.
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
