# Corpus partition 1

# MomoBot Integration — Source-Linked Learning Digest
**Corpus: Partition 1 of 3 — Complete canonical text supplied for this partition only**

> Scope limit: This digest covers **only** the documents listed in Partition 1. It does **not** prove behavior for Partitions 2-3, unlisted API versions, or live service behavior. No API was run. No secrets are included.

## 1. Product Families Represented in Partition 1

Partition 1 contains four overlapping families:

### 1.1 Stagehand v4 SDK — current SDK surface
Core reference is:

- `Stagehand` lifecycle + `act/observe/extract/metrics/experimentalBatch` — https://docs.stagehand.dev/v4/reference/stagehand.md
- Browser factories + Browserbase vs local — https://docs.stagehand.dev/v4/configuration/browser.md
- `BrowserContext` pages/cookies/headers/policy — https://docs.stagehand.dev/v4/reference/context.md
- Logging — https://docs.stagehand.dev/v4/configuration/logging.md
- `observe()` planning — https://docs.stagehand.dev/v4/basics/observe.md
- Migration v3→v4 — https://docs.stagehand.dev/v4/migrations/v3.md
- Quickstart — https://docs.stagehand.dev/v4/first-steps/quickstart.md
- Cost optimization — https://docs.stagehand.dev/v4/best-practices/cost-optimization.md
- Deployments on Vercel + Functions preview — https://docs.stagehand.dev/v4/best-practices/deployments.md
- User data — https://docs.stagehand.dev/v4/best-practices/user-data.md
- Integrations overview + agent frameworks — https://docs.stagehand.dev/v4/integrations/overview.md and https://docs.stagehand.dev/v4/integrations/agent-frameworks/overview.md
- Framework bindings: Eve, Deep Agents, Claude Code — https://docs.stagehand.dev/v4/integrations/agent-frameworks/eve.md , https://docs.stagehand.dev/v4/integrations/agent-frameworks/deep-agents.md , https://docs.stagehand.dev/v4/integrations/cli-agents/claude-code.md
- Application sample: Stripe + WebMCP — https://docs.stagehand.dev/v4/integrations/applications/stripe.md

v4 model is: obtain a `browser` handle from a factory, pass it to `Stagehand.create({browser})`, drive pages via `browser.context`, call AI primitives on the `Stagehand` instance, close both explicitly.

### 1.2 Stagehand v3 — legacy hosted API + SDK
Represented by:

- Agent with CUA/DOM/Hybrid — https://docs.stagehand.dev/v3/basics/agent.md
- Models + Model Gateway + Model Router `auto` — https://docs.stagehand.dev/v3/configuration/models.md
- Session API OpenAPI: `POST /v1/sessions/start`, `/v1/sessions/{id}/act`, `/observe`, `/extract`, `/navigate`, `/end`, `/replay`, `/agentExecute` — https://docs.stagehand.dev/v3/api-reference/python/start-a-new-browser-session.md , https://docs.stagehand.dev/v3/api-reference/python/perform-an-action.md , https://docs.stagehand.dev/v3/api-reference/ruby/observe-available-actions.md , https://docs.stagehand.dev/v3/api-reference/java/extract-data-from-the-page.md , https://docs.stagehand.dev/v3/api-reference/java/navigate-to-a-url.md , https://docs.stagehand.dev/v3/api-reference/go/end-a-browser-session.md , https://docs.stagehand.dev/v3/api-reference/ruby/end-a-browser-session.md , https://docs.stagehand.dev/v3/api-reference/java/execute-an-ai-agent.md , https://docs.stagehand.dev/v3/api-reference/java/replay-session-metrics.md
- Context, Locator, Extract, Observe, Response, History, Observability references — https://docs.stagehand.dev/v3/references/context.md , https://docs.stagehand.dev/v3/references/locator.md , https://docs.stagehand.dev/v3/references/extract.md , https://docs.stagehand.dev/v3/references/observe.md , https://docs.stagehand.dev/v3/references/response.md , https://docs.stagehand.dev/v3/best-practices/history.md , https://docs.stagehand.dev/v3/configuration/observability.md
- Prompting, evals, speed — https://docs.stagehand.dev/v3/best-practices/prompting-best-practices.md , https://docs.stagehand.dev/v3/basics/evals.md , https://docs.stagehand.dev/v3/best-practices/speed-optimization.md
- Python v2→v3 migration — https://docs.stagehand.dev/v3/migrations/python.md
- MCP, LangChain, Vercel, AI rules — https://docs.stagehand.dev/v3/integrations/mcp/setup.md , https://docs.stagehand.dev/v3/integrations/mcp/introduction.md , https://docs.stagehand.dev/v3/best-practices/mcp-integrations.md , https://docs.stagehand.dev/v3/integrations/langchain/configuration.md , https://docs.stagehand.dev/v3/integrations/vercel/introduction.md , https://docs.stagehand.dev/v3/first-steps/ai-rules.md

