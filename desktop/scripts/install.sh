#!/bin/sh
# One-command MomoBot install from a release folder (ZIP + SHA256SUMS):
#   sh install.sh <release-dir> [--workspace https://host/workspace]
# Verifies the checksum and signature, installs to ~/Applications (keeping any
# previous app beside it), saves the workspace URL, then runs a hidden smoke test.
set -eu
dir=${1:?usage: install.sh <release-dir> [--workspace https://host/workspace]}
workspace=""
if [ "${2:-}" = "--workspace" ]; then workspace=${3:?--workspace needs a URL}; fi
case "$workspace" in
  "") ;;
  *[\"\\\ ]*) echo "Workspace URL has invalid characters." >&2; exit 1 ;;
  https://*) ;;
  *) echo "Workspace URL must start with https://" >&2; exit 1 ;;
esac

zip="$dir/MomoBot-mac-arm64.zip"
expected=$(awk '$2=="MomoBot-mac-arm64.zip"{print $1}' "$dir/SHA256SUMS")
actual=$(shasum -a 256 "$zip" | awk '{print $1}')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then echo "Checksum mismatch; nothing installed." >&2; exit 1; fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ditto -x -k "$zip" "$tmp"
codesign --verify --deep --strict "$tmp/MomoBot.app"
# The release is ad-hoc signed; the user is installing it on purpose, so clear the download quarantine.
xattr -dr com.apple.quarantine "$tmp/MomoBot.app" 2>/dev/null || true

apps="$HOME/Applications"
mkdir -p "$apps"
if [ -d "$apps/MomoBot.app" ]; then mv "$apps/MomoBot.app" "$apps/MomoBot-previous-$(date +%Y%m%d%H%M%S).app"; fi
mv "$tmp/MomoBot.app" "$apps/MomoBot.app"

if [ -n "$workspace" ]; then
  conf="$HOME/Library/Application Support/MomoBot"
  mkdir -p "$conf"
  (umask 077 && printf '{\n  "endpoint": "%s"\n}\n' "$workspace" > "$conf/connection.json")
fi

# Hidden, sandbox-checked launch; never shows a window or takes focus.
"$apps/MomoBot.app/Contents/MacOS/MomoBot" --smoke-test > "$tmp/smoke.json"
grep -q '"passed":true' "$tmp/smoke.json" || { echo "Installed, but the launch check failed:" >&2; cat "$tmp/smoke.json" >&2; exit 1; }
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$apps/MomoBot.app/Contents/Info.plist")
echo "MomoBot $version installed to $apps/MomoBot.app. Open it and sign in."
