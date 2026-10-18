#!/usr/bin/env bash
# Health check: Docker up, loopback /health and /health/ready, public HTTPS,
# newest S3 backup stamp under 26 h. One JSON line per run to
# /var/log/momobot/health.jsonl; exit 1 means look.
set -uo pipefail
DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOMAIN="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMOBOT_DOMAIN)"
LOG="${MOMOBOT_HEALTH_LOG:-/var/log/momobot/health.jsonl}"
STAMP="$DEPLOY/last-backup-ok"            # touched by backup.sh after a verified S3 upload
MAX_AGE_H="${MOMOBOT_MAX_BACKUP_AGE_HOURS:-26}"
probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo 000; }

docker_ok=false; ready=000; public=000
if docker info >/dev/null 2>&1; then
  docker_ok=true
  ready="$(probe http://127.0.0.1:2026/health/ready)"
fi
[[ -n "$DOMAIN" ]] && public="$(probe "https://$DOMAIN/health")"

age=null
[[ -f "$STAMP" ]] && age=$(( ( $(date +%s) - $(stat -c %Y "$STAMP") ) / 3600 ))
ok=false
if $docker_ok && [[ "$ready" == 200 && "$public" == 200 && "$age" != null ]] && (( age <= MAX_AGE_H )); then ok=true; fi

line="$(printf '{"at":"%s","docker":%s,"ready":"%s","public":"%s","backupAgeHours":%s,"ok":%s}' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$docker_ok" "$ready" "$public" "$age" "$ok")"
mkdir -p "$(dirname "$LOG")"
echo "$line" >> "$LOG"
echo "$line"
$ok
