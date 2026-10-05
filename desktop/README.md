# MomoBot desktop

This Apple Silicon macOS application opens the existing MomoBot private agency in a persistent, isolated Electron session. It packages the interface shell, not the MomoBot backend or an OpenAI API key. First launch asks for the workspace URL; the default is `http://127.0.0.1:2030/workspace`, the original local private agency entry. A hosted workspace must use HTTPS. The MomoBot menu's Connection command changes the endpoint later.

The shell has context isolation, renderer sandboxing, web security, no Node integration, no preload bridge, and exact-origin navigation. External HTTPS links require an explicit in-app confirmation before opening in the system browser. Unknown protocols and camera/notification permissions are blocked. Same-origin microphone input may request native macOS consent when the website asks for audio. Sign in through the workspace's password/MFA form; this shell does not import browser cookies. SSO redirects to other origins are treated as external links, so browser SSO does not transfer a completed session into this app.

OpenAI artifact downloads, browser screenshots and JSON research evidence work through the app's authenticated fetches. The shell accepts only its own main frame, exact workspace origin, approved artifact/Blob URLs and bounded MIME types. Real download gestures save a unique private file to Downloads; an asynchronous download without a retained gesture requires a Save File confirmation while the app is already focused. Executable filenames, foreign URLs/redirect chains and files over 20 MiB are rejected. Byte counts and the completed file size are checked independently; cancelled, interrupted and oversize partial files are removed. Existing user files are never overwritten, and downloaded files are never launched. All downloads remain denied during hidden smoke tests.

Connection settings are non-secret JSON in Electron's application user-data directory. Cookies remain in Electron's app-specific persistent partition. API credentials belong in the backend credential store. Never place an API key in the URL or this package.

## Development and verification

```sh
cd desktop
npm ci
npm run check
npm test
npm run smoke
# With an accessible workspace and a suitable existing test session:
npm run smoke -- --verify-workspace
# With the production authentication boundary enabled and no test session:
npm run smoke -- --verify-login
npm run package:mac
```

`check` runs strict TypeScript checking over the JavaScript source and ESLint. `smoke` opens a hidden renderer, verifies its native execution isolation and navigation rejection, and exits without activating an app window or opening an external browser. `--verify-workspace` additionally requires the real OpenAI crew heading. Mutually exclusive `--verify-login` loads the configured workspace and requires its production redirect to `/login`, a nonempty login heading and a real form. It does not sign in or submit credentials. Normal `start` intentionally opens the app for its user. Set `MOMOBOT_DESKTOP_URL` to a validated HTTPS or loopback workspace URL to override the saved connection during local use. This variable contains an endpoint, never an API credential.

The packaging script uses the official mouthless Design C headshot from `branding/momobot-design-c-v1.png` for the connection screen and generates the standard macOS ICNS sizes from those same bytes. Its source and checksum are recorded in [branding provenance](branding/SOURCES.md). It creates `.app`, ZIP, DMG, checksums, and `release.json` in a new timestamped directory under `~/Documents/Codex/momobot-openai-app-release`; it does not overwrite an earlier release. Set `MOMOBOT_RELEASE_DIR` to choose another output root.

Electron is pinned to `44.5.0` through the existing lockfile. This release keeps that tested runtime.

By default, packaging uses an ad-hoc local integrity signature and does not claim notarization. For trusted distribution, set both `MOMOBOT_SIGNING_IDENTITY` to an existing Developer ID Application identity name and `MOMOBOT_NOTARY_PROFILE` to an existing notarytool Keychain profile name. Partial or malformed configuration fails before building. This path signs through Electron Packager, requires Apple acceptance, staples and validates tickets on the app and DMG, and assesses the app with Gatekeeper. No raw signing credentials enter the package or release metadata.

`release.json` contains public metadata and artifact basenames only; `SHA256SUMS` verifies ZIP and DMG. `build-paths.json` is a local private locator receipt and must not be uploaded. The package includes only runtime source, UI, exact assets and package metadata. See [distribution instructions](../docs/MOMOBOT_DESKTOP_DISTRIBUTION.md) for publishing boundaries.
