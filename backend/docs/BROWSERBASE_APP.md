# MomoBot public Browserbase research

Status: source implemented and focused offline security tests passing. Actual provider evidence is recorded outside the repository in the release folder; read that receipt before claiming a live session succeeded. This adapter is deliberately a **public source text snapshot** workflow, not a general browser agent, account browser, live DOM scraper, or Stagehand `act()` integration.

## User-facing behavior

`/workspace/browser-research` accepts one to three public HTTPS pages. The server fetches their public HTML/text without cookies, credentials, proxy environment variables, forms, or scripts. Each redirect and DNS record is checked before the transport connects to an approved literal IP; TLS checks the original hostname. A real Browserbase cloud session renders escaped text in a new browser context with JavaScript, service workers, downloads, and all network requests disabled. Useful extracted text, a PNG snapshot, a full session ID, and an account-authenticated Browserbase replay URL become an owner-scoped receipt.

The screenshot shows the sanitized source snapshot, **not the original live layout**. This distinction is included as `source_mode: public_read_only_snapshot` in every page. Page content, including instructions embedded by a site, remains untrusted source data. It is not an instruction to MomoBot and does not automatically run any agent, model, or site action.

## Configuration and lifecycle

When enabled, the gateway owns one `BrowserbaseResearchService(path)` in `app.state.browserbase_service`, calls `await start()` in startup and `await aclose()` in shutdown, and includes `routers.browserbase_research.router`. Creation follows `runs:create` permission checks with the actual integration lane's `runs.create` entitlement gate when that subsystem exists. Only a fully absent subsystem on the old base permits compatibility passthrough; partial/invalid policy fails startup. Configured policy errors are never swallowed. The gate and offline denial evidence are documented in `OPENAI_AGENTS_APP.md`. Runtime credentials remain in a private ignored file or injected process environment:

```dotenv
BROWSERBASE_API_KEY=${BROWSERBASE_API_KEY}
MOMOBOT_BROWSERBASE_ENABLED=true
MOMOBOT_BROWSERBASE_MONTHLY_MINUTE_LIMIT=6000
```

Gateway startup checks the pure `BrowserbaseResearchService.enabled()` predicate
before constructing or starting this worker. When disabled, the real lazy status
accessor reports `not_enabled`, and admission/storage requests return503 before
creating a SQLite file, artifact directory, process lease, or provider request.
Ordinary multi-worker Gateway startup therefore stays available; a disabled
Windows installation does not import or require `fcntl`. The constructor itself
has no storage side effects. `tests/test_managed_provider_startup.py` exercises
overlapping real lifespans and authenticated status/admission/list requests,
including missing `fcntl`, with no provider storage or network access.

When *enabled* with `GATEWAY_WORKERS > 1`, this service is still
process-local: `start()` takes an exclusive `fcntl` lease on `path` (one
`BrowserbaseResearchService` per `base_dir`), so only the first worker to
reach it actually owns the SQLite store and provider session lifecycle.
Losing that race is expected, not an error — the worker logs it, leaves its
own `BrowserbaseResearchService` unstarted, and keeps serving every other
route; it never aborts that worker's Gateway lifespan. The unstarted
instance's `lock_contended` flag makes `/api/browserbase/status` report
`service_unavailable` directly instead of querying the provider from a
process that does not own the lease, and any admission/storage call lazily
retries `start()` (self-healing if the owning worker later exits) and
surfaces `service_already_running` as a 503 while the lease is still held
elsewhere. `MOMOBOT_WORKFLOWS_ENABLED`'s `WorkflowService` shares this same
exclusive-lease-per-`base_dir` pattern and the same non-fatal-loser startup
behavior (see `WORKFLOWS.md`). Keep `GATEWAY_WORKERS=1` for either feature
unless every worker shares the same `base_dir` on purpose and you have
accepted that only one worker actually runs it; running them under separate
`base_dir`s (one per worker) is not supported today.
`tests/test_managed_provider_startup.py::test_enabled_browserbase_survives_lock_contention_across_gateway_workers`
covers this path end to end.

