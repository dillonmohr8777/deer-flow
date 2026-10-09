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
