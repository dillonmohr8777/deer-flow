# MomoBot for iOS

MomoBot is a small SwiftUI shell around a private authenticated workspace. It
adds device-owner authentication, native browser controls, and a strict
navigation boundary. It contains no API keys, cookies, passwords, Tailnet
hostnames, or other embedded credentials.
The app fails closed unless the device has a passcode, Face ID, or Touch ID.

## Requirements

- macOS with full Xcode 16 or newer selected with `xcode-select`
- XcodeGen (`brew install xcodegen`)
- Network access to `https://momobot.needmomentum.com`

The app deliberately uses a non-persistent `WKWebsiteDataStore`. Server cookies
remain in memory while the app is running, but a cold launch can require server
authentication again. There is no custom offline mode or private offline cache.

## Generate and run locally

```sh
cd mobile/ios
swift test --package-path MomoMobileCore
xcodegen generate
open MomoBot.xcodeproj
```

Select the `MomoBot` scheme and a simulator or registered device. The checked-in
project source is `project.yml`; do not commit a hand-edited `.pbxproj`.
The checked-in build opens the production workspace at
`https://momobot.needmomentum.com/workspace`. To target an authorized staging
environment, override the generated project's user-defined
`MOMOBOT_WORKSPACE_URL` build setting or pass it to `xcodebuild`/`archive` on the
command line. Never put credentials in the URL, source, or CI logs.

## Unsigned CI checks

```sh
cd mobile/ios
swift test --package-path MomoMobileCore
xcodegen generate
xcodebuild \
  -project MomoBot.xcodeproj \
  -scheme MomoBot \
  -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Command Line Tools without full Xcode cannot compile an iOS target. Some CLT-only
Swift 6 installations also need this local workaround for the Swift Testing macro:

```sh
swift test --package-path MomoMobileCore \
  -Xswiftc -plugin-path \
  -Xswiftc /Library/Developer/CommandLineTools/usr/lib/swift/host/plugins/testing
```

## Distribution gates

### Internal TestFlight

1. Join the Apple Developer Program, register `com.dillonmohr.momobot`, and set
   the signing team in the private build environment. Certificates and profiles
   never belong in this repository.
2. Create the matching App Store Connect record (the API cannot create it), then
   run the manual `MomoBot iOS TestFlight` workflow
   (`.github/workflows/momobot-ios-testflight.yml`). It archives with Xcode 26,
   signs at export with cloud-managed automatic signing, and uploads. It needs the
   repository secrets `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY` (the `.p8`
   text) and `APPLE_TEAM_ID`, from an App Store Connect Team API key with the
   Admin role. Without them it only checks that the unsigned archive builds.
3. Complete export-compliance, app-privacy, beta-description, feedback-email,
   and test-instructions fields. Privacy answers must include data handled by
   the hosted workspace, not only the native shell.
4. Add internal testers as App Store Connect users and separately authorize
   their MomoBot accounts. A processed build plus both access grants are
   required before testing works.

External TestFlight additionally requires Beta App Review, public privacy and
support URLs, and a reviewer account plus a working network path to the workspace.

### Public App Store

All TestFlight gates still apply, plus:

1. Apple App Review must receive a working review account and sign-in steps in
   App Review Information.
2. Publish a privacy policy and support URL; complete the age rating, category,
   content-rights, account-deletion, and regional compliance questions; and
   provide current iPhone/iPad screenshots and review notes for device auth.
3. Replace the generated 1024 px icon with source artwork at 1024 px or larger
   before submission. The checked-in icon preserves the existing 512 px artwork
   but is necessarily upscaled.
4. Confirm the export-compliance answer for the release. This app currently uses
   only operating-system HTTPS and declares no non-exempt encryption.
5. Pass App Review's minimum-functionality review. Native authentication,
   navigation, loading, and failure handling reduce the web-wrapper risk but do
   not guarantee approval under App Review Guideline 4.2.

Uploads happen only when someone runs the TestFlight workflow by hand. The
workflow only uploads: it adds no testers, starts no Beta App Review, and submits
nothing to the App Store.