v3 is session-ID-centric: `sessions.start` returns `sessionId`, all later calls require that ID. Described as ALPHA in every OpenAPI block.

### 1.3 Stagehand v2 — older page-centric SDK
Represented by:

- Extract — https://docs.stagehand.dev/v2/basics/extract.md
- Agent — https://docs.stagehand.dev/v2/basics/agent.md
- Models — https://docs.stagehand.dev/v2/configuration/models.md
- Observability — https://docs.stagehand.dev/v2/configuration/observability.md
- Caching, Computer Use, Multiple Tabs, Installation, AI rules — https://docs.stagehand.dev/v2/best-practices/caching.md , https://docs.stagehand.dev/v2/best-practices/computer-use.md , https://docs.stagehand.dev/v2/best-practices/using-multiple-tabs.md , https://docs.stagehand.dev/v2/first-steps/installation.md , https://docs.stagehand.dev/v2/first-steps/ai-rules.md
- Integrations — https://docs.stagehand.dev/v2/integrations/vercel/introduction.md , https://docs.stagehand.dev/v2/integrations/crew-ai/introduction.md , https://docs.stagehand.dev/v2/integrations/langchain/introduction.md , https://docs.stagehand.dev/v2/best-practices/mcp-integrations.md

v2 pattern is `new Stagehand({env})` + `init()`, with `stagehand.page` and `page.act/page.extract/page.observe`.

### 1.4 Browserbase Cloud Platform
Represented by unified skill + platform docs:

