# MomoBot distribution — desktop app plus every app store

Design + Phase 1 slice, per task `e15` in `docs/momo-week/QUEUE.md` (Dillon
2026-09-28: "be their boss, check in every now and then, inside the literal
app" and separately "desktop app plus every app store"). Written against the
code as it stands on `lane/momo-week` 2026-10-01.

## 1. What Phase 1 ships

MomoBot is already an installable web app (`frontend/public/manifest.webmanifest`,
`frontend/public/sw.js`, `frontend/src/core/pwa/install.ts`,
`frontend/src/components/pwa/`): Momo-canon icons at 192/512/512-maskable plus
an Apple touch icon, a generic offline shell (`/offline.html`) cached
public-only — no workspace HTML, RSC payload, API result or client file is
ever cached — standalone display, safe-area and reduced-motion handling, and
install guidance for both the native beforeinstallprompt flow and iOS's
manual Add to Home Screen step.

This slice (`momo-week/e15-distribution`) adds the other half of Phase 1's
installable-PWA bullet: a generic web push mechanism. `sw.js` now handles a
`push` event (parses a JSON `{title, body, url}` payload defensively — a
missing payload, a non-JSON body, or a non-string field all fall back to
`"MomoBot"` / empty body / `/workspace`, never thrown) and a
`notificationclick` event (focuses an already-open window on the
notification's target, or opens one). The target `url` is only ever trusted
as a same-origin relative path: an absolute URL, a protocol-relative
`//host/...`, or a backslash variant all collapse to `/workspace` instead of
navigating off-app. See `tests/unit/core/pwa/pwa-service-worker.test.ts` for
the push/notificationclick coverage.

What this slice does **not** do yet: nothing subscribes a browser to push
(`PushManager.subscribe`), no VAPID key pair exists, there is no backend
endpoint to store a subscription or to send a push, and nothing calls one
when a board thread needs the owner's yes (e4's "N waiting on you" signal is
today an in-app badge only, read on load/focus — see
`frontend/src/components/workspace/desk/desk-data.ts`). That is the next
slice, scoped below.

## 2. Desktop: Tauri 2, not the existing Electron prototype

A private, unmerged Electron shell already exists at `desktop/`
(`codex/momobot-openai-app-20260929`, documented in
`docs/MOMOBOT_APP_RELEASE.md`). It is useful prior art — safe-area handling,
an isolated app session that doesn't import browser cookies, bounded
same-origin downloads — but it is not a store-distribution candidate as
built: ad-hoc code signing only (no Developer ID, no notarization), packaged
for one owner's Mac via a local `package:mac` script, and scoped to the
OpenAI-agent surface rather than the general workspace. Electron also ships
a full Chromium + Node runtime per install (~150-200MB), which both slows
notarization/review and works against Apple's size scrutiny for a Mac App
Store submission.

Phase 1 targets **Tauri 2** instead, cutting a new `desktop/` build (the
existing Electron prototype stays as reference until Tauri reaches parity,
then retires):

- **Why Tauri over Electron**: ships the OS's own WebView (WKWebView on
  macOS, WebView2 on Windows) instead of bundling Chromium, so installers run
  single-digit MB instead of 150MB+; it has first-class code-signing and
  notarization config (`tauri.conf.json` → `bundle.macOS.signingIdentity` /
  `bundle.windows.certificateThumbprint`) and an official Apple App Store /
  Microsoft Store bundle target, rather than hand-rolled packaging.
- **macOS**: `.app` bundle, Developer ID signed and notarized for direct
  download; a separate sandboxed build (Tauri's `app-sandbox` entitlement
  profile) for Mac App Store submission — the two differ because App Store
  sandboxing restricts filesystem/network access beyond what Developer ID
  distribution requires.
- **Windows**: MSIX package for the Microsoft Store, plus an NSIS/WiX
  installer signed with an EV or OV code-signing certificate for direct
  download (unsigned Windows installers trigger SmartScreen warnings that
  read as "this app is unsafe" to a non-technical install flow).
- **What it wraps**: the same authenticated Next.js workspace this PWA
  already serves, in a native window — no bundled backend, no embedded
  provider key, matching the existing Electron prototype's isolation model
  (`docs/MOMOBOT_APP_RELEASE.md` "Private setup").
