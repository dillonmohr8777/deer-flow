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

# The VPS kit runs Postgres (see ../compose.postgres.yaml); users, threads,
# checkpoints and run_events live there, not in the volume above. Detected
# from POSTGRES_PASSWORD's presence in .env, the same signal compose.postgres.yaml
# itself requires -- never the password's value, which offsite_backup.py never
# needs (pg_dump runs inside the container over its own trusted local socket).
if [[ -n "$(get POSTGRES_PASSWORD "")" ]]; then
  PROJECT="${MOMOBOT_PROJECT:-deer-flow}"
  export MOMOBOT_BACKUP_POSTGRES_CONTAINER="${MOMOBOT_BACKUP_POSTGRES_CONTAINER:-${PROJECT}-postgres}"
  export MOMOBOT_BACKUP_POSTGRES_USER="$(get POSTGRES_USER deerflow)"
  export MOMOBOT_BACKUP_POSTGRES_DB="$(get POSTGRES_DB deerflow)"
fi

if ! docker image inspect "$MOMOBOT_BACKUP_IMAGE" >/dev/null 2>&1; then
  echo "Backup image $MOMOBOT_BACKUP_IMAGE is not on this server; nothing was backed up." >&2
  exit 2
fi
cd "$REPO/deploy/momentum"
exec /usr/bin/python3 offsite_backup.py