- Unified entry: `browse` CLI, Fetch, Search, Agents, Cloud APIs, Functions, Templates, Skills — https://www.browserbase.com/SKILL.md
- Browserbase Python SDK — https://docs.browserbase.com/reference/sdk/python.md
- SDK overview — https://docs.browserbase.com/reference/sdk/overview.md
- Sessions: create/use/manage, long sessions, keep-alive, timeouts — https://docs.browserbase.com/platform/browser/getting-started/using-browser-session.md , https://docs.browserbase.com/platform/browser/getting-started/manage-browser-session.md , https://docs.browserbase.com/platform/browser/long-sessions/overview.md , https://docs.browserbase.com/platform/browser/long-sessions/keep-alive.md , https://docs.browserbase.com/reference/api/update-a-session.md , https://docs.browserbase.com/reference/api/list-sessions.md
- Observability: replay, live view, downloads — https://docs.browserbase.com/platform/browser/observability/session-replay.md , https://docs.browserbase.com/platform/browser/observability/session-live-view.md , https://docs.browserbase.com/reference/api/list-session-recording-downloads.md , https://docs.browserbase.com/reference/api/session-live-urls.md , https://docs.browserbase.com/reference/api/get-download.md , https://docs.browserbase.com/reference/api/delete-a-download.md
- Agents platform: overview, integrate, how-it-works, runs, files — https://docs.browserbase.com/use-cases/agents.md , https://docs.browserbase.com/platform/agents/integrate-api-sdk.md , https://docs.browserbase.com/platform/agents/how-it-works.md , https://docs.browserbase.com/platform/agents/managing-files.md , https://docs.browserbase.com/reference/api/get-a-run.md , https://docs.browserbase.com/reference/api/resume-a-run.md , https://docs.browserbase.com/reference/api/stop-a-run.md , https://docs.browserbase.com/reference/api/list-agents.md , https://docs.browserbase.com/reference/api/get-an-agent.md , https://docs.browserbase.com/reference/api/update-an-agent.md
- Functions — https://docs.browserbase.com/platform/functions/overview.md , https://docs.browserbase.com/platform/functions/limits.md , https://docs.browserbase.com/reference/api/list-invocations-for-a-function-version.md , https://docs.browserbase.com/reference/api/get-a-function-version.md , https://docs.browserbase.com/reference/api/get-a-function.md
- Search/Fetch — https://docs.browserbase.com/reference/api/web-search.md and Fetch fields inside https://www.browserbase.com/SKILL.md
- Projects/Contexts/Extensions/Secrets/Webhooks — https://docs.browserbase.com/reference/api/list-projects.md , https://docs.browserbase.com/reference/api/get-a-project.md , https://docs.browserbase.com/reference/api/create-a-context.md , https://docs.browserbase.com/platform/browser/core-features/browser-extensions.md , https://docs.browserbase.com/reference/api/get-an-extension.md , https://docs.browserbase.com/reference/api/create-a-secret.md , https://docs.browserbase.com/platform/webhooks/overview.md , https://docs.browserbase.com/platform/webhooks/verifying-deliveries.md , https://docs.browserbase.com/reference/api/create-session-uploads.md
- Security/compliance/network: BYOS, allowed domains, IP allowlisting, Web Bot Auth, headless explainer — https://docs.browserbase.com/account/enterprise/byos-setup-guide.md , https://docs.browserbase.com/platform/browser/security/allowed-domains.md , https://docs.browserbase.com/platform/browser/security/ip-allowlisting.md , https://docs.browserbase.com/platform/identity/web-bot-auth.md , https://docs.browserbase.com/platform/browser/getting-started/what-is-headless-browser.md
- Billing/usage — https://docs.browserbase.com/account/billing/plans.md , https://docs.browserbase.com/account/billing/plan-management.md , https://docs.browserbase.com/optimizations/cost/measuring-usage.md
- Use cases + integrations: form submissions, automated tests, flight-booker CrewAI, MCP setup, n8n, Mastra, Eve, BrowserUse, Trigger, Hermes, OpenClaw, 1Password, AgentKit, Stripe Link, GitHub Action selector healing, Vercel — https://docs.browserbase.com/use-cases/automating-form-submissions.md , https://docs.browserbase.com/use-cases/building-automated-tests.md , https://docs.browserbase.com/integrations/crew-ai/build-a-flight-booker.md , https://docs.browserbase.com/integrations/mcp/setup.md , https://docs.browserbase.com/integrations/n8n/quickstart.md , https://docs.browserbase.com/integrations/mastra/quickstart.md , https://docs.browserbase.com/integrations/vercel/eve/quickstart.md , https://docs.browserbase.com/integrations/vercel/eve/introduction.md , https://docs.browserbase.com/integrations/vercel/introduction.md , https://docs.browserbase.com/integrations/browseruse/python.md , https://docs.browserbase.com/integrations/browseruse/introduction.md , https://docs.browserbase.com/integrations/trigger/quickstart.md , https://docs.browserbase.com/integrations/hermes-agent/setup.md , https://docs.browserbase.com/integrations/hermes-agent/introduction.md , https://docs.browserbase.com/integrations/openclaw/introduction.md , https://docs.browserbase.com/integrations/1password/introduction.md , https://docs.browserbase.com/integrations/agentkit/quickstart.md , https://docs.browserbase.com/integrations/stripe/browse-cli.md , https://docs.browserbase.com/integrations/skills/github-action.md , https://docs.browserbase.com/integrations/skills/introduction.md , https://docs.browserbase.com/integrations/anthropic/managed-agents/introduction.md , https://docs.browserbase.com/integrations/get-started.md , https://docs.browserbase.com/welcome/getting-started.md , https://docs.browserbase.com/welcome/quickstarts/playwright.md , https://docs.browserbase.com/welcome/quickstarts/skills.md , https://docs.browserbase.com/reference/sdk/overview.md , https://docs.browserbase.com/platform/browser/core-features/overview.md , https://docs.browserbase.com/platform/browser/techniques/dialogues.md

---

## 2. API Contracts and Current vs Legacy Contradictions

### 2.1 Construction / initialization

**v4 current:** Browser factory then `Stagehand.create({browser})`. No public constructor. Instance is already initialized. Caller owns browser handle.

- Documented in https://docs.stagehand.dev/v4/reference/stagehand.md and https://docs.stagehand.dev/v4/configuration/browser.md
- Migration states: “The constructor is private and `init()` is gone.” — https://docs.stagehand.dev/v4/migrations/v3.md

**v3 legacy:** `new Stagehand({env:"BROWSERBASE"|"LOCAL"})` then `await stagehand.init()`.

- Seen in https://docs.stagehand.dev/v3/references/context.md , https://docs.stagehand.dev/v3/references/locator.md , https://docs.stagehand.dev/v3/configuration/observability.md , https://docs.stagehand.dev/v3/first-steps/ai-rules.md

