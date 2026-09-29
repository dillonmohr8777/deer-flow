#!/usr/bin/env bash
# Render the launchd templates for this checkout and (re)load them:
#   start at login, health every 15 min, backup nightly at 03:15.
# Containers also carry restart: unless-stopped, so they come back whenever
# OrbStack starts; the start agent covers a stack that was never brought up.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEPLOY_DIR="${MOMOBOT_DEPLOY_DIR:-$HOME/momobot-prod}"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$DEPLOY_DIR/logs" "$DEPLOY_DIR/backups"
mkdir -m 700 -p "$DEPLOY_DIR/secrets"
for tpl in "$REPO"/deploy/momentum/mac/launchd/*.plist; do
  name="$(basename "$tpl")"
  sed -e "s|__REPO__|$REPO|g" -e "s|__DEPLOY__|$DEPLOY_DIR|g" -e "s|__HOME__|$HOME|g" "$tpl" > "$AGENTS/$name"
  plutil -lint "$AGENTS/$name" >/dev/null
  launchctl bootout "gui/$(id -u)/${name%.plist}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name"
  echo "loaded ${name%.plist}"
done
