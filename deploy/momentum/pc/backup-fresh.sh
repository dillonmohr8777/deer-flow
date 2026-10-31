#!/usr/bin/env bash
# Backup freshness alert (PC, hourly). Emails Dillon when the newest PASS backup is older than THRESHOLD hours (default 14:
# the timer runs every 12 h, so 14 leaves 2 h of grace). Alerts through Composio Gmail (the account the Gmail responder
# uses), at most once per ALERT_EVERY_H hours while stale. Also writes a status word and a JSON line per run.
#   backup-fresh.sh [--threshold-hours N] [--gcs] [--no-email]
#   --gcs         check the newest archive in gs://momobot-backups-m360/gateway/ instead of the local dir. Needs gcloud
#                 or gsutil; the PC has neither, so offsite freshness is only checked where one exists (the Mac).
#   --no-email    print the verdict only (used for tests)
# Settings live in /opt/momobot/ops/backup-fresh.env (not in Git; sourced if present, or export them):
#   ALERT_TO (required to send mail), COMPOSIO_ACCOUNT (Gmail account alias), BUCKET (gs://... prefix, for --gcs),
#   MOMOBOT_BACKUPS (default /opt/momobot/backups), ALERT_RUN_AS (user whose Composio login sends the mail when run as root).
set -uo pipefail
THRESHOLD=14; GCS=0; EMAIL=1
while (( $# )); do
  case "$1" in
    --threshold-hours) THRESHOLD=$2; shift ;;
    --gcs) GCS=1 ;;
    --no-email) EMAIL=0 ;;
    *) echo "usage: backup-fresh.sh [--threshold-hours N] [--gcs] [--no-email]" >&2; exit 2 ;;
  esac
  shift
done
# shellcheck disable=SC1090
[[ -f "${BACKUP_FRESH_ENV:-/opt/momobot/ops/backup-fresh.env}" ]] && . "${BACKUP_FRESH_ENV:-/opt/momobot/ops/backup-fresh.env}"
DIR=${MOMOBOT_BACKUPS:-/opt/momobot/backups}; BUCKET=${BUCKET:-}; ALERT_TO=${ALERT_TO:-}; ALERT_EVERY_H=${ALERT_EVERY_H:-6}
STATE=${STATE_DIR:-/var/lib/momobot-watchdog}; LOG=${LOG_FILE:-/var/log/momobot/backup-fresh.jsonl}
mkdir -p "$STATE" "$(dirname "$LOG")" 2>/dev/null || true
now=$(date -u +%s)

newest_local() { # prints "<epoch> <name>" of the newest PASS receipt
  local f at
  for f in $(ls -1t "$DIR"/momobot-*.json 2>/dev/null); do
    grep -q '"state":"PASS"' "$f" || continue
    at=$(sed -E 's/.*"at":"([^"]+)".*/\1/' "$f")
    python3 -c 'import sys,datetime as d; print(int(d.datetime.strptime(sys.argv[1],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc).timestamp()))' "$at" | tr '\n' ' '
    basename "${f%.json}"; return
  done
}
newest_gcs() {
  local ls
  if command -v gcloud >/dev/null; then ls=$(gcloud storage ls -l "$BUCKET/momobot-*.tgz.enc" 2>/dev/null)
  elif command -v gsutil >/dev/null; then ls=$(gsutil ls -l "$BUCKET/momobot-*.tgz.enc" 2>/dev/null)
  else echo "NOGCS"; return; fi
  printf '%s\n' "$ls" | grep tgz.enc | sort -k2 | tail -1 | python3 -c '
import sys,datetime as d
p=sys.stdin.read().split()
if p: print(int(d.datetime.strptime(p[1],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc).timestamp()), p[2].rsplit("/",1)[-1])'
}
(( GCS )) && [[ -z "$BUCKET" ]] && { echo "--gcs needs BUCKET (gs://... prefix)" >&2; exit 2; }
if (( GCS )); then where="offsite $BUCKET"; res=$(newest_gcs); else where="local $DIR"; res=$(newest_local); fi
if [[ "$res" == NOGCS ]]; then echo "no gcloud or gsutil on this host: cannot check offsite freshness here" >&2; exit 4; fi
if [[ -z "$res" ]]; then age_h=999999; name=none; else age_h=$(awk -v n="$now" -v t="${res%% *}" 'BEGIN{printf "%.2f", (n-t)/3600}'); name=${res#* }; fi
stale=$(awk -v a="$age_h" -v t="$THRESHOLD" 'BEGIN{print (a>t)?1:0}')
word=fresh; (( stale )) && word=STALE
printf '{"at":"%s","where":"%s","newest":"%s","age_hours":%s,"threshold_hours":%s,"state":"%s"}\n' "$(date -u +%FT%TZ)" "$where" "$name" "$age_h" "$THRESHOLD" "$word" >> "$LOG" 2>/dev/null || true
{ echo "$word" > /run/momobot-backup-fresh; } 2>/dev/null || true
echo "$word: newest backup $name is ${age_h}h old (threshold ${THRESHOLD}h, $where)"
(( stale )) || { rm -f "$STATE/backup-fresh-alerted"; exit 0; }
(( EMAIL )) || exit 1
[[ -n "$ALERT_TO" ]] || { echo "stale, but ALERT_TO is not set: no email sent" >&2; exit 1; }
last=$(cat "$STATE/backup-fresh-alerted" 2>/dev/null || echo 0)
if (( now - last < ALERT_EVERY_H * 3600 )); then echo "already alerted within ${ALERT_EVERY_H}h"; exit 1; fi
subject="MomoBot backup is stale: newest is ${age_h}h old"
body="The newest PASS backup on the MomoBot PC host ($where) is $name, ${age_h} hours old; the limit is ${THRESHOLD} hours (backups run at 03:30 and 15:30 ET).
Check: pc-wsl 'systemctl status momobot-backup.service momobot-backup.timer; tail -5 /var/log/momobot/backup-fresh.jsonl; ls -lt /opt/momobot/backups | head'
Runbook: /opt/momobot/src/deploy/momentum/pc/README.md (Backup freshness)."
payload=$(python3 -c 'import json,sys; print(json.dumps({"recipient_email":sys.argv[1],"subject":sys.argv[2],"body":sys.argv[3]}))' "$ALERT_TO" "$subject" "$body")
# receipts are root-only but the Composio login belongs to the operator user, so send as that user when running as root
send=(composio); [[ $EUID -eq 0 && -n "${ALERT_RUN_AS-dillonmohr}" ]] && send=(runuser -u "${ALERT_RUN_AS-dillonmohr}" -- env HOME="/home/${ALERT_RUN_AS-dillonmohr}" "/home/${ALERT_RUN_AS-dillonmohr}/.local/bin/composio")
if "${send[@]}" execute GMAIL_SEND_EMAIL ${COMPOSIO_ACCOUNT:+--account "$COMPOSIO_ACCOUNT"} -d "$payload" >/dev/null 2>&1; then
  echo "$now" > "$STATE/backup-fresh-alerted"; echo "alert emailed to $ALERT_TO"
else echo "alert email FAILED (composio)" >&2; fi
exit 1