**v2 legacy:** Same `new Stagehand` + `init()`, but with `stagehand.page` directly and `modelName` + `modelClientOptions`.

- Seen in https://docs.stagehand.dev/v2/first-steps/ai-rules.md , https://docs.stagehand.dev/v2/configuration/models.md , https://docs.stagehand.dev/v2/first-steps/installation.md

**v3 hosted session API:** `POST /v1/sessions/start` with `modelName` required, returns `sessionId`, `cdpUrl`, `available`. All other endpoints except start require active session ID.

- Contract in https://docs.stagehand.dev/v3/api-reference/python/start-a-new-browser-session.md

**Contradiction for MomoBot:** Do not mix shapes. v4 has no `sessionId` on calling surface, no `init()`, no `stagehand.page`, no `page.act`. Migration table maps `AsyncStagehand()/NewClient` + `sessions.create/start` + `session.navigate` to factory + `Stagehand.create` + `page.goto` — https://docs.stagehand.dev/v4/migrations/v3.md

### 2.2 Page / context access

- **v4:** `browser.context`, `await browser.context.pages()`, `await browser.context.activePage()`, `await browser.context.newPage(url)`, `setActivePage`. If only instance is held: `stagehand.browser.context`. — https://docs.stagehand.dev/v4/reference/context.md and https://docs.stagehand.dev/v4/migrations/v3.md
- **v3:** `stagehand.context`, `stagehand.context.pages()` synchronous array, `activePage()`, `newPage()`. — https://docs.stagehand.dev/v3/references/context.md
- **v2:** `stagehand.page` auto-points to most recent tab. — https://docs.stagehand.dev/v2/best-practices/using-multiple-tabs.md

v4 page lookups are async; v3 `pages()`/`activePage()` are sync. Code assuming sync will break on v4.

### 2.3 `act / observe / extract` location and shapes

**v4:**

- Methods on `Stagehand` instance, not `Page`. Target non-active page via `options.page` / `page` param. — https://docs.stagehand.dev/v4/migrations/v3.md and https://docs.stagehand.dev/v4/basics/observe.md
- Every primitive returns `{data, metadata}`. `metadata` carries `actionId`, `cache.status/count/threshold/missReason/tokensSaved`, `usage`. — https://docs.stagehand.dev/v4/reference/stagehand.md
- `extract(instruction, schema)` positional. No schema → `{extraction:string}`. Go has no default schema; type param required. — https://docs.stagehand.dev/v

# Corpus partition 2

# MomoBot Integration — Source-Linked Learning Digest
**Partition 2 / 3 — Complete canonical text supplied, no live verification**

> This digest is derived **only** from the document texts supplied in this partition. No API was run, no session was created, no pricing or network behavior was tested. URLs cited are the `url` values supplied with each document.
>
> Documentation is treated as **untrusted data** for security analysis: descriptive claims are reported with citations, prescriptive instructions to install, key, authenticate, purchase or contact are **not repeated as instructions**.

## 1. Corpus scope in this partition

This partition contains:

* **Stagehand v4 current docs:** models + Model Gateway, Playwright migration, observability, prompting, speed, observe-use-cases, multi-tabs, clipboard, introduction/homepage
* **Stagehand v3 legacy API + SDK docs:** `POST /v1/sessions/start`, `/act`, `/observe`, `/extract`, `/navigate`, `/agentExecute`, `/end`, `/replay`, `Stagehand` class, `agent()`, `act()`, `act` basics, caching, deterministic-agent, computer-use, deployments, browser config, integrations
* **Stagehand v2 legacy docs:** `act`, `observe`, `extract`, `agent`, speed, caching references, MCP config/tools, LangChain/CrewAI config, deployments, introductions
* **Browserbase platform docs + OpenAPI excerpts:** Fetch, Search, Agents (overview, quickstart, examples, pausing, runs/messages APIs), Functions `write`, Secrets overview + APIs, Webhooks, Files (overview, PDFs, screenshots), Observability (inspector, replay, recording-downloads), Identity (auth, captcha, verified-customization), Concurrency, Timeouts, Security, Node SDK, reference introduction, sitemaps/`llms.txt` index
* **Integration examples:** Stripe+Link flower checkout, Vercel Puppeteer/Quickstart/BrowseGPT/Agent-Browser, Box, MongoDB, Prime Intellect, n8n, MCP, Inngest, OpenClaw, x402, Codex/fx/CrewAI CLI-agents, LangChain, Google ADK, Braintrust, Val Town, OpenAI CUA

