#!/bin/sh
# One-command MomoBot install from a release folder or https download URL (ZIP + SHA256SUMS):
#   sh install.sh <release-dir-or-url> [--workspace https://host/workspace]
#   curl -fsSL <url>/install.sh | sh -s -- <url> --workspace https://host/workspace
# Verifies the checksum and signature, installs to ~/Applications (keeping the
# previous app beside it as MomoBot-previous.app), saves the workspace URL and,
# for an https source, the update URL, then runs a hidden smoke test.
set -eu
dir=${1:?usage: install.sh <release-dir-or-url> [--workspace https://host/workspace]}
workspace=""
if [ "${2:-}" = "--workspace" ]; then workspace=${3:?--workspace needs a URL}; fi
case "$workspace" in
  "") ;;
  *[\"\\\ ?#]*) echo "Workspace URL has invalid characters." >&2; exit 1 ;;
  https://*) ;;
  *) echo "Workspace URL must start with https://" >&2; exit 1 ;;
esac
release_url=""
case "$dir" in
  *[\"\\\ ]*) echo "Release location has invalid characters." >&2; exit 1 ;;
  https://*) release_url="${dir%/}/" ;;
esac
if [ "$(uname -m)" != arm64 ]; then echo "MomoBot needs an Apple Silicon Mac (M1 or newer)." >&2; exit 1; fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
case "$dir" in
  https://*)
    echo "Downloading MomoBot..."
    curl -fsSL "${dir%/}/SHA256SUMS" -o "$tmp/SHA256SUMS"
    curl -fL --progress-bar "${dir%/}/MomoBot-mac-arm64.zip" -o "$tmp/MomoBot-mac-arm64.zip"
    dir="$tmp" ;;
esac
zip="$dir/MomoBot-mac-arm64.zip"
expected=$(awk '$2=="MomoBot-mac-arm64.zip"{print $1}' "$dir/SHA256SUMS")
actual=$(shasum -a 256 "$zip" | awk '{print $1}')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then echo "Checksum mismatch; nothing installed." >&2; exit 1; fi

mkdir "$tmp/app"
ditto -x -k "$zip" "$tmp/app"
codesign --verify --deep --strict "$tmp/app/MomoBot.app"
# The release is ad-hoc signed; the user is installing it on purpose, so clear the download quarantine.
xattr -dr com.apple.quarantine "$tmp/app/MomoBot.app" 2>/dev/null || true

apps="$HOME/Applications"
mkdir -p "$apps"
if [ -d "$apps/MomoBot.app" ]; then rm -rf "$apps/MomoBot-previous.app"; mv "$apps/MomoBot.app" "$apps/MomoBot-previous.app"; fi
mv "$tmp/app/MomoBot.app" "$apps/MomoBot.app"

if [ -n "$workspace" ]; then
  conf="$HOME/Library/Application Support/MomoBot"
  mkdir -p "$conf"
  if [ -n "$release_url" ]; then
    (umask 077 && printf '{\n  "endpoint": "%s",\n  "updateURL": "%s"\n}\n' "$workspace" "$release_url" > "$conf/connection.json")
  else
    (umask 077 && printf '{\n  "endpoint": "%s"\n}\n' "$workspace" > "$conf/connection.json")
  fi
fi

# Hidden, sandbox-checked launch; never shows a window or takes focus.
MOMOBOT_UPDATE_URL="$release_url" "$apps/MomoBot.app/Contents/MacOS/MomoBot" --smoke-test > "$tmp/smoke.json" || true
grep -q '"passed":true' "$tmp/smoke.json" || { echo "Installed, but the launch check failed:" >&2; cat "$tmp/smoke.json" >&2; exit 1; }
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$apps/MomoBot.app/Contents/Info.plist")
echo "MomoBot $version installed to $apps/MomoBot.app. Open it and sign in."
