# Desktop verification - September29,2026

Client: Momentum / System: MomoBot desktop / Status: Installed local AppleSilicon app, authenticated private host running / Found: Host owns sign-in and API credentials / Changed: Sandboxed Electron44.5.0 shell, bounded artifact downloads, exact existing brand assets / NeedsApproval: DeveloperID identity for external distribution / NextMove: User signs in with the existing MomoBot account.

## Final validation

- Strict TypeScript/ESLint: passed. Security and download tests:17 passed.
- macOSarm64 app, ZIP and DMG packaged from current source. Ad-hoc codesign verify/deep/strict passed both release and installed app.
- Actual installed executable passed hidden `--smoke-test --verify-login` against private HTTPS8445: redirect to `/login`, sign-in form/password/button present, renderer `require` and `process` undefined, OS sandbox verified, cross-origin navigation blocked. No window activated; no paid provider call.
- Earlier development smoke reached the actual OpenAIcrew workspace at loopback3040 before the authenticated runtime replaced the isolated QA server.
- Authenticated HTTP and headless web evidence is recorded separately in the operator release evidence; native smoke does not claim a signed-in native response or physical iPhone installation.
- API key values were byte-scanned against the packaged ASAR: none bundled. Provider keys remain in an ignored0600 Gateway-only file. The native connection file contains only the workspace URL.

## Installed application

`/Users/dillonmohr/Applications/MomoBot.app`

Saved endpoint: `https://dillons-mac-mini.tailade026.ts.net:8445/workspace/openai`.
Connection file: `~/Library/Application Support/MomoBot/connection.json`,0600.

## Final release artifacts

Build: `/Users/dillonmohr/Documents/Codex/momobot-openai-app-release/build-2026-09-30T03-47-11-433Z`.
ZIP SHA256: `829abf1722de8f27c1479c7631e75f75a3012e49dd068f91f901fcdd542740cd`.
DMG SHA256: `ff2d953ba740ffe59df9c76c9cda2b20f3326a135a3a8d8385651619fd76628b`.
`release.json` records paths/checksums; `desktop-smoke.json` records the actual installed executable result.
Earlier timestamped builds are superseded.

## Download and distribution boundary

Only this window's same-origin authenticated artifacts/PNG/JSON are accepted, with20MiB bounds, safe filenames, explicit user intent, private unique files under Downloads and interrupted-file cleanup. External/executable downloads are rejected; saved files never auto-open. Hidden smoke rejects every download. Unit tests cover these policies; a physical Save interaction remains user-driven.

The app is ad-hoc signed and not notarized; no DeveloperID identity is installed. Public Mac distribution requires DeveloperID signing/notarization. The private iPhone app is a PWA and requires no iOSAppStore build. A harmless macOS helper sandbox-extension warning appeared; actual renderer OS sandboxing remained true.

## 0.2.2 rebuild - October 13, 2026

Built from branch `claude/momobot-desktop-20261013` (origin/main `1f6a22f76`), Electron 44.5.0, arm64. `npm ci`, strict typecheck, ESLint and 21 Node tests passed. Ad-hoc signature verified (`codesign --verify --deep --strict`, flags `adhoc`, identifier `com.momentum.momobot.openai`). Installed to `~/Applications/MomoBot.app`; the 0.2.1 app was kept at `~/Applications/MomoBot-0.2.1-backup.app`. Hidden `--smoke-test --verify-login` with `MOMOBOT_DESKTOP_URL=http://127.0.0.1:2026/workspace` (the installed app's saved endpoint) reached `/login` ("Sign in to MomoBot", password field and button present, renderer `require`/`process` undefined, OS sandbox true, cross-origin navigation blocked, window never shown). Without the env var the smoke test uses the built-in default `http://127.0.0.1:2030/workspace`, because smoke mode ignores the saved connection file.

## Done when

| Criterion | Status Oct 13 | Evidence / gap |
| --- | --- | --- |
| Signed-in session round trip (sign in, open workspace, send a message, get a reply, in the packaged app) | NOT YET | Smoke stops at the login page by design. Needs one real sign-in by Dillon, then a `--verify-workspace` run or a manual message. |
| Persistent connection (endpoint and session survive quit and relaunch) | PARTIAL | Endpoint persists in `connection.json` (confirmed `http://127.0.0.1:2026/workspace`). Cookie persistence needs the signed-in check above. |
| Reboot survival (launch at login) | FAIL | The app has no Login Items support (`setLoginItemSettings` is not called). Add it behind a menu toggle, or add the app to System Settings > Login Items by hand. |
| Notarized build | FAIL | Ad-hoc only. `scripts/package.cjs` already notarizes when `MOMOBOT_SIGNING_IDENTITY` and `MOMOBOT_NOTARY_PROFILE` are set; both need a paid Apple Developer enrollment and a Developer ID certificate. |
| Staff-reachable host | FAIL | Plain HTTP is accepted for loopback only, so the app reaches only this Mac's `:2026`. Staff need a stable HTTPS URL (Tailscale Serve or a public domain). The app already accepts HTTPS hosts. |
| Build, signature, install, hidden smoke to login page | PASS | See above. |

## Tools capability - October 14, 2026
Branch `claude/momobot-desktop-tools-20261014`. `npm run check` and `npm test` (31 tests, 10 new: domain lock, redaction, TOTP vectors, ledger, panel token, MCP stdio) pass; hidden `--smoke-test` still passes. `node scripts/e2e-tools.cjs` (live, through the MCP server): Expand fetch of example.com, Browserbase + Vault login to expand.ai landed on the dashboard (screenshot read back, inputs blurred), the same item was refused on example.com by the domain lock, and a byte scan of MCP output, ledger and screenshots for the password and username (plain, URL, JSON and base64 forms) found no hits. Not covered live: SMS/Gmail codes (code paths unit-tested only), local Chrome backend, the packaged app's Full Disk Access for iMessage.


## October 15 source correction (unreleased draft)

The earlier live-login narrative above is historical and has not been revalidated.
The old acceptance script could exit zero without proving authentication, screenshots,
release or ledger validity. Its PNG byte scan did not prove visual redaction.
Cloud CDP Input.insertText transmits secret text to Browserbase-hosted Chrome.
No new live credential exposure was performed or established in this correction.
Offline source tests are separate from packaged-app acceptance. Real login, cookie
persistence, screenshot visual review and an installed-app round trip remain unverified.
Cloud click/keypress/submit now fail closed pending browser-wide navigation enforcement.

## October 15 independent-review follow-up (unreleased draft)

The first correction's click/keypress block did not cover cloud text input or
`submit:false` secret fill. Those could still trigger page navigation. All cloud
automation now fails closed before session creation, focus, insertion or DOM
evaluation; release/list remain available for cleanup. Local supported actions
remain available. Browser-wide request protection is still absent, so cloud
login acceptance is unavailable, not passed. The live harness exits before any
provider or credential work even with its opt-in variables supplied.

The first correction also counted any tool error as domain-lock evidence. MCP now
carries a policy-generated error category: only `DOMAIN_MISMATCH` qualifies for
that sub-check; `CLOUD_UNAVAILABLE`, protected-site refusal, generic failure and
unconfigured domain lock do not. Overall acceptance additionally requires the
backend to be available. Tests use synthetic proofs and are not live acceptance.

Secret insertion now rechecks the complete saved-domain lock after focus for
password and code paths. Offline regressions cover off-domain navigation,
HTTPS downgrade, protected hosts, input-triggered cloud navigation, denial
categories and overall acceptance. These checks do not establish atomic
protection against every asynchronous hostile-page race or visual redaction.