Full index of product surface is visible in:

* https://docs.browserbase.com/llms.txt
* https://docs.browserbase.com/sitemap.xml
* https://docs.stagehand.dev/sitemap.xml
* https://docs.stagehand.dev/
* https://docs.stagehand.dev/v4/first-steps/introduction.md

## 2. Product families represented

### 2.1 Browserbase Browsers — managed sessions

Core primitive is a **browser session = single cloud browser instance**. Reference introduction frames sessions as fundamental building block with create / use / manage / inspect flow:

* https://docs.browserbase.com/reference/introduction.md
* https://docs.browserbase.com/welcome/quickstarts/puppeteer.md shows `bb.sessions.create()` then `connectOverCDP(session.connectUrl)` pattern, also used for Playwright/Puppeteer/Selenium.

Managed-vs-self-hosted tradeoff is explicit: DIY owns lifecycle, pooling, crash recovery, concurrency, debuggability, identity, proxies, Chromium updates, per-session sandboxing; Browserbase absorbs it:

* https://docs.browserbase.com/platform/browser/getting-started/remote-browser-versus-local-browser.md

Enterprise security claims: 1 browser per VM, isolated subnets + firewalls, no reuse (VM killed/recreated), no GPU, SOC2 Type II, HIPAA + BAA, pen-testing, Trust Center:

* https://docs.browserbase.com/account/enterprise/security.md

What this partition **does not prove**: actual isolation enforcement, firewall rules, patch cadence, or audit artifacts. Only claim text.

### 2.2 Stagehand — AI primitives + deterministic page APIs

Current v4 positioning:

> Stagehand is built for agents. Playwright was built for testing. Two layers: AI primitives (`act`, `extract`, `observe`) + Playwright-style `page` APIs (`goto`, `click`, `type`, `locator`, `screenshot`).

* https://docs.stagehand.dev/v4/first-steps/introduction.md
* https://docs.stagehand.dev/

v2/v3 positioning was four primitives including `agent()`:

* https://docs.stagehand.dev/v2/first-steps/introduction.md
* https://docs.stagehand.dev/v3/first-steps/introduction.md

v4 explicitly **has no autonomous agent** — multi-step flows are caller control flow:

* https://docs.stagehand.dev/v4/best-practices/prompting-best-practices.md — “Stagehand v4 has no autonomous agent, so multi-step flows are your control flow.”

### 2.3 Model Gateway

One Browserbase key for LLM inference + browser + caching, market-price tokens, no markup, retries/backoff, no tier-gating:

* https://docs.stagehand.dev/v4/configuration/models.md
* Listed in platform index as “Access top LLM providers through your Browserbase API key”: https://docs.browserbase.com/llms.txt

Routing table in v4 models doc:

| Configuration | Where inference runs |
|---|---|
| No `model` | Gateway, Browserbase selects per call |
| `model` no `apiKey` | Gateway, pinned |
| `model` with `apiKey` | Direct to provider, bypass Gateway |
| Client callback | Own process, bypass Gateway |

Gateway requires Browserbase-hosted browsers, rejects `stopSequences`, selection per-call:

* https://docs.stagehand.dev/v4/configuration/models.md

n8n integration also describes Gateway as alternative to own model key, market-rate billing:

* https://docs.browserbase.com/integrations/n8n/introduction.md

### 2.4 Fetch — lightweight retrieval

`POST /v1/fetch`, no JS execution, 5 MB limit, 60s timeout, `raw | markdown | json` formats, Fetch Extract (markdown/json) priced separately:

* https://docs.browserbase.com/platform/fetch/overview.md

Parameters: `url` required, `allowRedirects` default `false`, `allowInsecureSsl` default `false`, `proxies` boolean/object with optional `geolocation`, `format`, `schema` (only with `format: json`):

* https://docs.browserbase.com/platform/fetch/overview.md

Recommended pipeline Search → Fetch → Browsers:

* https://docs.browserbase.com/platform/fetch/overview.md
* https://docs.browserbase.com/platform/search/overview.md

### 2.5 Search

