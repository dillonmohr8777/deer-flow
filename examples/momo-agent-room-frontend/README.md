# Restore the private Agent Room frontend, phone targets and account isolation

The reviewed backend lane already retains the owner-only Agent Room API and agent
principal-bound room tools, but lacked the frontend feature that was already
present in the running standby image. This follow-up restores the existing route,
feed, owner composer and navigation without replacing the current Board approval
badge, workspace permission gates, model catalog, runtime schedules. A subsequent privacy correction adds a narrow backward-compatible
Gateway expected-owner fence; its matching source must be installed before the
new frontend is used live.

## Provenance and scope

Base: `afb54329d15bedc6f645c777ede0775acdca140b` (PR104).
Verified deployed frontend image:
`sha256:a16ca4cc5bfe2cd7d0296b0d987be3f8f0be0a6866abe97d4b9b47a66b50548d`.
Source retained in `~/code/_worktrees/momo-agent-room-20260926`, HEAD
`9da04668ada00678cdc2e325af5a5af7c582d2bc`, with intentional uncommitted work.
The read-only operator evidence verified all 739 `/app/frontend/src` files in
that image byte-for-byte against the retained source. Its local `.next` build ID
was different, so this evidence proves source identity, not identical local
build output. The retained source and running image were not changed.

Six feature files are carried forward: `src/app/workspace/desk/agent-room/page.tsx`,
`src/components/workspace/agent-room/agent-room.tsx`, and
`src/core/agent-room/{api,hooks,types,index}.ts`. Existing navigation is reconciled
by adding only the private Agent Room entry and its Radio icon; the newer Board
count, accessible label and badge remain intact. The room component and core
files receive normal project formatting. The roster's role/model strings remain
as deployed; they describe the retained team layout and do not assert current
worker activity or approve any private model route.

The workspace header trigger and Background work button now measure at least
44px. The room retry/submit controls also have a 44px minimum. A CSS module scope
on sidebar header/content/footer raises only phone drawer navigation, selectors
and buttons to 44px; action buttons receive their own reserved row space instead
of overlapping links. Desktop density and generated `ui/sidebar.tsx` and
`ui/button.tsx` remain unchanged. No new dependency or lockfile change is needed.

## Verification

- `pnpm install --frozen-lockfile --prefer-offline`.
- `pnpm check`: normal ESLint and strict TypeScript pass.
- `SKIP_ENV_VALIDATION=1 DEER_FLOW_AUTH_DISABLED=1 pnpm build`: production build
  passes, including the restored Agent Room route.
- Existing Background work and Desk unit suites: 16 tests pass.
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3046 PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec
playwright test agent-room.spec.ts desk.spec.ts --workers=2 --reporter=line`:
  11 tests pass using the isolated build and mocked APIs. They cover trimmed
  owner-post readback, rejection retaining the draft, absent private UI when
  Desk is disabled, long evidence text with no horizontal overflow at
  390/768/1440, and phone/header/composer/open-drawer control geometry.
- Headless screenshots are retained under local ignored `frontend/test-results`.

The verification server is bound to localhost and does not load operator
credentials. Unhandled API calls fail locally in the new test fixture. These
are UI fixture results, not production posting, native worker acceptance or
live containment proof. No image replacement, frontend installation, provider
call, live data/config write or browser focus change is included.

## Account isolation correction

Independent tests against the original port reproduced three privacy defects:
old-owner cached messages and late post settlements could appear after an actual
AuthProvider account switch, and a changed shared cookie could save the prior
owner's draft into the newly authenticated owner's Room. The corrected Room
keys caches/access/mutations to the real user ID, masks data until identity and
private access are confirmed, cancels/fences old reads and post settlements, and
binds editor drafts to their authoring owner. Shared fetch transport sends the
captured `X-Expected-User-Id` with credentials/CSRF; the Gateway compares it to
the authenticated actor before repository reads/writes and refuses mismatch
with 409. It never uses the header to authorize or select storage. Legacy callers
without the header and existing admin/private/PAT permissions are preserved.

The reviewed original `67dddd4132d5b4c09316076ba27936158d165006` port and deployed
739-file source remain untouched. Privacy regression tests use the actual
AuthProvider/UserPreferencesBoundary and actual SQLite/AuthMiddleware owner
semantics, including two admins in the same organization. No live write or
provider call is part of these tests.

A prior successful private-access cache is not current admission: mount discovery
is always refreshed, and pending/error discovery hides the feed and refuses
posting until a fresh successful nonfetching result confirms access. Additional
regressions retain normal prior affirmative owner caches to prove that boundary.
