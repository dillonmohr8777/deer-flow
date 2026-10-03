# MomoBot desktop distribution

MomoBot desktop is the existing native Electron shell for the private agency. Its backend remains separately deployed; this package does not embed a server, API credentials, client records or cloud handoff. Preserve the existing bundle ID and user-data to retain owner session identity. The default connection is the original local agency at `http://127.0.0.1:2030/workspace`.

## Local owner build

Run `npm ci`, `npm run check`, `npm test`, the hidden smoke against the original login boundary, then `npm run package:mac` from `desktop/`. Outputs live in a fresh timestamped directory; previous releases remain intact. The default signing mode is local ad-hoc integrity. Verify the packaged executable with hidden `--smoke-test --verify-login`, and preserve the installed original bundle before installing an authorized update. Do not confuse a reached login boundary with an authenticated useful agent response.

## Developer ID distribution

Use an already-installed Developer ID Application certificate and an existing Keychain notarytool profile. Both must be named through `MOMOBOT_SIGNING_IDENTITY` and `MOMOBOT_NOTARY_PROFILE`; neither variable contains a secret value. Distribution refuses an uncommitted desktop/icon source, missing identity, incomplete configuration, non-Accepted notarization, failed ticket validation or failed Gatekeeper assessment. This flow submits only the built app ZIP and DMG to Apple. It never creates a key/profile, exports private keys, buys membership or changes provider spending.

Electron Packager signs nested Electron components with hardened runtime. The application ZIP is submitted to Apple, its ticket stapled and validated, then final ZIP and DMG are created. The DMG is signed, submitted, stapled and validated separately. The app passes Gatekeeper assessment before final public metadata is emitted. Apple acceptance must be proven per build; previous signatures do not qualify changed bytes. [Electron Packager signing options](https://electron.github.io/packager/main/interfaces/Options.html), [Apple notarization guidance](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## Publication

Upload only `MomoBot-mac-arm64.zip`, `MomoBot-mac-arm64.dmg`, `release.json` and `SHA256SUMS` to an authorized release destination. Exclude `build-paths.json`, local test evidence, credential/MCP inventories, cloud handoff and any client packet. Public metadata includes package version, Electron version, full Git source revision, dirty state, signing state and artifact digests; no absolute local paths. Ad-hoc builds must remain explicitly labeled local and unnotarized. A prepared workflow does not prove a published release or installed backend. Preserve source branch/PR controls and distinguish source push, built app, local install, public distribution, owner authentication and useful Brain Forge output.