`POST /v1/search`, `query` 1–200 chars, `numResults

# Corpus partition 3

# MomoBot Integration — Source-Linked Learning Digest
**Partition 3 of 3 — Complete canonical text supplied for this partition only**

> This digest is derived **only** from the document texts supplied in Partition 3. It does not prove behavior of Partitions 1-2, live API behavior, pricing enforcement, or undocumented security controls. No API was run. No secrets are included.

Documentation index for discovery:
- https://docs.stagehand.dev/llms.txt

## 1. Product families represented in Partition 3

Partition 3 contains full text for:

**A. Stagehand SDK generations:**
- **v4 current:** `Stagehand.create({browser})` + `browser.context` + `page` + `stagehand.act/extract/observe` + `browserbase.search/fetch/launch` — https://docs.stagehand.dev/v4/basics/act.md , https://docs.stagehand.dev/v4/basics/extract.md , https://docs.stagehand.dev/v4/reference/page.md , https://docs.stagehand.dev/v4/reference/locator.md , https://docs.stagehand.dev/v4/reference/response.md , https://docs.stagehand.dev/v4/reference/webmcp.md , https://docs.stagehand.dev/v4/basics/webmcp.md , https://docs.stagehand.dev/v4/add-ons/search.md , https://docs.stagehand.dev/v4/add-ons/fetch.md , https://docs.stagehand.dev/v4/best-practices/caching.md , https://docs.stagehand.dev/v4/first-steps/installation.md , https://docs.stagehand.dev/v4/first-steps/ai-rules.md
- **v3 Stainless API + SDKs:** `POST /v1/sessions/start`, `/navigate`, `/act`, `/observe`, `/extract`, `/agentExecute`, `/end`, `GET /replay` on `https://api.stagehand.browserbase.com` — https://docs.stagehand.dev/v3/api-reference/java/start-a-new-browser-session.md , https://docs.stagehand.dev/v3/api-reference/ruby/navigate-to-a-url.md , https://docs.stagehand.dev/v3/api-reference/java/perform-an-action.md , https://docs.stagehand.dev/v3/api-reference/go/observe-available-actions.md , https://docs.stagehand.dev/v3/api-reference/python/observe-available-actions.md , https://docs.stagehand.dev/v3/api-reference/python/extract-data-from-the-page.md , https://docs.stagehand.dev/v3/api-reference/python/execute-an-ai-agent.md , https://docs.stagehand.dev/v3/api-reference/python/end-a-browser-session.md , https://docs.stagehand.dev/v3/api-reference/go/replay-session-metrics.md , https://docs.stagehand.dev/v3/api-reference/ruby/replay-session-metrics.md
- **v3 SDK languages:** Python, Java, Ruby, Go, TypeScript references — https://docs.stagehand.dev/v3/sdk/python.md , https://docs.stagehand.dev/v3/sdk/java.md , https://docs.stagehand.dev/v3/sdk/ruby.md , https://docs.stagehand.dev/v3/references/page.md , https://docs.stagehand.dev/v3/references/deeplocator.md , https://docs.stagehand.dev/v3/references/clipboard.md , https://docs.stagehand.dev/v3/basics/observe.md , https://docs.stagehand.dev/v3/basics/extract.md
- **v2 legacy:** `stagehand.page.act/extract/observe/agent`, `new Stagehand({env})` + `init()` returning `{debugUrl,sessionUrl,sessionId}` — https://docs.stagehand.dev/v2/basics/act.md , https://docs.stagehand.dev/v2/best-practices/prompting-best-practices.md , https://docs.stagehand.dev/v2/configuration/browser.md , https://docs.stagehand.dev/v2/configuration/logging.md , https://docs.stagehand.dev/v2/best-practices/cost-optimization.md , https://docs.stagehand.dev/v2/references/stagehand.md , https://docs.stagehand.dev/v2/best-practices/working-with-iframes.md , https://docs.stagehand.dev/v2/best-practices/playwright-interop.md , https://docs.stagehand.dev/v2/best-practices/user-data.md , https://docs.stagehand.dev/v2/configuration/evals.md
- **v3 migrations:** v2->v3 breaking changes — https://docs.stagehand.dev/v3/migrations/v2.md

