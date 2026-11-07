# Northwind extension boundaries

- This independent package uses `deerflow_extension_api`, FastAPI, Pydantic, and
  the Python standard library. Production code must not import `app.*` or
  `deerflow.*`; the test-only host CSRF integration may import the actual Gateway.
- `northwind_placement/api.py` owns routes and business gates; `models.py` owns bounded
  input validation; `store.py` owns SQLite transactions, idempotency, and audit.
  `static/` is the API-backed dashboard. Keep its contract in sync with the API.
- Resolve identity using the public extension resolver. Require host-stamped
  session auth, the exact configured organization, and an explicit user allowlist.
  Only configured confirmer user IDs can confirm a move-in. Never trust a request
  name, header, checkbox, or storage-owner identity as Jordan's authority.
- Avery and Jordan share the configured organization/workspace database. Keep
  audit actors and retry keys actor-specific. Cross-organization and unlisted
  access fails closed. Preserve the host CSRF and membership checks.
- Persist source replay receipts, contact suppression, drafts, fee receipts,
  and audit in the private data directory. Case records never enter persona
  memory, the client registry, or the agency queue. No deletes or destructive
  migrations are in scope.
- Directory capacity is not vacancy. Availability expires. A proposed tour is
  not a calendar booking. The application performs no external side effect;
  do not add sender, calendar, billing, model, or provider calls under a misleading
  manual-record endpoint.
- Invoice and collection receipts remain distinct from a signed contract.
  Use integer cents and the Florida business date. Do not silently apply a
  discount, fee percentage, refund, or walkthrough-value option.
- Tests use synthetic data and the existing backend environment. Verify the
  affected HTTP flows, restart persistence, and auth/CSRF gates after changes.
  Run Ruff check and format before handing the package to the parent reviewer.
- `build_test_app` is a test fixture only, never a deployable authentication route.
  Installing/activating this extension and granting actual user membership are
  separate deployment actions; this package does not provision them.