The limit must come from current account-plan evidence, not a guessed public pricing tier. This owner's verified account plan has 6000 shared browser minutes, resets October 1, and supports 25 concurrent sessions; these observations are time-specific and are not a new purchase. The code requests no project ID: the latest Browserbase API infers the project from the key. No `BROWSERBASE_PROJECT_ID` is needed.

Python Playwright is required only as a CDP client. No local Chrome install or browser download is required. The gateway must use its existing single-process service lifecycle; background task ownership is local to that process, while receipts and idempotency live in SQLite. A restart fails interrupted jobs and releases their recorded provider sessions; it does not silently recreate a paid job.

`status()` lists all key-visible projects, reads every project's current `browserMinutes`, and sums them against the verified shared limit. If projects, usage, the limit, the key, or Playwright are missing or invalid, creation fails closed. A key limited to an incomplete project inventory cannot establish organization usage; use an organization-scoped key whose project list covers the quota-sharing organization. The current setup was checked through the authenticated account and live API. Every job rechecks usage before creating its provider session and requires at least three remaining minutes. Account-level usage can change concurrently outside MomoBot; this is a bounded admission check, not a provider billing lock.

Each owner has at most one queued/running job and three pages. The provider session has `timeout: 180`, `keepAlive: false`, no proxies or persistent contexts. A second owner job returns `owner_busy`. Creation is not retried when its outcome is uncertain; the required idempotency header reuses the existing persisted record. Provider release is requested on all paths after a session ID is received, and terminal status is read back. `session_closed: false` means cleanup was not confirmed and the configured TTL remains the backstop.

## HTTP contract

All endpoints use existing authentication and `runs:read`, `runs:create`, or `runs:cancel` permissions. SQLite ownership hashes authenticated actor + server-selected organization + storage principal. Shared workspace storage does not grant access to another actor's jobs.

`GET /api/browserbase/status` requires `X-Expected-User-Id` matching the current actor. It returns `owner_scope` plus `configured`, `available`, `reason`, `browser_minutes`, `monthly_minute_limit`, `remaining_minutes`, `mode`, and `limits`. All other routes require `X-Expected-Browserbase-Scope` matching that hash; stale/missing scopes return `409 workspace_scope_changed` before service access. Frontend query caches should use the same scope and discard previous content on account/workspace change.

- `GET /api/browserbase/research` returns `{data: [summary]}` for the current owner, newest first, capped at 100.
- `POST /api/browserbase/research` requires `Idempotency-Key` (1–128 characters) and `{urls: string[1..3], title?: string}`. The same owner/key/payload returns the same run; a changed payload returns `409 idempotency_conflict`.
- `GET /api/browserbase/research/{id}` resumes receipt polling.
- `POST /api/browserbase/research/{id}/cancel` requires `runs:cancel` and awaits cleanup.
- `GET /api/browserbase/research/{id}/pages/{index}/screenshot` returns owned PNG bytes with `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`.

Summary fields: `id`, `title`, `status`, `created_at`, `updated_at`, `last_error`. Status is `queued | running | completed | failed | cancelled`. Detail adds `urls`, `pages`, `session_id`, `replay_url`, `session_closed`, and `usage`. Page fields: `index`, `url`, `final_url`, `title`, `text`, `content_type`, `screenshot_url`, `source_mode`. Usage contains `browser_minutes`, `elapsed_seconds`, and `cost_usd`. Per-session billed minutes and money remain `null` because the source does not provide a confirmed per-run charge; elapsed time is measured wall time, not inferred billing.

