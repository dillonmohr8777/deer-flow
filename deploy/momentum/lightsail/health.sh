#!/usr/bin/env bash
# Health check: Docker up, gateway readiness, public API and UI, at least 10 GiB
# deployment disk space, newest S3 backup stamp under 26 h. One JSON line per run to
# /var/log/momobot/health.jsonl; exit 1 means look.
set -uo pipefail
DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOMAIN="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "${MOMOBOT_ENV_FILE:-$DEPLOY/.env}" MOMOBOT_DOMAIN)"
LOG="${MOMOBOT_HEALTH_LOG:-/var/log/momobot/health.jsonl}"
STAMP="$DEPLOY/last-backup-ok"            # touched by backup.sh after a verified S3 upload
MAX_AGE_H="${MOMOBOT_MAX_BACKUP_AGE_HOURS:-26}"
probe() { curl -s --location -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo 000; }

docker_ok=false; ready=000; public=000; public_ui=000
if docker info >/dev/null 2>&1; then
  docker_ok=true
  ready="$(probe http://127.0.0.1:2026/health/ready)"
fi
if [[ -n "$DOMAIN" ]]; then
  public="$(probe "https://$DOMAIN/health")"
  public_ui="$(probe "https://$DOMAIN/")"
fi

disk_mib=null; disk_ok=false
if disk_kib="$(df -Pk "$DEPLOY" 2>/dev/null | awk 'NR == 2 {print $4}')" && [[ "$disk_kib" =~ ^[0-9]+$ ]]; then
  disk_mib=$((disk_kib / 1024))
  (( disk_kib >= 10 * 1024 * 1024 )) && disk_ok=true
fi

age=null
[[ -f "$STAMP" ]] && age=$(( ( $(date +%s) - $(stat -c %Y "$STAMP") ) / 3600 ))
ok=false
if $docker_ok && $disk_ok && [[ "$ready" == 200 && "$public" == 200 && "$public_ui" == 200 && "$age" != null ]] && (( age <= MAX_AGE_H )); then ok=true; fi

line="$(printf '{"at":"%s","docker":%s,"ready":"%s","public":"%s","publicUi":"%s","diskAvailableMiB":%s,"backupAgeHours":%s,"ok":%s}' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$docker_ok" "$ready" "$public" "$public_ui" "$disk_mib" "$age" "$ok")"
mkdir -p "$(dirname "$LOG")"
echo "$line" >> "$LOG"
echo "$line"
$ok
