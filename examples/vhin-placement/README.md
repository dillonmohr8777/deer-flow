# VHIN placement operations

This is an installable MomoBot extension with a working HTTP API, an authenticated
dashboard, and durable SQLite records. A coordinator and the owner can work on the same
placement cases within one explicitly configured MomoBot organization. Only the
configured owner (confirmer) user ID can confirm a move-in. Installing source does not
create accounts, memberships, calendar connections, message senders, or charges.
The host admits only the extension's reviewed read and manual-record paths for
client accounts. An enabled plugin still checks the exact active organization,
configured user allowlist, session authentication, CSRF and owner authority.
If a trusted TLS proxy loses its original scheme, set `GATEWAY_CORS_ORIGINS` in
the operator environment to the exact public HTTPS origin before release. The
production overlay passes it through; an empty value adds no origins and `*`
does not authorize browser auth. Never use a wildcard to repair login.

The implementation is deliberately manual and draft-only. Intake can be recorded
and reconciled, community availability can be human-verified, and tours can be
proposed. Invoice and payment receipts can be recorded after their actual external
events. No endpoint sends messages, books a calendar, issues an invoice, charges a
card, or calls a model/provider.

Refreshing records, including after a saved change, clears the Top 3 results.
Run Top 3 again to use current availability, contract status, and owner ratings.
Responses from a lookup started before the refresh cannot restore old results.

## Install in the existing Gateway

Use the existing extension manager from the DeerFlow checkout, after reviewing
this package and verifying the intended organization/user IDs:

```sh
make extension-install SOURCE="$PWD/examples/vhin-placement"
```

Configure the installed plugin in the operator-controlled `config.yaml`:

```yaml
plugins:
  - name: vhin
    package: deerflow-vhin-placement
    use: vhin_placement:install
    enabled: true
    required: false
    config:
      data_dir: /persistent/private-data/vhin
      organization_id: VERIFIED_VHIN_ORGANIZATION_ID
      workspace_id: vhin-placement
      allowed_user_ids:
        - VERIFIED_COORDINATOR_USER_ID
        - VERIFIED_OWNER_USER_ID
      placement_confirmer_user_ids:
        - VERIFIED_OWNER_USER_ID
      # Optional: how unsent tour drafts are signed (placeholders when unset).
      advisor_name: OWNER_FIRST_NAME
      business_line: BUSINESS_CONNECTION_LINE
```

The built regulation corpus is read from `$VHIN_REGULATIONS_DIR` (set it on the
Gateway to a read-only data mount) or, for local work, from the package's
`regulations_data` folder.

These are placeholders, not provisioned accounts. `data_dir` must be an absolute,
persistent, private path mounted into the Gateway. Required IDs are explicit;
there is no allow-everyone default. The configured organization must match the
active, authenticated host workspace exactly. Every allowed user needs an actual
active memberships in that same organization. Restart the Gateway through its
normal deployment flow after installing/configuring an extension. This checkout
does not modify production configuration or restart a service.

Open `/api/vhin/dashboard/` while signed in to MomoBot. Every dashboard asset and
API route uses the same host identity gate. The package uses the public
`deerflow_extension_api.resolve_principal()` contract and host-stamped session
source/organization ID. Anonymous, auth-disabled, PAT, internal-service, wrong
organization, and unlisted-user requests fail closed. There is no standalone
production app with a test login or user-select header. Host CSRF middleware
remains enabled; the dashboard sends `X-CSRF-Token` from the host `csrf_token`
cookie for writes.

## Records and workflow

- A referral has `New`, `Qualified`, `Touring`, or `Placed` status. Qualification
  requires complete intake and an explicit human confirmation. `Touring` requires
  a proposed tour and human review; it does not mean a confirmed calendar booking.
  Placement is a separate, configured-confirmer action.
- Each source submission is immutable and replay-safe. The same `source_ref`
  and original data reuse the referral even under a new HTTP retry key. Reusing
  the source with changed data returns 409 for review. Phone/email matches within
  the configured workspace return 409 plus `duplicate_ids`; different families
  are never silently merged. A correction uses the existing referral and its
  `expected_version`.
- Missing intake fields remain visible. `attention` is `routine`, `urgent`, or
  `human_request`; flagged cases appear in the callback briefing with handoff
  explicitly `unconnected`. This records a human need without claiming a transfer.
