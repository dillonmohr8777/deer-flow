#!/bin/zsh
# Build, Developer ID sign, notarize, staple and verify MomoBot. Credentials come from the login
# Keychain at runtime and are never echoed or written outside a 0600 temp file removed on exit.
#
# Keychain items (account = $USER), created once per DILLON-STEPS.md:
#   momobot-notary-key-id   App Store Connect API Key ID
#   momobot-notary-issuer   Issuer ID (UUID)
#   momobot-notary-p8       base64 of AuthKey_XXXX.p8
# Optional: MOMOBOT_SIGNING_IDENTITY overrides auto-detected "Developer ID Application: ..." identity.
set -euo pipefail
cd "${0:A:h}/.."

kc() { security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null || { print -u2 "Missing Keychain item: $1"; exit 1; }; }

if [[ -z "${MOMOBOT_SIGNING_IDENTITY:-}" ]]; then
  MOMOBOT_SIGNING_IDENTITY=$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)
  [[ -n "$MOMOBOT_SIGNING_IDENTITY" ]] || { print -u2 "No Developer ID Application identity in Keychain."; exit 1; }
fi
export MOMOBOT_SIGNING_IDENTITY

umask 077
KEYFILE=$(mktemp -t momobot-notary).p8
trap 'rm -f "$KEYFILE"' EXIT INT TERM
kc momobot-notary-p8 | base64 -D > "$KEYFILE"
export APPLE_API_KEY="$KEYFILE"
export APPLE_API_KEY_ID="$(kc momobot-notary-key-id)"
export APPLE_API_ISSUER="$(kc momobot-notary-issuer)"

[[ -d node_modules ]] || npm ci --no-audit --no-fund
npm run check
npm test

OUT="${MOMOBOT_RELEASE_DIR:-$HOME/Documents/Codex/momobot-openai-app-release}"
export MOMOBOT_RELEASE_DIR="$OUT"
# package.cjs signs with hardened runtime + entitlements, notarizes app and DMG, staples and validates.
npm run package:mac >/dev/null

BUILD=$(print -rl -- "$OUT"/build-*(/om[1]))
APP=$(node -e 'process.stdout.write(require(process.argv[1]).appPath)' "$BUILD/build-paths.json")
DMG="$BUILD/MomoBot-mac-arm64.dmg"

codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dv --verbose=4 "$APP" 2>&1 | grep -E 'flags=.*runtime|TeamIdentifier|Authority=Developer ID' >/dev/null || { print -u2 "Hardened runtime / Developer ID authority missing"; exit 1; }
spctl -a -vvv -t exec "$APP"
xcrun stapler validate "$APP"
spctl -a -vvv -t open --context context:primary-signature "$DMG"
xcrun stapler validate "$DMG"

print "Notarized build ready: $BUILD"
