#!/bin/sh
# One-command MomoBot install or update from a release folder or https URL holding MomoBot-mac-arm64.zip:
#   sh install.sh <release-dir-or-url> --sha256 <hash> [--workspace https://host/workspace] [--update-url https://site/]
# Teammates never run this directly: the download site's setup.sh calls it with the release's
# SHA-256 pinned, so a file that doesn't match that exact hash is never installed (the GitHub
# release alone can't change what gets installed). Installs to ~/Applications, keeps the previous
# app as MomoBot-previous.app, saves the workspace and update URLs, then runs a hidden launch check
# and puts the previous app back if that check fails.
# Everything runs inside main(), so a download cut short by `curl | sh` executes nothing.
set -eu

main() {
  src=${1:?usage: install.sh <release-dir-or-url> --sha256 <hash> [--workspace URL] [--update-url URL]}
  shift
  sha="" workspace="" update_url=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --sha256) sha=${2:?--sha256 needs a hash}; shift 2 ;;
      --workspace) workspace=${2:?--workspace needs a URL}; shift 2 ;;
      --update-url) update_url=${2:?--update-url needs a URL}; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done
  case "$sha" in
    *[!0-9a-f]*|"") echo "A 64-character --sha256 is required; use the team install line." >&2; exit 1 ;;
  esac
  [ ${#sha} -eq 64 ] || { echo "A 64-character --sha256 is required; use the team install line." >&2; exit 1; }
  for url in "$workspace" "$update_url"; do
    case "$url" in
      "") ;;
      *[\"\\\ \'\`\$?#]*) echo "URL has invalid characters: $url" >&2; exit 1 ;;
      https://*) ;;
      *) echo "URL must start with https:// : $url" >&2; exit 1 ;;
    esac
  done
  case "$src" in
    *[\"\\\ \'\`\$]*) echo "Release location has invalid characters." >&2; exit 1 ;;
  esac
  if [ "$(uname -m)" != arm64 ]; then echo "MomoBot needs an Apple Silicon Mac (M1 or newer). Intel Macs are not supported." >&2; exit 1; fi

  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  zip="$tmp/MomoBot-mac-arm64.zip"
  case "$src" in
    https://*) echo "Downloading MomoBot..."; curl -fL --progress-bar "${src%/}/MomoBot-mac-arm64.zip" -o "$zip" ;;
    *) cp "$src/MomoBot-mac-arm64.zip" "$zip" ;;
  esac
  actual=$(shasum -a 256 "$zip" | awk '{print $1}')
  if [ "$actual" != "$sha" ]; then echo "Checksum mismatch (got $actual); nothing installed." >&2; exit 1; fi

  mkdir "$tmp/app"
  ditto -x -k "$zip" "$tmp/app"
  codesign --verify --deep --strict "$tmp/app/MomoBot.app"
  # Ad-hoc signed, so Gatekeeper would block it; the pinned hash above is what vouches for this build.
  xattr -dr com.apple.quarantine "$tmp/app/MomoBot.app" 2>/dev/null || true

  apps="$HOME/Applications"
  mkdir -p "$apps"
  if [ -d "$apps/MomoBot.app" ]; then rm -rf "$apps/MomoBot-previous.app"; mv "$apps/MomoBot.app" "$apps/MomoBot-previous.app"; fi
  mv "$tmp/app/MomoBot.app" "$apps/MomoBot.app"

  # Hidden, sandbox-checked launch; never shows a window or takes focus.
  MOMOBOT_UPDATE_URL="$update_url" "$apps/MomoBot.app/Contents/MacOS/MomoBot" --smoke-test > "$tmp/smoke.json" 2>&1 || true
  if ! grep -q '"passed":true' "$tmp/smoke.json"; then
    echo "The new MomoBot failed its launch check:" >&2
    cat "$tmp/smoke.json" >&2
    if [ -d "$apps/MomoBot-previous.app" ]; then
      rm -rf "$apps/MomoBot.app"
      mv "$apps/MomoBot-previous.app" "$apps/MomoBot.app"
      echo "Your previous MomoBot was put back; nothing changed." >&2
    else
      rm -rf "$apps/MomoBot.app"
      echo "Nothing was installed." >&2
    fi
    exit 1
  fi
  # Saved only after the launch check, so a rollback really leaves nothing changed.
  if [ -n "$workspace" ]; then
    conf="$HOME/Library/Application Support/MomoBot"
    mkdir -p "$conf"
    # Keep an owner's Tools opt-in across updates; everything else is rewritten.
    tools=""
    if grep -q '"tools": *true' "$conf/connection.json" 2>/dev/null; then tools=',\n  "tools": true'; fi
    if [ -n "$update_url" ]; then
      (umask 077 && printf "{\n  \"endpoint\": \"%s\",\n  \"updateURL\": \"%s\"$tools\n}\n" "$workspace" "$update_url" > "$conf/connection.json")
    else
      (umask 077 && printf "{\n  \"endpoint\": \"%s\"$tools\n}\n" "$workspace" > "$conf/connection.json")
    fi
  fi

  version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$apps/MomoBot.app/Contents/Info.plist")
  echo "MomoBot $version installed to $apps/MomoBot.app (Finder: Go > Home > Applications). Open it and sign in."
}

main "$@"
