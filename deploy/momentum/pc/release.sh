#!/usr/bin/env bash
# One-command PC release with backup first and automatic rollback (installed as /opt/momobot/ops/release.sh).
#   sudo release.sh [--dry-run] [--prune] <sha>
# <sha> is 8+ hex chars of a commit whose images are already built here: deer-flow-gateway:main-<sha8> and
# deer-flow-frontend:main-<sha8> (build step in README). Flow: preflight -> backup.sh (stop on failure) ->
# MAINTENANCE (watchdog stands down) -> switch both image tags in .env -> pc-up.sh -> poll /health/ready up to 3 min
# -> on any failure put the previous tags back and re-run pc-up.sh -> remove MAINTENANCE.
# Releasing the tags already running is a no-op (no backup, no restart). --dry-run prints the plan and changes nothing.
# --prune removes older main-* images but always keeps the new tag and the previous one (the last 2 tags).
# A rollback is the same command with the previous sha: the previous images are kept on purpose.
set -euo pipefail
DEPLOY=${MOMOBOT_DEPLOY:-/opt/momobot}
ENV_FILE=$DEPLOY/.env
BACKUP=${MOMOBOT_BACKUP:-$DEPLOY/ops/backup.sh}
PC_UP=${MOMOBOT_PC_UP:-$DEPLOY/pc-up.sh}
READY_URL=${MOMOBOT_READY_URL:-http://127.0.0.1:2026/health/ready}
READY_TIMEOUT=${MOMOBOT_READY_TIMEOUT:-180}
READY_INTERVAL=${MOMOBOT_READY_INTERVAL:-3}
MAINT=$DEPLOY/MAINTENANCE
LOG=$DEPLOY/release.log
DRY=0; PRUNE=0; SHA=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --prune) PRUNE=1 ;;
    -*) echo "usage: release.sh [--dry-run] [--prune] <sha>" >&2; exit 2 ;;
    *) SHA=$a ;;
  esac
done
[[ "$SHA" =~ ^[0-9a-f]{8,40}$ ]] || { echo "usage: release.sh [--dry-run] [--prune] <sha (8+ hex)>" >&2; exit 2; }
SHA8=${SHA:0:8}
NEW_G=deer-flow-gateway:main-$SHA8; NEW_F=deer-flow-frontend:main-$SHA8
say() { printf '[release %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { say "STOP: $*"; exit 1; }
get_env() { grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d "\"'\r"; }
set_env() { # rewrite one KEY=value line in place (keeps mode and owner of .env; value is an image tag, not a secret)
  local tmp; tmp=$(mktemp)
  awk -v k="$1" -v v="$2" '$0 ~ "^[[:space:]]*" k "=" {print k "=" v; f=1; next} {print} END{if(!f) print k "=" v}' "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
}
wait_ready() {
  local end=$((SECONDS + READY_TIMEOUT)) out code
  while (( SECONDS < end )); do
    out=$(curl -s --max-time 5 -w '\n%{http_code}' "$READY_URL" 2>/dev/null || true); code=${out##*$'\n'}
    [[ "$code" == 200 && "$out" == *'"status":"ready"'* ]] && return 0
    sleep "$READY_INTERVAL"
  done
  return 1
}
apply_tags() { set_env MOMENTUM_GATEWAY_IMAGE "$1"; set_env MOMENTUM_FRONTEND_IMAGE "$2"; "$PC_UP" && wait_ready; }

[[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found"
OLD_G=$(get_env MOMENTUM_GATEWAY_IMAGE); OLD_F=$(get_env MOMENTUM_FRONTEND_IMAGE)
[[ -n "$OLD_G" && -n "$OLD_F" ]] || die "current image tags are not set in $ENV_FILE"
for img in "$NEW_G" "$NEW_F"; do docker image inspect "$img" >/dev/null 2>&1 || die "image $img is not on this host (build it first, see README)"; done
if [[ "$OLD_G" == "$NEW_G" && "$OLD_F" == "$NEW_F" ]]; then say "already running $NEW_G and $NEW_F: nothing to do"; exit 0; fi
[[ -e "$MAINT" ]] && die "$MAINT exists: another release or manual work is in progress"
systemctl is-active --quiet momobot-backup.service && die "a backup is running; wait for it to finish"
if (( DRY )); then
  say "DRY RUN, nothing will change. Plan:"
  say "1. $BACKUP (stop here on failure)"
  say "2. create $MAINT"
  say "3. gateway $OLD_G -> $NEW_G ; frontend $OLD_F -> $NEW_F in $ENV_FILE"
  say "4. $PC_UP, then poll $READY_URL up to ${READY_TIMEOUT}s"
  say "5. on failure: tags back to $OLD_G / $OLD_F, $PC_UP again, poll again, exit 1"
  say "6. remove $MAINT$( ((PRUNE)) && echo ', prune old main-* images except the last 2 tags')"
  exit 0
fi

say "backup first"
"$BACKUP" || die "backup failed; nothing was changed"
: > "$MAINT"; trap 'rm -f "$MAINT"' EXIT
say "switching to $NEW_G / $NEW_F (was $OLD_G / $OLD_F)"
if apply_tags "$NEW_G" "$NEW_F"; then
  say "ready on $NEW_G"
  echo "$(date -u +%FT%TZ) ok $OLD_G -> $NEW_G" >> "$LOG"
  if (( PRUNE )); then
    for repo in deer-flow-gateway deer-flow-frontend; do
      docker images --format '{{.Repository}}:{{.Tag}}' "$repo" | grep ':main-' \
        | grep -vxF -e "$NEW_G" -e "$NEW_F" -e "$OLD_G" -e "$OLD_F" | while read -r old; do say "prune $old"; docker image rm "$old" >/dev/null 2>&1 || true; done
    done
  fi
  exit 0
fi
say "new release did not become ready within ${READY_TIMEOUT}s (or pc-up failed): rolling back to $OLD_G / $OLD_F"
if apply_tags "$OLD_G" "$OLD_F"; then
  echo "$(date -u +%FT%TZ) rolled-back $NEW_G failed, back on $OLD_G" >> "$LOG"
  die "rolled back to $OLD_G and it is ready; investigate $NEW_G before retrying"
fi
echo "$(date -u +%FT%TZ) ROLLBACK-FAILED $NEW_G then $OLD_G" >> "$LOG"
say "ROLLBACK FAILED: tags are back on $OLD_G but the stack is not ready. MAINTENANCE is removed so the watchdog can restart it."
exit 2
