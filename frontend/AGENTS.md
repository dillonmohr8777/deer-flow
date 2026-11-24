# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with the DeerFlow frontend. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

## Project Overview

DeerFlow Frontend is a Next.js 16 web interface for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2. Requires Node.js 22+ and pnpm 10.26.2+.

### Core dependencies

- **LangGraph SDK** (`@langchain/langgraph-sdk` ^1.5.3) — Agent orchestration and streaming
- **LangChain Core** (`@langchain/core` ^1.1.15) — Core AI primitives
- **TanStack Query** (`@tanstack/react-query` ^5.90.17) — Server state
- **UI**: Shadcn UI, MagicUI, React Bits, Vercel AI SDK elements (registry-generated; see Code Style)

`pnpm-workspace.yaml` overrides `@xmldom/xmldom` 0.9.x to 0.9.12 (GHSA-965w-775f-mr7g, pulled via Nextra/MathJax/`speech-rule-engine@4.1.2`). Keep until upstream patches it; regenerate `pnpm-lock.yaml` and verify docs build if changed.

## Commands

| Command          | Purpose                                       |
| ---------------- | --------------------------------------------- |
| `pnpm dev`       | Start the development server with Webpack     |
| `pnpm build`     | Production build                              |
| `pnpm check`     | Lint + type check (run before committing)     |
| `pnpm lint`      | ESLint only                                   |
| `pnpm lint:fix`  | ESLint with auto-fix                          |
| `pnpm format`    | Prettier check (`pnpm format:write` to apply) |
| `pnpm test`      | Run unit tests with Rstest                    |
| `pnpm test:e2e`  | Run E2E tests with Playwright (Chromium)      |
| `pnpm typecheck` | TypeScript type check (`tsc --noEmit`)        |
| `pnpm start`     | Start production server                       |

Unit tests live under `tests/unit/` mirroring `src/` (Rstest, `@/` alias). Webpack is the default dev bundler; pass `DEER_FLOW_DEV_BUNDLER=turbo` with `pnpm dev` to diagnose bundler issues with Turbopack.

Rstest splits into two projects (`rstest.config.ts`): `*.test.ts(x)` runs in **node** (default for pure logic); `*.dom.test.ts(x)` runs in **happy-dom** (3x slower; reserve for `renderHook`, components, and hooks requiring real React effects/cleanup/store re-renders instead of mocking `react`).

E2E tests live under `tests/e2e/` (Playwright Chromium, `playwright.config.ts`), mocking backend APIs with `page.route()`. Auth recovery fixtures use context routes so worker-owned requests reach mocks after the PWA worker claims the page; keep active-worker recovery coverage at desktop/mobile widths, exact retry counts, and registration gate without altering production auth or disabling the worker. `tests/e2e/design-surfaces.spec.ts` is opt-in (`DESIGN_SHOTS=1`), capturing 1440×900 and 390×844 surfaces into `DESIGN_SHOTS_DIR` (`/login` uses `DESIGN_SIGNED_OUT_URL` with `DEER_FLOW_AUTH_DISABLED=0` and an unreachable gateway; `DESIGN_SHOTS_DEBUG=1` logs unmocked calls; `DESIGN_SHOTS_ONLY=a,b` filters surfaces). Real-backend auth tests `tests/e2e-real-backend/auth-disabled-contract.spec.ts` and `backend/tests/test_auth_me_permissions.py` pin the full route-permission list (including `projects:read/write/delete`); update both when adding permissions.

`run-history.ts` replaces the unpaged runs hook: show counts only after a successful read, never during loading/errors. Scheduled run history uses task/page query keys over the live offset API, fetches 51 rows (50 + next-page sentinel, never appends), polls/refreshes only page 0, resets to page 0 on task switch, and cancels obsolete reads via AbortSignal (live offsets may observe newly inserted runs on mutations/navigation).