- **Native value for store review**: window-level push notifications (this
  slice's mechanism, once wired to a real subscription), native share
  target registration, and an OS-level "MomoBot is running" tray/menu-bar
  indicator — desktop stores are less strict than Apple's mobile guideline
  4.2 (§3 below) but a bare WebView wrapper with zero native surface is
  still a common rejection reason on both stores.

## 3. Mobile: Capacitor, and what clears Apple guideline 4.2

[App Store Review Guideline 4.2](https://developer.apple.com/app-store/review/guidelines/#minimum-functionality)
rejects a submission that is "merely a repackaged website" with no
native functionality beyond what a browser bookmark already gives. Wrapping
the PWA in **Capacitor** (not a bespoke native rewrite — it reuses this same
web app, consistent with the Tauri decision above: one workspace, three
shells) is necessary but not sufficient; it still needs real native surface:

- **Push notifications** (`@capacitor/push-notifications`): the same
  "needs your yes" signal this slice's service-worker mechanism exists for,
  delivered through APNs/FCM instead of web push — the two coexist, same
  payload shape, different transport.
- **Share sheet** (`@capacitor/share`): share a board thread or a run
  receipt out of MomoBot into Messages/Mail/Slack, and — the harder
  direction Apple actually credits — accept an **incoming** share (a
  screenshot, a link) into a new board thread via a Share Extension target.
- **Biometrics** (`@capacitor/biometric-auth` or an App Store-approved
  equivalent): Face ID/Touch ID/fingerprint to unlock a resumed session
  instead of re-entering the password/MFA flow every open, backed by the
  existing session, never a parallel credential store.
- **Widgets**: a home-screen widget showing the owner-alert count from e4
  ("N waiting on you") — native widget code (WidgetKit on iOS, App Widgets
  on Android), reading a value the main app last wrote, not a live
  re-render of the web app.

Capacitor itself (`npx cap init`, `npx cap add ios`, `npx cap add android`)
wraps the built Next.js static/production output in a thin native shell per
platform; the native plugins above are what a reviewer actually credits as
"native," not the wrapper.

- **iOS**: Capacitor + Xcode project, distributed through App Store Connect
  (TestFlight for beta, then public App Store release).
- **Android**: Capacitor + Android Studio project, an Android App Bundle
  (`.aab`) uploaded to the Google Play Console.

## 4. Accounts and costs Dillon needs to authorize

None of these are purchased or enrolled by this task — distribution work
stops at the doc and the generic push mechanism until Dillon says go, per
the queue's standing rule against spend decisions.

| Account | Cost | Needed for |
| --- | --- | --- |
| Apple Developer Program | $99/yr | Developer ID signing + notarization (macOS direct download), Mac App Store submission, iOS App Store submission, APNs push credentials |
| Google Play Console | $25 one-time | Android app signing, Google Play submission |
| Microsoft Partner Center (Store) | Free for an individual developer account at the time of writing; confirm current pricing at submission time, Microsoft has changed this tier before | Microsoft Store submission (MSIX) |
| Windows code-signing certificate (EV or OV) | Recurring, varies by issuer (roughly $75-400/yr) | Signing the direct-download Windows installer so it does not trigger SmartScreen |

## 5. Why the stable domain has to come first

Every item above assumes a public, stable HTTPS origin. Today's verified
endpoint is `https://dillons-mac-mini.tailade026.ts.net:8445/workspace`
(`docs/MOMOBOT_APP_RELEASE.md`) — a Tailscale Serve hostname reachable only
from devices joined to Dillon's tailnet. That blocks every distribution path
above, not just one of them:

- **App/Play Store review**: both Apple and Google's reviewers install the
  submitted build on a device **not** on Dillon's tailnet and must be able
  to sign in and use it. A `ts.net` origin is simply unreachable to them —
  this alone fails review before any guideline-4.2 or native-functionality
  question is even reached.
- **Web push (VAPID)**: a push subscription's VAPID `aud`/origin is pinned
  to the origin that requested it. Standing up real push now against the
  `ts.net` origin means re-subscribing every installed client once the
  domain moves — better to cut over first.
- **PWA installability and update identity**: the manifest's `id` and
  `start_url`, and the service worker's registration scope, are keyed to
  origin. Moving domains after people have installed the PWA orphans those
  installs (a new origin is a new app, not an update) — same reasoning
  `AGENTS.md`'s nginx/compose bind-host discipline already applies to
  "the published port is the entire external surface."
- **Native deep links**: both Tauri's and Capacitor's universal-link /
  app-link configuration (`apple-app-site-association`,
  `assetlinks.json`) must be hosted at a fixed, publicly resolvable domain
  the OS can fetch over HTTPS at install time — a tailnet-only host cannot
  serve that file to Apple's or Google's verification crawlers.
- **TLS certificate trust**: store review and ordinary end users alike need
  a certificate from a public CA on a domain they can actually resolve;
  Tailscale's cert for a `ts.net` name is valid but meaningless to a device
  outside the tailnet.

`momobot.needmomentum.com` (or an equivalent domain Dillon already controls)
replacing the `ts.net` URL as the production origin — with the existing
password/MFA auth unchanged — is a prerequisite for every remaining
distribution step, not parallel work.

## 6. What's left (next slices)

In rough dependency order:

1. **Stable domain cutover** (§5) — blocks everything below. Needs a Dillon
   decision: which domain, and whether it fronts the current private
   instance or a newly provisioned one.
2. **Real web push wiring**: VAPID key pair, a subscription-storage table
   and `POST /api/push/subscribe` endpoint, a `PushManager.subscribe()` call
   from the frontend (permission-gated, opt-in), and a trigger on the board
   thread transition e4 already detects (`status=drafted`) that sends a push
   through the stored subscription using this slice's payload shape.
   Lighthouse's installable-PWA audit (manifest validity, service-worker
   scope, HTTPS) should be re-run against the stable domain once §1 lands —
   not meaningfully checkable against a tailnet-only origin today, and not
   run in this sandboxed environment (no network access to install the
   `lighthouse` package here).
3. **Tauri desktop build** (§2), after the domain is stable so deep links
   and the in-app URL are fixed at build time.
4. **Capacitor iOS/Android build** (§3), same domain dependency, plus the
   four native plugins guideline 4.2 needs — push reuses §2's payload.
5. Store accounts (§4) enrolled by Dillon once a build is ready to submit.