**B. Browserbase platform:**
- Sessions, Contexts, Proxies, Verified/Identity, Viewports, Timezones, Certificate validation, Metadata, Regions, Downloads/Uploads, Recordings/Replays/Logs, Search/Fetch, Agents, Functions, Secrets, Certificates, Webhooks, Model Gateway, MCP, Browse CLI, x402, AgentKit — https://docs.browserbase.com/reference/api/create-a-session.md , https://docs.browserbase.com/platform/browser/getting-started/create-browser-session.md , https://docs.browserbase.com/reference/api/get-a-session.md , https://docs.browserbase.com/platform/browser/core-features/contexts.md , https://docs.browserbase.com/platform/identity/proxies.md , https://docs.browserbase.com/platform/identity/overview.md , https://docs.browserbase.com/platform/browser/core-features/viewports.md , https://docs.browserbase.com/platform/browser/techniques/timezones.md , https://docs.browserbase.com/platform/browser/security/certificate-validation.md , https://docs.browserbase.com/platform/browser/core-features/session-metadata.md , https://docs.browserbase.com/optimizations/latency/multi-region.md , https://docs.browserbase.com/platform/browser/files/downloads.md , https://docs.browserbase.com/platform/browser/files/uploads.md , https://docs.browserbase.com/reference/api/list-downloads.md , https://docs.browserbase.com/reference/api/create-session-recording-downloads.md , https://docs.browserbase.com/reference/api/session-replays.md , https://docs.browserbase.com/reference/api/session-logs.md , https://docs.browserbase.com/reference/api/fetch-a-page.md , https://docs.browserbase.com/platform/model-gateway/overview.md , https://docs.browserbase.com/reference/api/run-an-agent.md , https://docs.browserbase.com/reference/api/invoke-a-function.md , https://docs.browserbase.com/platform/functions/invoke.md , https://docs.browserbase.com/platform/functions/quickstart.md , https://docs.browserbase.com/platform/functions/deploy.md , https://docs.browserbase.com/platform/functions/secrets.md , https://docs.browserbase.com/platform/secrets/getting-started.md

**C. Agent / integration surfaces:**
CLI Agents, Pi, Vercel AI SDK, Mastra, Playwright/Puppeteer/Selenium interop, LangChain, CrewAI, Braintrust, Val Town, Temporal, Inngest, Trigger, IBM, Agno, Stripe, Google ADK, Convex, Next.js/Vercel, Anthropic Managed Agents, Prime Intellect, Browse CLI/Skills — https://docs.stagehand.dev/v4/integrations/cli-agents/overview.md , https://docs.stagehand.dev/v4/integrations/cli-agents/pi.md , https://docs.stagehand.dev/v4/integrations/agent-frameworks/vercel-ai-sdk.md , https://docs.stagehand.dev/v4/integrations/agent-frameworks/mastra.md , https://docs.stagehand.dev/v3/integrations/playwright.md , https://docs.stagehand.dev/v3/integrations/selenium.md , https://docs.stagehand.dev/v3/integrations/convex/configuration.md

## 2. API contracts (as documented in Partition 3)

### 2.1 Stagehand v4 — Browser + Stagehand split

v4 drives browser directly over CDP, no Playwright/Puppeteer interop. Target pages via `page` option:
- https://docs.stagehand.dev/v4/basics/act.md
- https://docs.stagehand.dev/v4/first-steps/ai-rules.md

Core pattern documented:
- `browser = await browserbase.launch({apiKey})` or `localBrowser.launch/connect`
- `stagehand = await Stagehand.create({browser, model, cache, logging})`
- `page = await browser.context.activePage() | pages() | newPage(url)`
- `stagehand.act(instruction|Action, {page, model, timeout, variables, locator, ignoreLocators, cache})`
- `stagehand.extract(instruction, schema, {page, model, timeout, locator, ignoreLocators, screenshot, cache})`
- `stagehand.observe(instruction?, {page, model, timeout, locator...})`
- `page.tools() -> WebMCPTool[]`, `invoke()->result()/cancel()`
- Cleanup order: `await stagehand.close()` before `await browser.close()` — https://docs.stagehand.dev/v4/first-steps/ai-rules.md , https://docs.stagehand.dev/v4/first-steps/installation.md

`Page` deterministic controls documented in full:
`goto/reload/goBack/goForward` return `Response|null`, plus `click/hover/scroll/dragAndDrop/type/keyPress/evaluate/on/addInitScript/setExtraHTTPHeaders/setViewportSize/waitForLoadState/waitForTimeout/waitForSelector/screenshot/snapshot/tools/url/title/close/locator` — https://docs.stagehand.dev/v4/reference/page.md