Common errors: `provider_unconfigured`, `browser_dependency_missing`, `monthly_limit_unverified`, `organization_usage_unverified` (503); `browser_minutes_exhausted` (429); `owner_busy`, `idempotency_conflict`, `workspace_scope_changed` (409); `not_found` (404 for unknown or other-owner receipts); `private_network_blocked`, `secret_bearing_url`, `invalid_public_url` (400/validation422). Provider details, connect URLs, and secret-bearing exception text are never returned or persisted.

## Safety evidence and limits

A DNS preflight followed by ordinary remote browser navigation would not prevent DNS rebinding. Browserbase `allowedDomains` is experimental, permits subdomains, and only checks top-frame navigation; it does not constrain iframe/resources/XHR/non-HTTP schemes. This implementation therefore fetches with a pinned local HTTPS transport and sends only escaped text to the network-disabled cloud browser. It also rejects private/mixed DNS, multicast, mapped IPv6, NAT64 ranges, private 6to4, secret query names, custom ports, non-HTTPS redirects, oversized bodies, and nontext resources. This cannot visit authenticated sites or execute site workflows. Captchas and JavaScript-only pages may contain no useful source text.

Stored SQLite files and PNGs are mode0600; artifact directory mode0700. No same-origin HTML artifact is served. The receipt's replay URL identifies the actual Browserbase session and requires the user's existing Browserbase access; it is not a public share link. No live-control debugger URL or CDP connect URL is exposed.

## Documentation study

The finite exhaustive scope is the union of the current official Browserbase and Stagehand `llms.txt` catalogs and sitemaps, plus Browserbase's official `SKILL.md`. It excludes private/signed account pages and infinite arbitrary hyperlinks. On 2026-09-29/30, all **814 exact catalog URLs** were fetched successfully with bounded concurrency6 and two retries. HTML/Markdown aliases were preserved as separate URL receipts and reduced to **410 canonical full document texts** for synthesis. The corpus contains 4,026,788 characters, plus compressed original source bytes, hashes, fetch times, final URLs, and a durable URL ledger.

All 410 full texts, partitioned across three calls, were supplied to the user-requested exact `meta/muse-spark-1.3-contributor` model through the existing OpenRouter key. The provider reported Meta and the requested model for every call. Actual reported spend was **$0.1102053**, input tokens1,071,733, completion tokens15,160, under the preauthorized $0.50 cap. Full text supplied is not proof that every detail was independently verified or that bounded output contains every detail. `MUSE-STUDY.md` is a source-linked study aid; integration choices are checked against original official source snapshots and offline/live tests.

Evidence directory: `/Users/dillonmohr/Documents/Codex/browserbase-learning-20260929` (`url-ledger.json`, `corpus.jsonl`, `snapshots/`, `crawl-summary.json`, `MUSE-STUDY.md`, `muse-usage.json`). Live receipt directory: `/Users/dillonmohr/Documents/Codex/momobot-openai-app-release/browserbase-live-20260929`.

Primary sources: [Browserbase skill](https://www.browserbase.com/SKILL.md), [catalog](https://docs.browserbase.com/llms.txt), [Stagehand catalog](https://docs.stagehand.dev/llms.txt), [session creation](https://docs.browserbase.com/reference/api/create-a-session), [project usage](https://docs.browserbase.com/reference/api/get-project-usage), [release](https://docs.browserbase.com/reference/api/update-a-session), [allowedDomains limits](https://docs.browserbase.com/platform/browser/security/allowed-domains), [Stagehand v4 reference](https://docs.stagehand.dev/v4/reference/stagehand).

## Validation

TDD red: the new module import failed before implementation. Focused offline tests cover malicious URLs/DNS/redirects, escaped source handling, shared project quota aggregation, idempotency and uncertainty, cross-actor/organization access, scope fencing, permissions, screenshot headers, provider cleanup, cancellation, and interrupted-run recovery. Run `backend/.venv/bin/python -m pytest backend/tests/test_browserbase_research.py -q` and scoped Ruff. Live paid calls are excluded from tests and require explicit finite-run authorization.
