# MomoBot app release and operator handoff

The private application is installed from `/Users/dillonmohr/code/_worktrees/momobot-openai-app-20260929`
on `codex/momobot-openai-app-20260929`. This document separates source validation,
bounded provider evidence, and the final installed runtime. A successful build or
HTTP response alone does not establish useful autonomous work or publication.

## Release record

The following records have independent read-back:

- Executable source commits: `584048ce` and `d000c549`; clean reviewed source, no provider keys/runtime state tracked.
- Final local production frontend build and 12 focused browser scenarios:
  **passed** (Webpack build plus OpenAI 3 / Browser research 3 / PWA 6).
  Chromium QA at `127.0.0.1:3040`, log `/tmp/momobot-final-e2e.log`;
  six additional real authenticated responsive captures and saved artifact read-back passed.
- Private gateway/frontend launchd jobs running with production authentication: **verified**.
- Authenticated tailnet8445 access: **verified**; anonymous workspace redirects to login and API returns401.
- Final macOS package: **built and installed**; installed hidden HTTPS login smoke passed. See `desktop/VERIFICATION.md`.
- iPhone Safari installation and authenticated useful output on the actual device: **manual device check pending**.
- Draft integration PR: [#109](https://github.com/dillonmohr8777/deer-flow/pull/109), targeting `lane/momo-week`; publication is not a merge or merged-tree deployment.
- Public hosting, GitHub publication/merge, Developer ID signing, notarization,
  and App Store submission: **not part of the private installed release**; draft source publication is recorded separately below.

## What is delivered

The authenticated Next.js app has `/workspace/openai` for the managed OpenAI
crew and `/workspace/browser-research` for public source captures. Both use the
existing password/MFA session and route permissions. The PWA adds iPhone
standalone metadata, exact existing icons, installation help, safe areas,
reduced-motion behavior, and a generic offline screen. It caches only public
offline assets; API results, workspace HTML, client records, and generated files
are not stored by the service worker. It does not run queued agents offline.

The macOS Apple Silicon app is an Electron shell for the same authenticated
workspace. Its isolated app session does not import browser cookies. It is not
a bundled backend or an embedded API key. The current shell has an ad-hoc
integrity signature, without Developer ID signing or notarization. Native
downloads support bounded same-origin artifacts, PNG and JSON with explicit user intent;
the authenticated web app also verified an actual saved artifact byte-for-byte.
Password/MFA login is presented within the workspace origin; browser SSO
does not transfer a completed session into the native app.

## Private setup

Use Node 24, pnpm 10.26.2, uv, and the locked Python backend dependencies. The
repository launcher is `scripts/run_momobot_openai_app.py`. Gateway secrets are
in the ignored regular `.env.local` file with mode 0600. Do not print, commit,
copy into the frontend, or place credentials in a URL. Keychain is not used by
this launcher.

The private state directory is `.deer-flow/private-app/`, containing the
authenticated `config.yaml`, `data/deerflow.db`, and `.jwt_secret`. These retain
the prepared account/session configuration; do not overwrite them with a
blank database, enable anonymous access, or regenerate the signing secret.
Private run databases and capture artifacts live under the configured app
data directory. Gateway services hold exclusive database leases, persist
admission receipts, and close/reconcile recorded runs during shutdown/restart.

Prepare each dedicated private state with the Gateway stopped:

```sh
backend/.venv/bin/python scripts/run_momobot_openai_app.py prepare-config \
  --state-dir /absolute/path/to/private-app \
  --expected-config-sha256 "$MOMO_REVIEWED_CONFIG_SHA"
```

Set `MOMO_REVIEWED_CONFIG_SHA` to the reviewed current `config.yaml` SHA256.
The operator-owned state directory must be mode 0700 and its regular config
mode 0600, with no symlink components; permission changes do not alter its SHA.
Preparation appends only a missing `run_events: {backend: db}` setting to an
existing SQLite configuration. It keeps an exclusive mode-0600 byte-for-byte
backup and atomically replaces the config; auth, signing secret, database path,
provider references and budgets are untouched. Explicit owner `run_events`
settings remain unchanged. Gateway startup rejects a missing section or a
`db` journal paired with a memory database; development defaults stay unchanged.
Previously completed pilots with memory run events retain their historical
receipts; preparation does not backfill or claim durable original event logs.

Required managed OpenAI variables are `OPENAI_API_KEY` and
`MOMOBOT_OPENAI_AGENTS_ENABLED=true`. Browser research requires
`BROWSERBASE_API_KEY`, `MOMOBOT_BROWSERBASE_ENABLED=true`, and a verified
`MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT`. An observed account-plan allowance
must be recorded before setting the last value; project usage alone does not
establish the account allowance. A new key, purchase, or raised provider budget
requires the owner's explicit authorization.

Build without supplying provider credentials to the frontend:

```sh
cd /Users/dillonmohr/code/_worktrees/momobot-openai-app-20260929/backend
uv sync --frozen --extra browser
cd ../frontend
pnpm install --frozen-lockfile
pnpm check
SKIP_ENV_VALIDATION=1 DEER_FLOW_ENV=production DEER_FLOW_AUTH_COOKIE_PREFIX=momo_agent_ \
  DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=http://127.0.0.1:8040 pnpm exec next build --webpack
```

The private launcher copies only a small non-secret environment allowlist into
Next.js. Gateway-only credentials are loaded from the private environment
file; production mode and authentication are enforced. It binds both services
to loopback. Run the two services separately, in background operator sessions:

```sh
cd /Users/dillonmohr/code/_worktrees/momobot-openai-app-20260929
backend/.venv/bin/python scripts/run_momobot_openai_app.py gateway \
  --state-dir .deer-flow/private-app --env-file .env.local
backend/.venv/bin/python scripts/run_momobot_openai_app.py frontend \
  --state-dir .deer-flow/private-app
```

The defaults are gateway `127.0.0.1:8040` and frontend `127.0.0.1:3040`.
`--gateway-port` and `--frontend-port` must agree across both launcher invocations.
Intended launchd labels are `com.dillon.momobot-openai-gateway` and
`com.dillon.momobot-openai-frontend`; both jobs are installed and their launchctl state is running. Never run a second worker against the same private agent
database. Provider keys stay on the gateway.

The verified private phone endpoint is
`https://dillons-mac-mini.tailade026.ts.net:8445/workspace/openai`.
Tailnet Serve on8445 proxies the authenticated loopback frontend. It is available within the owner's tailnet, with no Funnel on8445; existing443/8443/8444 routing remains unchanged. The installed native app's connection file targets this verified URL; the source fallback is loopback3040.

## Execution and safety behavior

Managed OpenAI uses released Python SDK 3.22.1, `client.beta.agents`,
`gpt-6.1-sol`, a small hosted sandbox, and at most three concurrent specialists.
Outbound sandbox networking and private application/browser/MCP tools are
disabled. Per-session admission is serialized and idempotent. A durable
120-second deadline makes one cancellation attempt; it is a best-effort time
bound, not a guaranteed token or dollar cap. Provider billing limits require
separate account read-back. Final-output presence is established from a
completed root turn and its persisted `final_answer`, rather than transport
success, commentary, or child completion.

Browser research allows at most three public HTTPS pages, one active capture
per owner, and a 180-second provider session. Public fetches validate every DNS
answer and redirect, pin the approved IP with TLS hostname validation, and
reject private destinations/credential-bearing URLs. The actual Browserbase
cloud browser renders escaped captured source text with network requests and
scripts disabled. The screenshots are **public read-only snapshots**, not the
original remote site's live layout. This does not expose Stagehand autonomous
actions, account sign-in, uploads, posting, or private-site automation.

Both surfaces pin actor identity on status and receive an `owner_scope` bound
to actor, organization, and storage principal. Subsequent operations must carry
that expected scope. Changed cookies/workspaces return 409 before provider or
business-storage access. Foreign owned records return 404. Query caches and
late mutation callbacks are scoped. Downloads are authenticated and bounded;
browser handoff alone is not proof that a file was saved. Missing usage or cost
remains unavailable, never zero.

## Evidence and validation

The bounded live OpenAI check preserved a completed root turn, two delegated
agent-creation events, a retrieved 1,431-byte `release-check.txt`, and reported
99,606 input / 1,552 output tokens. It checked arithmetic and mobile design
requirements without browsing or external actions. Its findings are a limited
workload, not an independently sourced accessibility audit. Actual billed
OpenAI cost is unavailable. Evidence:
`/Users/dillonmohr/Documents/Codex/momobot-openai-app-release/live-openai-evidence.json`
and `live-release-check.txt`. This validates that provider workload; it does
not by itself establish launchd/native/phone delivery gates; installed runtime
evidence below verifies the first two separately.

The Browserbase/Stagehand official catalog study preserved 814 distinct fetched
URLs and normalized 410 canonical full texts. All full texts were supplied to
`meta/muse-spark-1.3-contributor` in three bounded calls. Recorded provider cost
was $0.1102053, with 1,071,733 input and 15,160 completion tokens. URL/hash
read-back verifies source snapshots, not every model conclusion. Evidence is
in `/Users/dillonmohr/Documents/Codex/browserbase-learning-20260929/`:
`SUMMARY.md`, `MUSE-STUDY.md`, `muse-usage.json`, `source-integrity.json`, and
`backend-verification.json`. The corrected live Browserbase screenshot/closure
receipt is in `momobot-openai-app-release/browserbase-live-20260929/verified-20260929/`; early origin-validation failures
were released and must not be reported as successful captures.

Forty-eight consolidated frontend unit/DOM tests passed, including owner/workspace changes,
idempotent retries, unknown output, read-only permissions, URL rejection,
authenticated screenshot bounds, and artifact content-type rejection. OpenAI
router authorization/validation tests passed. Full frontend TypeScript and
full ESLint passed on the release source. Backend and desktop suites have
separate receipts. The final Webpack production build
passed, followed by all 12 focused Chromium scenarios: scoped fixture requests,
resumed evidence, a decoded PNG, downloaded JSON file read-back, failure/unknown
states, 390/768/1440 layouts, installation help, reduced motion, and public-only
offline caching. These are local fixture and PWA checks, not provider billing,
physical Safari, or deployment proof.

Run focused tests from the final source:

```sh
cd /Users/dillonmohr/code/_worktrees/momobot-openai-app-20260929/backend
.venv/bin/python -m pytest tests/test_openai_agents_service.py \
  tests/test_openai_agents_routes.py tests/test_openai_agents_sdk.py \
  tests/test_browserbase_research.py -q
cd ../frontend
pnpm exec rstest run tests/unit/core/browserbase tests/unit/core/openai-agents \
  tests/unit/components/workspace/browser-research.dom.test.tsx \
  tests/unit/components/workspace/openai-agent-room.dom.test.tsx
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3040 PLAYWRIGHT_SKIP_WEB_SERVER=1 \
  pnpm exec playwright test tests/e2e/openai-agent-room.spec.ts \
  tests/e2e/browser-research.spec.ts tests/e2e/pwa.spec.ts --workers=1
cd ../desktop
npm ci
npm run check
npm test
npm run smoke
npm run package:mac
```

All API-fixture Playwright tests block service workers so intercepted requests
cannot reach paid providers. The dedicated PWA suite explicitly allows workers
and checks public-only caching and offline API failure. Do not remove that
isolation to make a fixture test pass. Phone/tablet/desktop widths are 390,
768, and 1440, with 44px controls and reduced-motion checks; real Safari/device
QA remains a distinct gate.

On the iPhone, join the owner's tailnet, open the verified HTTPS endpoint in
Safari, sign in, and use Share → Add to Home Screen / Open as Web App. Installation,
password/MFA, and useful-output read-back on that physical device are user
actions. A prepared manifest or Chromium fixture does not prove iPhone installation.

## Repository contract reconciliation

The first full offline backend run recorded 19,198 passing tests and 45 failures
in `/tmp/momobot-backend-offline.log`; this result is not a green full-suite gate.
The auth/me, route-permission, PAT-scope and Board thread-ID failures came from
baseline Board/Team/Academy additions already present in `943fc338`, rather than
new Agents or Browserbase permissions. Their explicit expected permission sets
now include those six registered permissions. PAT scopes and its default-deny
route allowlist remain unchanged; the scope test verifies that Board, Team and
Academy scopes are rejected. Board's seven path handlers now validate the
existing canonical identifier format and join the runtime rejection sweep.
The final gateway guidance fits its unchanged 49,152-byte budget at 49,149 bytes.
The focused auth/me, route authorization, PAT repository/auth, thread-ID,
guidance and Board router suite passes **180 tests**, and scoped Ruff passes.
The subsequent complete backend run passed19,274 tests after the SDK transport
fixture and baseline contract repairs. Final safety revision results are recorded below.

## Final installed runtime evidence

`/Users/dillonmohr/Documents/Codex/momobot-openai-app-release/private-runtime.json` records authenticated actor/status/list/workspace200 read-back. The QA token was short-lived and held only in memory; it was not the user's password or a stored access credential. Anonymous access independently returned401 and `/login`. `installed-desktop.json` and `installed-desktop-smoke.json` record the installed signed bundle, secret-value ASAR scan, and actual hidden native HTTPS login verification. Full browser suite12/12 and consolidated new frontend unit suite48/48 pass. Browserbase corrected smoke produced a96,443-byte PNG,3,588characters source text, and independent completed-session read-back; its provider bill is unavailable. The original app on2026 remains untouched.

The first two mocked OpenAI browser checks unexpectedly reached the live API through the service worker. Both resulting turns completed (44 and12 output tokens), with exact receipts in `http-qa-sessions.json`; no provider cost was returned. Global fixture contexts now block service workers, while only the dedicated PWA cache tests opt in. Real test-provider transport boundaries additionally have offline DNS/socket guards.

The exhaustive public source catalog and Muse digest are saved in `BROWSERBASE_SOURCE_INDEX.json` and `BROWSERBASE_MUSE_STUDY.md`. The latter is model analysis of source snapshots, with per-partition limits, rather than verified operational claims.

## Authenticated useful output and final safety review

Only the deliberately verified OpenAI release task and Browserbase introduction capture were imported into the actual owner workspace; original QA databases remained byte-identical and import_event provenance was appended. `useful-output-readback.json` verifies actual signed-in HTTPS routes, two real delegate-creation items, the1431-byte artifact and96,443-byte screenshot. Six real authenticated screenshots at390/768/1440 are recorded in `authenticated-browser-qa.json`; no API mocks or new paid turns were used. The browser actually saved the artifact and byte-compared it with the verified provider file; thread-list API returned200 after the normal CSRF cookie was included. Setup selected the private workspace's balanced experience mode; the original deployment's preferences were untouched.

A restarted gateway loaded `d000c549`; `final-runtime-restart-readback.json` confirms authenticated Browserbase admission replay returned the existing run without a new cloud session, and actual OpenAI artifact bytes passed the new exact metadata-length check. Both launchd jobs remain running;8445 remains tailnet-only. The tailnet reported an online iOS peer, but physical Safari install/login/download is still a user-device check.

Final review fixed uncertain Browserbase session reservations (hold through possible180sTTL plus10s dispatch margin), disabled provider startup/storage/lease effects, and artifact metadata-length mismatch. The three paid admission routes bridge to the real `runs.create` entitlement policy on the newer integration lane and fail startup for a partial/malformed subsystem. The legacy installed base has no such subsystem; its existing auth/permission/scope gates remain required. Exact newer-lane policy tests rejected six missing/suspended grant cases before any provider call.

The final safety revision's complete offline backend suite passed **19,306 tests**, with194 skipped,20 deselected and57 warnings in581.55s. Strict blocking-I/O passed **156 tests**, with2 warnings in7.25s. Full frontend TypeScript/ESLint and production Webpack build passed;48 focused frontend unit/DOM checks,12 browser/PWA scenarios and17 desktop security/download tests passed. Focused final fixes also passed98 entitlement/router,40 Browserbase/startup,16 lifecycle, and52 OpenAI/SDK/storage/guidance tests (overlapping suites; do not sum).

Validation logs and SHA256 receipts are retained in `/Users/dillonmohr/Documents/Codex/momobot-openai-app-release/validation-logs/` and `validation-log-integrity.json`. Both provider credential values were checked against release logs and the complete feature diff without printing them; none were present. `final-runtime-health.json` confirms final executable source `d000c549`, both running launchd jobs, loopback-only ports, anonymous401/login gates, tailnet-only8445 and installed bundle integrity.

Draft [PR#109](https://github.com/dillonmohr8777/deer-flow/pull/109) targets `lane/momo-week`. Final mechanical merge checks were conflict-free against both live lane snapshot `d0b17c54` and GitHub's cached snapshot `982450d2`; the actual entitlement policy was unchanged from verified `9e97559c`. `final-integration-review.json` records both snapshots. Mechanical mergeability is not execution QA of the advancing integration tree. The installed workspace remains based on the reviewed isolated feature source; no integration merge or public distribution is claimed.
