#!/usr/bin/env bash
# Move MomoBot prod data between the Mac mini and the Lightsail box, either way.
# Carries the two compose volumes (gateway-data: SQLite deerflow.db, users/,
# memory, .jwt_secret; redis-data) plus config.yaml and extensions_config.json.
# NEVER .env: secrets travel through SSM only. The tarball still holds
# .jwt_secret and users/, so it is mode 600 and short-lived: delete it after.
#
# On the MAC (Dillon runs; each of export/mac-slack-off stops live traffic):
#   migrate-data.sh export              stop the Mac gateway, write the tarball
#   migrate-data.sh mac-slack-off       channels.slack.enabled -> false in the Mac config
#   migrate-data.sh ship KEY IP         scp the newest tarball to the box
#   migrate-data.sh mac-slack-on        undo (rollback)
#   migrate-data.sh mac-restore FILE    rollback: load a return-*.tgz into the Mac volumes
# On the BOX (sudo; Dillon runs):
#   migrate-data.sh import FILE [--force] [--no-start]   load tarball, Slack stays OFF
#   migrate-data.sh slack-on | slack-off                 the Slack cutover switch
#   migrate-data.sh server-export                        rollback: stop, write return-*.tgz
set -euo pipefail

VOL_GW=momobot-prod_gateway-data
VOL_REDIS=momobot-prod_redis-data
PROJECT=momobot-prod
OUT_DIR_DEFAULT="$HOME/momobot-prod/migrate"
OS="$(uname -s)"
ts() { date -u +%Y%m%dT%H%M%SZ; }
die() { echo "ERROR: $*" >&2; exit 1; }

if [[ "$OS" == Darwin ]]; then
  export PATH="$HOME/.orbstack/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
  export DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.orbstack/run/docker.sock}"
  DEPLOY="${MOMOBOT_DEPLOY_DIR:-$HOME/momobot-prod}"
  sha() { shasum -a 256 "$@"; }
else
  DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
  sha() { sha256sum "$@"; }
fi
CONFIG="$DEPLOY/config.yaml"
EXT="$DEPLOY/extensions_config.json"

# tar_out VOLUME FILE  /  tar_in VOLUME FILE: volume <-> tgz through a throwaway alpine.
tar_out() { docker run --rm --network none -v "$1:/v:ro" -v "$(dirname "$2"):/out" alpine \
  tar czf "/out/$(basename "$2")" -C /v --exclude=./agency-evals .; }   # agency-evals is a Mac read-only mount point
tar_in()  { docker run --rm --network none -v "$1:/v" -v "$(dirname "$2"):/in:ro" alpine \
  tar xzf "/in/$(basename "$2")" -C /v; }
vol_nonempty() { docker volume inspect "$1" >/dev/null 2>&1 &&
  [[ -n "$(docker run --rm -v "$1:/v:ro" alpine ls -A /v | head -1)" ]]; }
vol_create() { docker volume inspect "$1" >/dev/null 2>&1 || docker volume create \
  --label "com.docker.compose.project=$PROJECT" --label "com.docker.compose.volume=${1#"${PROJECT}"_}" "$1" >/dev/null; }
vol_wipe() { docker run --rm -v "$1:/v" alpine find /v -mindepth 1 -delete; }

# Flip channels.slack.enabled IN PLACE (truncate + write, same inode): the file is
# bind-mounted into the gateway, and a rename-style edit (sed -i) would leave
# the container looking at the old file.
slack_set() {
  python3 - "$CONFIG" "$1" <<'PY'
import re, sys
path, want = sys.argv[1], "true" if sys.argv[2] == "on" else "false"
s = open(path).read()
new, n = re.subn(r"(^  slack:\n    enabled: )(true|false)", r"\g<1>" + want, s, count=1, flags=re.M)
if n != 1:
    sys.exit("could not find the 'channels: slack: enabled:' block in " + path)
with open(path, "r+") as f:
    f.seek(0); f.write(new); f.truncate()
print(f"channels.slack.enabled -> {want} in {path}")
PY
}

manifest_check() {  # FILE: unpack to a temp dir, verify hashes, assert no .env
  local f="$1" d; d="$(mktemp -d)"; trap 'rm -rf "$d"' RETURN
  tar xzf "$f" -C "$d"
  [[ -z "$(find "$d" -name '.env' -o -name '*.env' | head -1)" ]] || die "tarball contains an env file; refusing"
  (cd "$d" && sha -c MANIFEST.sha256 >/dev/null) || die "MANIFEST.sha256 check failed"
  echo "tarball OK: $(wc -l <"$d/MANIFEST.sha256" | tr -d ' ') files verified"
}

