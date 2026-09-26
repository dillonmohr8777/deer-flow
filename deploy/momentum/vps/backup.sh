#!/usr/bin/env bash
# Nightly encrypted backup of the gateway volume via ../offsite_backup.py.
# The snapshot container must use an image that exists on this server, so it
# follows MOMENTUM_GATEWAY_IMAGE from .env (the tag the stack runs), never
# offsite_backup.py's PC-era default.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ENV_FILE="${MOMOBOT_ENV_FILE:-$REPO/.env}"
get() { "$REPO/deploy/momentum/vps/dotenv-get.sh" "$ENV_FILE" "$@"; }

export MOMOBOT_BACKUP_IMAGE="$(get MOMENTUM_GATEWAY_IMAGE deer-flow-gateway:momentum-m4-20260924)"
export MOMOBOT_BACKUP_KEY="${MOMOBOT_BACKUP_KEY:-/srv/momobot/secrets/momobot-backup.key}"
export MOMOBOT_BACKUP_DEST="${MOMOBOT_BACKUP_DEST:-/srv/momobot/backups}"
export MOMOBOT_BACKUP_VOLUME="${MOMOBOT_BACKUP_VOLUME:-deer-flow_gateway-data}"

if ! docker image inspect "$MOMOBOT_BACKUP_IMAGE" >/dev/null 2>&1; then
  echo "Backup image $MOMOBOT_BACKUP_IMAGE is not on this server; nothing was backed up." >&2
  exit 2
fi
cd "$REPO/deploy/momentum"
exec /usr/bin/python3 offsite_backup.py
