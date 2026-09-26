#!/usr/bin/env bash
# Health check for always-on MomoBot. The Linux counterpart of health.ps1:
# Docker reachable, the UI and /health/ready answer on loopback, the public
# HTTPS address answers, and the newest encrypted backup receipt is fresh.
# Appends one JSON line per run and exits 1 when anything is wrong.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PORT="${PORT:-2026}"
DOMAIN="${MOMOBOT_DOMAIN:-$("$REPO/deploy/momentum/vps/dotenv-get.sh" "${MOMOBOT_ENV_FILE:-$REPO/.env}" MOMOBOT_DOMAIN)}"
BACKUP_DIR="${MOMOBOT_BACKUP_DEST:-/srv/momobot/backups}"
MAX_BACKUP_AGE_HOURS="${MOMOBOT_MAX_BACKUP_AGE_HOURS:-26}"
LOG="${MOMOBOT_HEALTH_LOG:-/var/log/momobot/health.jsonl}"

probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo 000; }

docker_ok=false; main=000; ready=000; public=000; backup_age=null
if docker info >/dev/null 2>&1; then
  docker_ok=true
  main="$(probe "http://127.0.0.1:$PORT/")"
  ready="$(probe "http://127.0.0.1:$PORT/health/ready")"
fi
[[ -n "$DOMAIN" ]] && public="$(probe "https://$DOMAIN/health")"

newest="$(ls -1t "$BACKUP_DIR"/*.receipt.json 2>/dev/null | head -1 || true)"
if [[ -n "$newest" ]]; then
  backup_age=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 3600 ))
fi

ok=false
if $docker_ok && [[ "$main" == 200 && "$ready" == 200 ]] \
  && { [[ -z "$DOMAIN" ]] || [[ "$public" == 200 ]]; } \
  && [[ "$backup_age" != null ]] && (( backup_age <= MAX_BACKUP_AGE_HOURS )); then
  ok=true
fi

# HTTP codes are strings: a failed probe is "000", and a bare 000 isn't valid JSON.
line="$(printf '{"at":"%s","docker":%s,"main":"%s","ready":"%s","public":"%s","backupAgeHours":%s,"ok":%s}' \
  "$(date -Is)" "$docker_ok" "$main" "$ready" "$public" "$backup_age" "$ok")"
mkdir -p "$(dirname "$LOG")"
echo "$line" >> "$LOG"
echo "$line"
$ok
