# MomoBot: production, app stores, and an agent fleet for every client

Written 2026-09-23 on top of the approved plan (Phases 1 to 3: cloud and SOC 2 baseline, "Momo already knows you" onboarding, design and usability). Owner: Dillon. Detail lives here; chat stays short.

## Phase 4: App Store and Google Play

**Web first, then a thin native shell.** The web app is the product. It's installable as a PWA; the `lane/mobile-pwa` lane adds the manifest, icons and safe areas. Apple rejects apps that are only a website in a frame (guideline 4.2), so the store builds wrap the same web app with Capacitor and add real native value:

- Push notifications through APNs and FCM for finished runs, approvals waiting and the morning brief. This extends `core/notification`, with a server-side push service and device tokens stored per user.
- Face ID and Touch ID unlock, with the session token in the iOS Keychain or Android Keystore.
- A share extension: share a link, photo or email from any app into a new Momo chat. This reuses the PWA share target design.
- An offline shell and cached recent threads (read only).
- Voice input. `voice-input-button` already exists on the web; use the native speech APIs.

**Store requirements checklist:**
- In-app account deletion (Apple 5.1.1(v)). The Phase 1 "account deletion" endpoint covers it.
- Sign in with Apple, if Google sign-in is offered (Apple 4.8).
- A privacy policy URL, terms, and App Privacy labels. Also Google Play's Data safety form.
- Disclosure and consent before personal data goes to third-party AI providers (Apple 5.1.2(i)). A one-time consent screen, recorded in the audit log.
- A demo account for App Review. The app is invite only, so the reviewer needs a seeded demo workspace.
- Age rating, support URL and email, crash reporting (Sentry), and a status page.

**Distribution.** MomoBot is invite-only B2B:
- **Apple:** Apple Business Manager custom apps, private per client organization, or an unlisted App Store listing. Both still go through review.
- **Google:** a Play private app via managed Google Play, or closed testing for the pilot.
- A public listing can wait.

**Accounts Dillon needs:** Apple Developer Program ($99 a year, Momentum as an organization, which needs a D-U-N-S number) and a Google Play Console ($25 once).

## Phase 5: hundreds of agents, one fleet per client

**Principle: templates, not hand-built agents.** An agent is a template plus a client binding plus that client's connectors, memory and budget. One template update rolls out to every client after it passes evals.

1. **Template library.** About 10 marketing roles to start:
   - weekly client report;
   - SEO, AEO and GEO visibility monitor (citation rate across ChatGPT, Perplexity and Google, from the research findings);
   - content drafts (blog and social);
   - ads health check (Google and Meta);
   - reviews responder;
   - local listings;
   - email campaign drafts;
   - analytics anomaly watch;
   - competitor watch;
   - client success check-in.

   Each has a SOUL, skills, allowed tools and MCP plugins, a default model (Muse Spark 1.3 contributor for bulk, Opus 5.5 for hard reasoning), a schedule, and acceptance criteria. Stored as versioned files in the repo, like `fleet/`, and installed through the agents API.
2. **Client binding.** Add `client_id` and `template_id`/`template_version` to custom agents. `AgentConfig` has no client field today. Agent memory, connectors and spend are all scoped to that client, using the `clients` model now in `lane/clients-model`.
3. **Connector vault per client.** Encrypted, least-privilege credentials per client for GA4, Search Console, Google Ads, Meta, HubSpot, WordPress and Slack channels. Read-only by default, and every use is audited. Existing MCPs cover most of these; the vault decides which client's credential a run gets.
4. **Budgets and entitlements.** M4 entitlements plus the M5 ledger, keyed by client: a monthly model spend cap per client, per-template run limits, and alerts at 80 percent. Business Intelligence shows spend and value per client.
5. **Scale the runtime.**
   - Postgres (in `lane/postgres-ready`).
   - `scheduler.multi_instance` with lease-based recovery (already built; it needs Postgres).
   - Several gateway workers behind the proxy.
   - A queue for long agent work: subagent batches and the MCP task runtime already exist.
   - Per-client concurrency limits.
6. **Quality at scale.**
   - An eval suite per template: fixture client data, expected outputs, and an Independent Verifier pass. This finishes the M6 16-run matrix.
   - Canary rollout: 1 client, then 10 percent, then all.
   - Langfuse traces on every run.
   - A weekly quality report: approval rate, edits needed, failures, time saved.
7. **People stay in charge.**
   - Everything client-facing lands in the approval inbox.
   - The autonomy dial per client and template (suggest, then act with notice, then auto) moves up only after a clean approval streak.
   - External sends, spend and publishing stay approval-gated.
8. **Rollout.** 3 pilot clients with 4 templates (weekly report, visibility monitor, content drafts, reviews). Then 10 clients with all 10 templates. Then every active client in the registry, all measured.

## Hosting options (waiting on Dillon's pick, 2026-09-23)

MomoBot needs:
- a server that can run Docker, because the agent sandbox runs there;
- Postgres;
- file storage;
- Cloudflare in front.

It doesn't need GPUs, an Oracle database or Azure.

**Hetzner reprice.** Hetzner raised its CCX and CPX lines 2.1x to 3.1x on 2026-06-15, blaming DRAM prices. The US only offers those two lines. Prices below were checked 2026-09-23 against the DigitalOcean pricing pages and CostGoat's Hetzner tracker (updated 2026-09-05). The Google Cloud row is still from memory.

| Route | Setup | ~$/mo |
|---|---|---|
| Lean, recommended under $150 | DigitalOcean in NYC: a Basic 8 vCPU, 16 GB droplet ($96), managed Postgres ($15 to $30), a small test droplet (~$12), nightly encrypted backups to Cloudflare R2, and Cloudflare Free | 125 to 140 |
| Most power per dollar, EU data | Hetzner in Germany or Finland: a CX53 with 16 shared vCPU and 32 GB (about EUR 29.50), Postgres in Docker (`compose.postgres.yaml`), a CX23 test server, and backups to R2. Data sits in the EU, about 100 ms from Philly | 45 to 50 |
| Enterprise | Google Cloud, already in the access registry: Compute Engine, Cloud SQL, Cloud Storage, Secret Manager, Cloudflare Pro, and paid Sentry and Langfuse. Unverified | 350 to 420 |

Hetzner US no longer beats DigitalOcean: a CPX42 with 8 shared vCPU and 16 GB is about EUR 70, with no managed database and 1 TB of traffic. A CCX33 with 8 dedicated vCPU and 32 GB is about EUR 139.

- **Monitoring:** the free tiers of Sentry, Better Stack, Langfuse and Cloudflare cover us at this size.
- **Oracle's free ARM tier** is a test box only.
- **Upgrade path:** start lean. Move Postgres to a managed service when paying clients need automatic failover. Move to the enterprise route when a client's security review requires it.
- **The cost that grows with the agent fleet is model usage, not hosting.**

## Suggested order after the current lanes land

1. Deploy the batch now in flight, rehearsed.
2. Phase 1 cloud and identity (MFA, Sign in with Apple and Google), because the app stores and outside clients both depend on it.
3. Agent templates and client binding: Phase 5 items 1 and 2, plus a 3-client pilot on staff-only access.
4. Push notifications and the Capacitor shell spike: Phase 4, TestFlight build for staff.
5. Connector vault and budgets: Phase 5 items 3 and 4, then open to pilot clients.