## Architecture

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, set thread-scoped `/goal` completion conditions, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code), **todos**, and goal state updates.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes include `/` (landing), `/showcase/[thread_id]` (allowlisted public read-only demos), `/workspace/chats/[thread_id]` (authenticated chat), `/workspace/agents/[agent_name]` and `/workspace/agents/new` (custom agents), `/artifacts/view` (chrome-free window that renders Markdown or CSV/TSV artifacts with the panel's own renderer), `/blog/…`, the `(auth)/{login,setup,auth/callback}` flow, `/[lang]/docs/…`, and `/api/…` route handlers (e.g. `/api/memory`).
- **`components/`** — React components:
  - `ui/` — Shadcn UI primitives (auto-generated, ESLint-ignored)
  - `ai-elements/` — Vercel AI SDK elements (auto-generated, ESLint-ignored)
  - `workspace/` — Chat page components (messages, artifacts, settings)
  - `landing/` — Landing page sections
  - `docs/` — Docs / MDX rendering components
- **`core/`** — Business logic, the heart of the app. Domains include `threads/` (creation, streaming, state), `api/` (LangGraph client singleton), `agents/` (custom agents), `subagents/` (runtime worker catalog and administrator mutations), `auth/` (authentication), `artifacts/`, `channels/` (IM connections), `integrations/` (managed third-party integration status/install clients such as Lark CLI), `i18n/` (en-US, zh-CN), `settings/`, `memory/`, `skills/`, `messages/`, `mcp/`, `models/`, `input-polish/` (pre-send draft rewrite API), `voice-input/` (browser speech-recognition helpers), `suggestions/`, `tasks/`, `todos/`, `tools/`, `workspace-changes/` (run-scoped changed-file summaries and diff fetching), `config/`, `notification/`, `blog/`, plus rendering helpers (`rehype/`, `streamdown/`) and `utils/`.
- **`hooks/`** — Shared React hooks
- **`lib/`** — Utilities (`cn()` from clsx + tailwind-merge)
- **`content/`** — MDX content (blog posts, docs) rendered by the app
- **`styles/`** — Global CSS with Tailwind v4 `@import` syntax and CSS variables for theming
- **`typings/`** — Ambient TypeScript declarations
- Root files: `env.js` (env validation), `mdx-components.ts` (MDX component map)

More specific `AGENTS.md` files under `src/` contain the frontend sections split from this file.

## Code Style

Page-body paper colour overrides apply only while the root is light and paper.
Use theme-aware status tokens for coloured text; treatment tokens alone do not
follow the light/dark switch. Agent Room E2E checks rendered foreground and
composited backgrounds across every treatment and both themes; normal text must
keep at least 4.5:1 contrast, including390/768/1440px paper layouts.

`core/utils/markdown.ts` reads web-fetch titles from the first nonblank line.
Match zero to three literal spaces before `# ` without trimming indentation;
mixed space/tab code blocks must fall back to the URL. Keep this local to title
extraction rather than changing the shared streamdown fence parser.

Custom Agent `display_name` is an optional Unicode UI label, edited in
`AgentSettingsDialog`. Use it with a fallback to `name` for gallery/chat text;
keep `name` for React identity, URLs, requests, and runtime `agent_name`.
The 100-code-point budget uses `[...value.trim()].length`, matching Pydantic;
do not use HTML `maxLength`, which counts UTF-16 code units instead.

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

Scheduled-task list search filters the current authorized query result by title or
prompt, composing with status/type filters and thread scope. Selection must derive
from the filtered list so hidden tasks cannot remain actionable. Keep literal
matching in `core/scheduled-tasks/search.ts`; clearing search retains other filters.

Single-run schedule edits retain the mounted task's original `run_at` while its wall time and timezone match. The parent echoes edits through `initial`; retain a stable snapshot and reset the parent draft during render before remounting with a task key when switching tasks. Use the resolved timezone consistently for the snapshot and displayed wall time. Component and scheduled-task E2E tests cover DST folds and timestamp precision.

## Environment

Scheduled-task interval forms preserve the initial `every_seconds` on mount,
timezone changes, and untouched blur. The backend's configurable interval minimum
can be lower than the UI's default 60-second floor. Apply that UI floor only after
an explicit amount/unit edit so editing metadata or duplicating a task cannot
silently change its cadence. Component regressions live in
`tests/unit/components/workspace/scheduled-task-schedule-input.dom.test.tsx`.

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:8001/api
```

Leave these unset for the standard `make dev` / Docker flow, where nginx serves the public `/api/langgraph/*` prefix and rewrites it to Gateway's native `/api/*` routes.

`make build-static` creates a standalone read-only demo and copies `.next/static`
and `public` into the output. In static mode, `core/api/static-response.ts`
resolves Gateway REST reads with the bundled capability catalog and safe
installation projections from existing same-origin `/mock/api` fixtures; writes
and unknown API routes fail locally.
The homepage client counter calls `/github-stars`, outside the Gateway proxy.
That dynamic route reads the server-only `GITHUB_OAUTH_TOKEN` at runtime, caches
GitHub data for one hour, and returns 204 when the count is unavailable. Start
the standalone server from `frontend/` with `node --env-file=.env
.next/standalone/server.js` to load the current credentials.

To reach a dev server on anything other than localhost — a LAN address, or a proxied hostname — list the host in `DEER_FLOW_DEV_ALLOWED_ORIGINS` (comma-separated; a full URL is reduced to its host). It feeds Next's `allowedDevOrigins`, which gates `/_next/*`, fonts, and HMR. Without it those requests get a 403 and the page renders server-side but never hydrates, so nothing on it — including the login form — responds. Development only; production builds ignore it.

One-time schedule input uses `validZonedLocalToUtcIso` to reject wall times that
do not round-trip in the selected timezone. Invalid input emits an empty spec and
localized inline feedback; both create and edit must block submission. Keep this
UI validation separate from the API payload. Preserve the original instant when
wall time and timezone match the mounted snapshot; validate changed inputs, and
restore the exact original timestamp when those edits are reverted.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

When adding features:

1. Follow the established `src/` structure
2. Add TypeScript types and proper error handling
3. Write unit tests under `tests/unit/` (`pnpm test`) and E2E tests under `tests/e2e/` (`pnpm test:e2e`)
4. Run `pnpm check` before committing
5. Update this `AGENTS.md` when architecture, commands, or conventions change

Route asset budgets are enforced with `pnpm perf:check`. The command measures
`/login` from a normal production build, then builds in static-demo mode for the
fixture-backed workspace routes. It starts the production server on temporary local
ports, measures the unique JavaScript and CSS files referenced by representative
routes, writes the detailed result to `.next/performance-results.json`, and compares
totals with `performance-budgets.json`. Fix route ownership or split points when a
budget fails; do not raise a ceiling without documenting and reviewing the measured
regression.

Chat archive is a thread metadata flag (`deerflow_archived === true`), independent
of run status. Sidebar and Chats explicitly request the Gateway's optional
`archived` filter through `searchThreadsByArchive`; the SDK drops this extension,
so use the authenticated REST fetcher. Static demos retain SDK fixture queries.
`core/threads/archive.ts` waits for the write, cancels stale reads, merges only the
owned flag into metadata snapshots, then restarts metadata reads and resets list
pagination. Keep both default and Custom Agent header restore controls in sync.
Pin/archive responses must not merge unrelated metadata flags: out-of-order
organization requests can otherwise roll back each other's confirmed state.
Run-created optimistic snapshots have no archive flag: refresh archive-filtered
lists from the server instead of inserting those snapshots into either view.

### Delimited artifact preview

CSV/TSV previews share `artifact-table-preview.tsx` between the panel and standalone viewer. Papa Parse runs only inside `delimited-preview.worker.ts`; `use-delimited-preview.ts` bounds input before transfer, cancels stale work, and enforces a five-second timeout. The parser detects the first record separator outside quoted fields and passes it explicitly to Papa Parse, so embedded newlines in an incomplete quoted field cannot corrupt newline detection. It retains at most 202 logical records and 50 columns, discarding an incomplete final record from truncated input. UI pagination displays at most 200 data rows in pages of 50. Keep the table mounted but inactive when switching to source so header/pagination state survives; changing file identity resets it. Pending `write_file` content stays in source mode until success.

Custom skill export is admin-only and disabled in static demos. The lazy
`skill-export-dialog.tsx` must abort requests and ignore stale callbacks on close
or user/skill changes. `core/skills/export.ts` owns the revision-bound Blob download;
HTTP 409 requires explicit preview refresh. Keep file lists paginated and diagnostics
localized. Browser handoff does not prove the file was saved to disk.

Sidebar rows request deletion through `ThreadDeleteDialogProvider`, hosted in
`WorkspaceSidebar` outside the virtualized flat/project lists. Keep the selected
thread snapshot and retry UI alive when a partial deletion removes its row.
Focus Cancel on open and after a failed deletion has re-enabled the actions;
block dismissal while deletion is pending. Show the error message when available,
with a localized fallback, and log the rejection for debugging. The shared
delete helper accepts remote 404 (not 403) before retrying local cleanup, and
`onDeleted` runs only after both deletion steps succeed.

## Capability Center

`/workspace/capabilities` owns Plugins and Skills navigation (linked from Command Center, not the sidebar). Plugins composes the
MCP manager and a lazily loaded Lark configuration dialog; installation, OAuth,
mutation permissions, and cache ownership remain in the existing hooks. Skill display names/summaries are presentation
metadata; runtime names and full descriptions remain unchanged. Public, custom,
integration, and legacy sources must stay distinct. Community currently offers
archive import, not a remote marketplace. Screenshot E2E fixtures are demo data.

## Momentum Command Center

`/workspace/command-center` is the default non-static workspace entry. Reuse the
authenticated console stats/runs/usage endpoints; cache keys must include the
current user. Roster connections describe definitions, never live dispatch.
Preserve unknown costs as unpriced and distinguish estimates from provider credit
or invoices. The global background tray observes work; it does not start model
calls. Stop actions require confirmation and the existing run-cancel permission.
Keep project grouping distinct from verified client tenancy. Stage independently
with `NEXT_BUILD_DIR=.next-momentum`; do not overwrite a running server's build.
Momo films (`public/momentum/films/`, provenance in its SOURCES.md) render only
through `components/momentum/momo-film.tsx`: muted, `preload="none"`, poster-only
when motion is off (workspace `motionOn`, front door `useIntroMotion().live`).
Scrapbook scraps (`public/momentum/scraps/`, provenance in its SOURCES.md) render
only through `components/momentum/scraps.tsx`'s `Scraps` component: the sidebar
footer, empty states (`page-body.tsx`'s `EmptyState`), and the Momo Daily front
page margins at desktop widths. They stay out of chat threads, forms, dialogs, and
dense tables, where a moving decoration would distract rather than help. `data-live`
(the same `motionOn`/`useDailyMotion()` switch as Momo films) pauses their sway, and
they are hidden entirely under the future and retro treatments.

`backend/packages/harness/deerflow/capabilities/builtin.json` owns localized
catalog manifests. Refresh the generated demo snapshot with `pnpm catalog:sync`
after changing the catalog; unit tests enforce equality with the source. Demo
business projections derive provider IDs from the catalog adapter metadata. The
sync script uses decoded filesystem paths for formatter configuration lookup.
`plugin-catalog.ts` only resolves localized text and explicit
installation metadata; never infer provider identity from server display names.
`plugin-directory.tsx` groups rows and applies search/category/installed filters.
`core/capabilities` consumes catalog and safe status projections; MCP secrets and
raw settings remain in the administrator-only editor. `plugin-adapters.tsx`
registers integration-specific settings flows once, independent of catalog size.
The `business` form uses manifest credential fields without asking for an MCP URL;
its backend adapter generates bundled DingTalk/WeCom notification or HubSpot CRM
connections. These also appear in MCP discovery, so deduplicate projections by
installation ID. Keep their labels as configuration, not package installation.
Keep installation, enabled state, configured credentials, and verified authorization
distinct. Agent `mcp_plugins` uses stable installation IDs; null means all, [] means
none. The settings dialog submits only selections changed from its opening
snapshot, preserving concurrent updates on unrelated saves and treating restored
selections as unchanged. It is runtime selection, not a replacement authorization policy. See
`docs/capability-center.md` for the complete contract and extension example.
`PluginIcon` is shared by recommendations, configured entries, and the editor;
brand assets and their provenance live in `public/images/plugins/`. Brand icons
require explicit catalog metadata; a custom server name never selects a brand.
Ambiguous installation IDs remain visible but cannot be selected for an Agent. The icon picker
accepts local PNG/JPEG/WebP up to 2 MiB, checks the signature, decodes and contains
the image in a 128px PNG, and stages changes until the existing targeted MCP save.
`presentation.icon` is a bounded PNG data URL carried by the API's existing extra
metadata support; it must never enter transport parameters. Preserve sibling
presentation fields and masked credentials; cancel/reset/unmount must fence stale
image-decoding results. Uploaded remote URLs and SVG are never rendered. Existing
shared-MCP administrator checks remain authoritative; this adds no personal scope.

## Desk (private instance only)

`/workspace/desk` renders only when `/api/features` reports `desk.enabled` (from `config.yaml -> private_workspace.enabled`, default false). When on, `/workspace` redirects to Desk (`core/features/server.ts`, fail closed) and adds the sidebar link; when off, the route replaces to Command Center before rendering. Desk reads existing APIs (scheduled tasks, clients/fleet bindings, fleet templates, console usage, and `GET /api/board/threads?status=drafted`); grouping and schedule matching live in `components/workspace/desk/desk-data.ts`. The Approvals panel and sidebar Board badge share that drafted-threads query: count waiting on owner plus an "After hours" flag for `urgent` threads outside 8am-8pm ET (`isAfterHoursET`/`hasUrgentAfterHoursApproval`), with no external sends. `tests/e2e/desk.spec.ts` covers both flag states, empty states, and badge wiring.

## Team and AI Academy (Momentum staff only)

`/workspace/team` and `/workspace/academy` render only when `/api/features` reports `momentum_internal.enabled` (gateway checks flag, workspace slug in `momentum_internal.organization_slugs`, and staff role `owner`/`admin`/`member`; client workspaces never qualify; others replace to Command Center with links hidden). `/api/team` and `/api/academy` enforce the same 404 gate server-side. Wrappers live in `core/team` and `core/academy`, pure logic in `components/workspace/team/team-data.ts` and `core/academy/progress.ts`; channel views key by channel id so drafts do not leak across channels. `tests/e2e/team-academy.spec.ts` covers flag states and 390/768/1440 overflow.

## MomoBot Agents and About (`/workspace/lineup`, `/workspace/about`)

Render the private kit from `/api/momobot-brand/*` (`core/momobot-brand`, `components/workspace/lineup`); sidebar items appear only when that API answers. No kit text, art, or price is committed. Prices render only via `priceLabel` when `show_pricing: true` (null renders "Not priced"; never sum packages). `tests/e2e/momobot-lineup.spec.ts` uses a synthetic kit unless `LINEUP_KIT_DIR` is set.

## Invite teammate (Settings > Invite teammate)

Shared-workspace owners/admins mint invites in `components/workspace/settings/invite-settings-page.tsx`, posting `{organization_id, email, role}` (`member`/`admin`/`client`) to `POST /api/v1/auth/invitations` via `core/invitations/api.ts` (shared CSRF `fetch` wrapper). `GET /api/workspaces` lists shared workspaces; the form offers workspaces where the caller is `owner`/`admin` (defaulting to active) and shows an owners/admins-only notice otherwise while still handling gateway 403s. The 201 one-time `token` renders once as `${origin}/invite#token=...` with copy, stays in component state only (never query/storage/logs/analytics), and clears on reset/close. `classifyInviteFailure` maps frozen 403, other 403, 409, 422, 503, and network errors. Listing/revoking invites is not in the UI yet. Covered by `tests/unit/core/invitations/api.test.ts` and `tests/unit/components/workspace/settings/invite-settings-page.dom.test.tsx`.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

### Shared model settings

Settings → Models (`?settings=models`) offers administrator-only catalog management
through `/api/managed-models`. YAML entries are read-only. `core/models/management.ts`
whitelists editable fields so source metadata and `has_api_key` never get posted.
Draft credentials stay in editor state, never query cache or browser storage; blank
keeps the saved key, explicit removal sends an empty key. Saving invalidates both the
admin catalog and `MODELS_QUERY_KEY`. Editor unmount aborts probes and fences late
callbacks. Static demos and non-admin users must not query the management API.

## Full-stack plugin UI

`core/extensions/` loads authenticated deployment-installed ES modules from `/api/plugins`.
Module downloads use the configured backend base and authenticated fetch, then import
and release a Blob URL; packages must be self-contained (no relative module/assets).
This inline transport is experimental; packaged-asset compatibility is documented in
`docs/full-stack-plugins.md`. Host copy belongs in the typed locale dictionaries.
Conversation action factories, shapes and availability callbacks are guarded per plugin;
only validated value snapshots reach the toolbar/sidebar render paths.
`PluginNavigation` and the dynamic workspace extension route consume page declarations;
Capability Center details only show metadata and status. Conversation action slots augment
normal/custom-agent toolbars and sidebar menus without replacing native export or notification.
Plugin views use mount/dispose and abort signals; Shadow DOM is CSS isolation, not a sandbox.
Descriptors are user-keyed page snapshots, refreshed manually. Backend calls bind the plugin's
namespace, action allowlist and expected viewer identity. See `docs/full-stack-plugins.md`.

Plugin page `openConversation(threadId)` resolves authenticated thread metadata
with `pathOfThread`; do not let plugins hardcode default-agent routes. The page's
abort signal fences late navigation after unmount/account changes. Synchronous
conversation-action callbacks reject Promise returns while consuming rejections.

The private Agent Room lives at `/workspace/desk/agent-room`. Its route and
navigation use the existing Desk feature gate; message reads and owner posts use
`core/agent-room` through the shared credential/CSRF fetcher. The Gateway retains
owner/admin isolation and agents post through its separate principal-bound tool.
Room access/message/mutation keys include the actual AuthProvider user ID; wait
for affirmative private discovery before reading or projecting cached messages.
Fence aborted/late reads, old-owner post settlement and composer drafts across
auth transitions, without globally clearing unrelated caches. GET/POST send
`X-Expected-User-Id`; the Gateway must enforce its optional actor mismatch fence
before repository access. The header never grants permission or chooses storage.
Keep existing no-header callers, admin/private gates and CSRF behavior unchanged.
Its roster is a retained descriptive projection, not proof of live workers.
Phone touch overrides belong to the workspace header, Background work, room
composer and phone-only sidebar scope; do not modify generated UI primitives or
desktop density. `tests/e2e/agent-room.spec.ts` covers readback, failed-post draft
retention, the private gate and 390/768/1440 geometry with mocked APIs.

Client inbox/work-plan rules: [CLIENT_PORTAL.md](../backend/docs/CLIENT_PORTAL.md).

## Approvals inbox (`/workspace/approvals`)

List/detail page over `GET/PATCH/POST /api/approvals` (`src/core/approvals/`, `src/components/workspace/approvals/`). It reuses the Board's two-pane layout module. Edits save through `PATCH` and Approve is disabled while the form is dirty, so what is approved is always what was saved. Slack and email get typed fields; ad changes and other types edit as JSON. Keys the form does not show are preserved on save.

Channel connection setup belongs to the caller's private workspace. Use `core/workspaces/hooks.ts` for the sidebar setup handoff and workspace selector; never submit channel setup against a shared workspace. A successful switch hard-navigates to discard old workspace caches.

The sidebar's Easy / Medium / Hard entry opens the existing Experience settings for staff, including account managers. Keep it hidden for client or unresolved roles, matching the Settings dialog's section policy.

AuthProvider refreshes retain the confirmed user on transport/parse failures and
clear it only after a confirmed 401 or explicit identity change. Fence responses
by auth generation and request order; switching between confirmed user IDs must
reload the page so cached responses and mounted observers are discarded together.
Same-user refreshes stay in place. REST and refreshUser 401s share the live-URL,
query-preserving redirect. LangGraph 401s redirect only after a separate raw
`/auth/me` request also confirms 401; retain the SDK's HTTP 401 no-retry behavior.
Validate refresh bodies with `userSchema` and warn on invalid 200 responses.
Logout fences refresh/banner recovery and the shared `redirectOnUnauthorized`
helper used by REST and LangGraph, then clears queries after its POST. A fresh
AuthProvider mount resets that shared logout guard; `useRequireAuth` has no
production callers.
Regression coverage is in `auth-logout-clears-cache.dom.test.tsx` and
`core/api/fetcher.dom.test.ts`.

Mobile sidebar presentation shares `useSidebarExpanded`, while the desktop
collapse preference remains independent. The workspace location watcher closes
the drawer on pathname/query navigation, except a new chat assigning its thread
URL; desktop breakpoint changes also close it. Keep these fixes in workspace components,
with coverage in `ui-polish-mobile.spec.ts`, rather than generated UI primitives.
Installation help stays hidden on authentication/invitation routes; Settings
autofocus targets the resolved role-allowed section. An unresolved role uses the
client-safe section set, so an Invite deep link falls back to Appearance.
The shared `useAgents` list query reports loading during initial feature discovery,
then honors the resolved/sticky Agents flag without toggling the query during
background revalidation. Disabled flags hide cached lists. Keep the unknown-feature outage
fallback; `core/agents/hooks.dom.test.tsx` and `agents-feature-disabled.spec.ts`
cover discovery, disabled results and recovery.

Resolved clients may use the workspace picker for their private legacy chats. Gateway membership gates list/select. Keep private and dedicated searches separate; never infer shared legacy ownership.

`/workspace/reports` renders the staff-only workspace Reports & Leads screen (`components/workspace/reports/`, `core/reports/`). Query keys include the authenticated user and active workspace ID; pending or unavailable feeds render explicit `Pending` / `Unavailable` labels rather than `0`, named-lead match-back rows use a container-query responsive table, and Google Doc review attachments defer validation feedback until blur/submit. Unit and DOM coverage live in `tests/unit/components/workspace/reports-data.test.ts` and `reports.dom.test.tsx`.