- Community facts keep a source URL and observation timestamp. Licensed beds
  never become available vacancies. Human availability requires a source,
  verifier identity, timestamp, and expiry within seven days. Expired vacancy
  counts become `null` in current views.
- Follow-up is a stored draft. A reply, decline, or booking pauses it; stop
  suppresses it. Suppression persists across restart and contact edits, including
  the original contact identities. There is no automatic resume or send route.
- Tours remain `proposed`, with `calendar_connected: false`. Local overlapping
  proposals are rejected; adjacent slots are allowed. This does not read external
  free/busy or verify family/community confirmation.
- Move-in requires a signed agreement reference, signing date, recorded fee in
  integer cents, refund terms, and explicit `50_50_day30_day60` terms. There is no
  assumed fee percentage, discount, or walkthrough allowance. The odd cent, if
  any, goes into the second installment. Installment dates use calendar-day
  arithmetic; date-only checks and due reporting use `America/New_York`.
- Contracted fees come from signed-term records. Invoiced and collected amounts
  come from distinct manual receipt records; collections cannot exceed recorded
  invoices, and invoices cannot exceed the installment. Duplicate receipt
  references are rejected within each kind. A receipt reference is the operator's
  attestation of an actual external artifact, not a provider verification.

SQLite filenames are hashes of organization/workspace IDs. User IDs are retained
as audit actors, not used to split the coordinator and the owner into separate silos. Mutations,
retry receipts, and audit entries commit in one SQLite transaction. Data files are
mode `0600`; newly created parent directories are `0700`. The configured volume
and its backups must have the deployment's required access/encryption controls.
No case details enter persona memory, a global client registry, or an agency queue.
No deletion endpoint is exposed. The state response shows the latest 100 audit
events; the underlying journal and retry receipts retain earlier events.

- Owner's stars: once the owner contracts a community they rate it 1, 2 or 3. Stars never decide
  whether a fitting community appears; they break ties between equal fits and show on
  every pick. Only the configured confirmer can record a contract or a rating.
- Tour plans coordinate three parties (family, each community, the owner) for up to three
  communities. Drafts are stored unsent; community drafts never include the family's name,
  care needs or budget. A stop or decline closes open plans and removes family drafts.
  Replies are operator attestations (`source_ref`), not provider readbacks.
- Regulations: `<STATE>/corpus.json` holds verbatim primary-source text split into
  citable units, built by `scripts/build_regulations.py` from `sources.json` (official
  publishers only, SHA-256 per document). The built corpus and its mirror are bulk data
  and stay out of Git: build them into the deployment's data mount with `--out` and
  `--mirror`, and point the Gateway at the corpus with `VHIN_REGULATIONS_DIR`. Florida covers
  Rule Chapter 59A-36, F.A.C. (flrules.org) and Part I of Chapter 429, F.S.
  (leg.state.fl.us). Add a state by adding its `sources.json` and, for a new publisher
  format, one parser. The mirror (`<mirror>/<STATE>/`) holds the same text in pages under
  3,400 characters for chat agents whose fetch tool keeps 4,096 characters. Rebuild both
  when the publisher amends a rule; the corpus records its retrieval time.

## HTTP contract

All writes require `Idempotency-Key` (1–200 characters). Retrying the same key,
actor, path, and payload returns the original response; changing a key's input
returns 409. Keys are actor-scoped within the workspace. Reload `/state` after a
retry to see later edits, pauses, suppression, or expiry. Responses are `no-store`.