cmd="${1:-}"; shift || true
case "$cmd" in

export)
  [[ "$OS" == Darwin ]] || die "run export on the Mac"
  out="${MOMOBOT_MIGRATE_DIR:-$OUT_DIR_DEFAULT}"; mkdir -p "$out"; chmod 700 "$out"
  docker volume inspect "$VOL_GW" >/dev/null || die "volume $VOL_GW not found"
  [[ -f "$CONFIG" && -f "$EXT" ]] || die "missing $CONFIG or $EXT"
  echo "Mac-local dependencies in config.yaml (these will NOT exist on the box):"
  grep -n 'host.docker.internal' "$CONFIG" | cut -d: -f1 | tr '\n' ' '; echo "<- line numbers"
  echo "Stopping ${PROJECT}-gateway (60 s grace so SQLite checkpoints its WAL)..."
  docker stop -t 60 "${PROJECT}-gateway" >/dev/null 2>&1 || true
  work="$(mktemp -d "$out/work.XXXXXX")"
  tar_out "$VOL_GW" "$work/gateway-data.tgz"
  vol_nonempty "$VOL_REDIS" && tar_out "$VOL_REDIS" "$work/redis-data.tgz" || echo "redis-data empty or missing, skipped"
  cp "$CONFIG" "$work/config.yaml"; cp "$EXT" "$work/extensions_config.json"
  (cd "$work" && sha ./* >MANIFEST.sha256)
  f="$out/momobot-migrate-$(ts).tgz"
  (umask 077; tar czf "$f" -C "$work" .)
  rm -rf "$work"; chmod 600 "$f"
  manifest_check "$f"
  echo "WROTE $f ($(du -h "$f" | cut -f1)). Mac gateway is STOPPED. Next: mac-slack-off, then ship."
  ;;

mac-slack-off) [[ "$OS" == Darwin ]] || die "Mac only"; cp "$CONFIG" "$CONFIG.bak-slack-$(ts)"; slack_set off
  echo "Backup kept next to the config. The Mac gateway must stay stopped (or restarted only after this)." ;;
mac-slack-on)  [[ "$OS" == Darwin ]] || die "Mac only"; slack_set on ;;

ship)
  [[ "$OS" == Darwin ]] || die "run ship on the Mac"
  key="${1:?usage: ship KEY.pem BOX_IP}"; ip="${2:?usage: ship KEY.pem BOX_IP}"
  # shellcheck disable=SC2012
  f="$(ls -1t "${MOMOBOT_MIGRATE_DIR:-$OUT_DIR_DEFAULT}"/momobot-migrate-*.tgz | head -1)"
  [[ -n "$f" ]] || die "no tarball; run export first"
  scp -i "$key" -o IdentitiesOnly=yes "$f" "ubuntu@$ip:/opt/momobot/import/"
  echo "shipped $(basename "$f"). On the box: sudo $(basename "$0") import /opt/momobot/import/$(basename "$f")"
  ;;

mac-restore)  # rollback: server-export tarball -> Mac volumes
  [[ "$OS" == Darwin ]] || die "Mac only"
  f="${1:?usage: mac-restore return-FILE.tgz}"
  docker ps --format '{{.Names}}' | grep -qx "${PROJECT}-gateway" && die "Mac gateway is running; stop it first"
  manifest_check "$f"
  d="$(mktemp -d)"; tar xzf "$f" -C "$d"
  keep="$DEPLOY/backups/pre-restore-$(ts).tgz"; mkdir -p "$DEPLOY/backups"
  tar_out "$VOL_GW" "$keep" && echo "current Mac gateway volume saved to $keep"
  vol_wipe "$VOL_GW"; tar_in "$VOL_GW" "$d/gateway-data.tgz"
  if [[ -f "$d/redis-data.tgz" ]]; then vol_create "$VOL_REDIS"; vol_wipe "$VOL_REDIS"; tar_in "$VOL_REDIS" "$d/redis-data.tgz"; fi
  rm -rf "$d"
  echo "Mac volumes restored. Mac config was NOT touched. Next: mac-slack-on, then deploy/momentum/mac/restart.sh"
  ;;

import)
  [[ "$OS" == Linux && $EUID -eq 0 ]] || die "run import on the box with sudo"
  f="${1:?usage: import FILE [--force] [--no-start]}"; shift
  force=0; start=1
  for a in "$@"; do case "$a" in --force) force=1 ;; --no-start) start=0 ;; *) die "unknown flag $a" ;; esac; done
  REPO="$DEPLOY/src"; LS="$REPO/deploy/momentum/lightsail"
  manifest_check "$f"
  d="$(mktemp -d "$DEPLOY/import/unpack.XXXXXX")"; tar xzf "$f" -C "$d"
  [[ -f "$CONFIG" && -f "$DEPLOY/.env" ]] && "$LS/up.sh" stop >/dev/null 2>&1 || true
  if vol_nonempty "$VOL_GW"; then
    (( force )) || die "$VOL_GW already has data; re-run with --force (a pre-import copy is saved first)"
    tar_out "$VOL_GW" "$DEPLOY/import/pre-import-$(ts).tgz"; vol_wipe "$VOL_GW"
  fi
  vol_create "$VOL_GW"; tar_in "$VOL_GW" "$d/gateway-data.tgz"
  if [[ -f "$d/redis-data.tgz" ]]; then
    vol_create "$VOL_REDIS"; vol_nonempty "$VOL_REDIS" && vol_wipe "$VOL_REDIS"; tar_in "$VOL_REDIS" "$d/redis-data.tgz"
  fi
  # Config: keep a copy of anything already there, point OIDC at the new host,
  # and ship it with Slack OFF so the box and the Mac are never both listening.
  domain="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMOBOT_DOMAIN)"
  [[ -n "$domain" ]] || die "MOMOBOT_DOMAIN missing in $DEPLOY/.env (run bootstrap.sh first)"
  [[ -f "$CONFIG" ]] && cp "$CONFIG" "$CONFIG.bak-$(ts)"
  python3 - "$d/config.yaml" "$CONFIG" "$domain" <<'PY'
import re, sys
src, dst, domain = sys.argv[1:4]
s = open(src).read()
s, n = re.subn(r"https://[A-Za-z0-9.-]+\.ts\.net", "https://" + domain, s)
open(dst, "w").write(s)
print(f"config.yaml: {n} Tailscale URL(s) rewritten to https://{domain}")
PY
  install -m 666 "$d/extensions_config.json" "$EXT"   # gateway edits this file at runtime
  slack_set off
  rm -rf "$d"
  # SQLite integrity check, using the image the gateway runs.
  img="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMENTUM_GATEWAY_IMAGE)"
  if docker image inspect "$img" >/dev/null 2>&1; then
    docker run --rm --network none -v "$VOL_GW:/v" --entrypoint python "$img" -c '
import sqlite3
c = sqlite3.connect("/v/data/deerflow.db")
print("sqlite integrity_check:", c.execute("pragma integrity_check").fetchone()[0])'
  else
    echo "WARN: $img not built yet; run bootstrap.sh, then check integrity by hand"
  fi
  if (( start )); then "$LS/up.sh"; else echo "imported; not started (--no-start). Start: sudo $LS/up.sh"; fi
  echo "Slack is OFF on the box. After Mac slack is off AND sign-in checks pass: sudo $(basename "$0") slack-on"
  ;;

slack-on|slack-off)
  [[ "$OS" == Linux && $EUID -eq 0 ]] || die "run on the box with sudo"
  slack_set "${cmd#slack-}"
  "$DEPLOY/src/deploy/momentum/lightsail/up.sh" compose restart gateway
  ;;

server-export)  # rollback: box -> tarball for mac-restore
  [[ "$OS" == Linux && $EUID -eq 0 ]] || die "run on the box with sudo"
  "$DEPLOY/src/deploy/momentum/lightsail/up.sh" stop
  work="$(mktemp -d "$DEPLOY/import/work.XXXXXX")"
  tar_out "$VOL_GW" "$work/gateway-data.tgz"
  vol_nonempty "$VOL_REDIS" && tar_out "$VOL_REDIS" "$work/redis-data.tgz" || true
  (cd "$work" && sha ./* >MANIFEST.sha256)
  f="$DEPLOY/import/return-$(ts).tgz"; (umask 077; tar czf "$f" -C "$work" .); rm -rf "$work"
  slack_set off
  manifest_check "$f"
  echo "WROTE $f. Box is stopped with Slack off. Pull it: scp -i KEY ubuntu@IP:$f ~/momobot-prod/migrate/  then mac-restore."
  ;;

*) sed -n '2,20p' "$0"; exit 64 ;;
esac
