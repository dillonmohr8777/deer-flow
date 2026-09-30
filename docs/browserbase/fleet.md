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