| Method and path under `/api/vhin` | Payload or result |
| --- | --- |
| `GET /state` | `referrals`, `communities`, `tours`, `placements`, `ledger`, `drafts`, `audit`, `connections`, `briefing`, `can_confirm_placement` |
| `POST /referrals` | `name`, `source_ref`; optional `phone`, `email`, `responsible_contact`, `location`, `budget_cents`, `care_needs`, `timing`, `contact_preference`, `attention` |
| `GET /referrals/{id}` | Referral, version, missing information, contact/handoff status |
| `PATCH /referrals/{id}` | `expected_version` and changed intake fields; source reference remains immutable |
| `POST /referrals/{id}/transition` | `status: Qualified\|Touring`, `human_confirmed: true` |
| `POST /referrals/{id}/contact-events` | `event: stop\|decline\|reply\|booking`, optional `note` |
| `POST /referrals/{id}/drafts` | `reason: incomplete\|no_booking\|missed_tour\|completed_tour\|planning`, `body` |
| `POST /communities` | `name`, `city`, `services`, optional `licensed_beds`, `source_url`, `observed_at` |
| `POST /communities/{id}/availability` | `vacancies`, `verified_at`, `expires_at`, `source_ref`, `human_confirmed: true` |
| `POST /tours` | `referral_id`, `community_id`, `start_at`, `end_at` |
| `POST /communities/{id}/contract` | Owner only: `status: not_contracted\|in_progress\|contracted`, `agreement_ref` (required when contracted), `human_confirmed: true` |
| `POST /communities/{id}/rating` | Owner only, contracted communities only: `stars: 1\|2\|3`, optional `note`; ending the contract clears the stars |
| `GET /recommendations` | Query `city`, `services` (comma-separated), `category`, `max_miles`, `limit` (1-3). Fit filters first; then confirmed openings, distance, and the owner's stars as a tiebreak. Each pick shows `owner_rating` and `checks_needed` |
| `POST /tour-plans` | `referral_id`, `community_ids` (1-3, visiting order), `options` (1-3 start times), optional `tour_minutes`, `travel_minutes`, `supersedes_plan_id`. Builds back-to-back stops and unsent drafts for the family, each community and the owner; one open plan per family |
| `POST /tour-plans/{id}/responses` | `party: family\|owner\|community`, `community_id` for a community, `response: accepts\|declines`, `option`, `source_ref`. Only the owner records the owner's reply. All parties accepting one option creates proposed tours marked `parties_confirmed`, still not booked |
| `GET /tour-plans/{id}/calendar.ics?option=N` | Tentative calendar file for the owner to import; community names and times only |
| `GET /regulations` | Loaded states, sources, retrieval time and unit counts |
| `GET /regulations/{state}/search?q=` | Ranked primary-source units with exact citation, parent context, official URL and effective date |
| `GET /regulations/{state}/unit?citation=` | One unit and its children by exact citation, for example `Rule 59A-36.006(1)(a)4., F.A.C.` |
| `POST /placements` | `referral_id`, `community_id`, `move_in_date`, `agreement_ref`, `agreement_signed_on`, `fee_cents`, `terms: 50_50_day30_day60`, `refund_terms` |
| `POST /placements/{id}/ledger` | `kind: invoiced\|collected`, `day: 30\|60`, `amount_cents`, `event_date`, `receipt_ref` |

Dates are ISO `YYYY-MM-DD`; timestamps must include an offset. All inputs reject
unknown fields. Money accepts integers only. The generated OpenAPI schema gives
field bounds and exact types. `briefing` separates `contracted_cents`,
`invoiced_cents`, `collected_cents`, and `due_cents`, and reports unknown costs and
handling time as `null`.

## Verify offline

From the repository root, use an existing environment with the declared dev
dependencies and the Gateway's dependencies. No dependency installation or Docker
build is necessary when using the existing backend environment:

```sh
PYTHONPATH=examples/vhin-placement:backend/packages/extension-api:backend:backend/packages/harness \
  python -m pytest examples/vhin-placement/tests -q
ruff check examples/vhin-placement/vhin_placement examples/vhin-placement/tests
ruff format --check examples/vhin-placement/vhin_placement examples/vhin-placement/tests
```

Tests are synthetic and offline. The Florida search tests run only when a built
corpus is present (`scripts/build_regulations.py FL`, or `VHIN_REGULATIONS_DIR`
pointing at one) and skip otherwise; a synthetic corpus covers loading and routes. They exercise HTTP identity/organization gates,
shared coordinator/owner records, persistence/retry across fresh app instances, source
replay, conflicting contacts, incomplete intake, stop and pause behavior,
availability expiry, tour conflicts, configured confirmation authority, signed
terms, exact money, local midnight, and the **actual host `CSRFMiddleware`**.

`tests/test_api.py:build_test_app()` is only a synthetic TestClient fixture and
browser-test adapter. Its fixed test identity must never be installed or served
as production authentication. `csrf=True` includes the real host middleware;
the identity itself remains a test stub.

Production admission remains separate: verify the intended host organization and
accounts, private persistent volume and backups, allowed-data arrangements,
the existing intake form source, the owner's confirmation role, and destination
readbacks. External calendars, family/community confirmations, messaging,
phone/handoff, provider invoice/payment reconciliation, shared review of community
fit, refunds, and alternative fee terms are not connected by this package.