`Locator` documented with `click/hover/fill/count/isChecked/inputValue/isVisible/innerText/innerHtml/textContent/scrollTo/centroid/highlight/sendClickEvent/type/selectOption/setInputFiles/first/nth`, shadow-DOM piercing including closed roots, iframe hops via `>>` — https://docs.stagehand.dev/v4/reference/locator.md

`Response` from navigation:
- Immediate metadata without RPC: `url/status/statusText/ok/headers/fromServiceWorker`
- Lazy body: `body/text/json/finished`, plus `allHeaders/headerValue/headerValues/headersArray/securityDetails/serverAddr`
- Handles invalid after session close, may be GC'd after newer responses — https://docs.stagehand.dev/v4/reference/response.md

`WebMCP`:
- `page.tools({timeout:1000 default})`, `invoke({input:{}})` returns handle immediately, `result({timeout: indefinite default})` waits for terminal `Completed|Canceled|Error`
- `result()` caches terminal response; timeout/transport failures retryable; `cancel()` is request not guarantee — https://docs.stagehand.dev/v4/basics/webmcp.md , https://docs.stagehand.dev/v4/reference/webmcp.md

### 2.2 Stagehand v3 — Session-ID REST + `stagehand.*` instance methods

OpenAPI server `https://api.stagehand.browserbase.com`, security `x-bb-api-key` + deprecated `x-bb-project-id` — https://docs.stagehand.dev/v3/api-reference/java/start-a-new-browser-session.md

Endpoints in partition:
- `POST /v1/sessions/start {modelName*, domSettleTimeoutMs, verbose, systemPrompt, browserbaseSessionCreateParams, browser, selfHeal, browserbaseSessionID...}` -> `{sessionId, cdpUrl?, available}` — https://docs.stagehand.dev/v3/api-reference/java/start-a-new-browser-session.md
- `POST /v1/sessions/{id}/navigate {url*, options:{referer,timeout,waitUntil:load|domcontentloaded|networkidle}, frameId}` — https://docs.stagehand.dev/v3/api-reference/ruby/navigate-to-a-url.md
- `POST /v1/sessions/{id}/act {input*: string|Action{selector*,description*,backendNodeId,method,arguments}, options:{model,variables,timeout}, frameId}` — https://docs.stagehand.dev/v3/api-reference/java/perform-an-action.md
- `POST /v1/sessions/{id}/observe {instruction, options:{model,variables,timeout,selector,ignoreSelectors}, frameId}` — https://docs.stagehand.dev/v3/api-reference/go/observe-available-actions.md
- `POST /v1/sessions/{id}/extract {instruction, schema: JSON Schema, options:{model,timeout,selector,ignoreSelectors,screenshot}, frameId}` — https://docs.stagehand.dev/v3/api-reference/python/extract-data-from-the-page.md
- `POST /v1/sessions/{id}/agentExecute {agentConfig*:{provider legacy,model,systemPrompt,cua deprecated,mode:dom|hybrid|cua,executionModel}, executeOptions*:{instruction*,maxSteps,highlightCursor,useSearch,toolTimeout,variables}, frameId, shouldCache}` — https://docs.stagehand.dev/v3/api-reference/python/execute-an-ai-agent.md
- `POST /v1/sessions/{id}/end -> {success}` — https://docs.stagehand.dev/v3/api-reference/python/end-a-browser-session.md
- `GET /v1/sessions/{id}/replay -> {pages:[{url,timestamp,duration,actions:[{method,parameters,result,timestamp,endTime,tokenUsage}]}], clientLanguage?}` — https://docs.stagehand.dev/v3/api-reference/go/replay-session-metrics.md
- SSE streaming via `x-stream-response:true` + `streamResponse:true` — https://docs.stagehand.dev/v3/sdk/python.md , https://docs.stagehand.dev/v3/sdk/ruby.md

v3 TypeScript surface: `stagehand.act/extract/observe/agent` on instance, `stagehand.context.pages()/newPage()/setActivePage()/awaitActivePage()`, `page.goto/reload/goBack/goForward/url/title/click/hover/scroll/dragAndDrop/type/keyPress/locator/evaluate/addInitScript/setExtraHTTPHeaders/screenshot/snapshot/listWebMCPTools/invokeWebMCPTool/setViewportSize/waitForLoadState/waitForSelector/on/once/off` — https://docs.stagehand.dev/v3/references/page.md
`deepLocator("iframe#x >> button")` + deep XPath auto-traversal — https://docs.stagehand.dev/v3/references/deeplocator.md
`