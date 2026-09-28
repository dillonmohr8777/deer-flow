#!/usr/bin/env bash
# Nightly encrypted backup of the Mac stack's gateway volume (SQLite DB,
# .jwt_secret, uploads, agents). Wraps ../offsite_backup.py with Mac paths.
# Output: $MOMOBOT_DEPLOY_DIR/backups/*.enc + receipts; key in secrets/ (0600).
set -euo pipefail
umask 077
export PATH="$HOME/.orbstack/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEPLOY_DIR="${MOMOBOT_DEPLOY_DIR:-$HOME/momobot-prod}"
PROJECT="${MOMOBOT_PROJECT:-momobot-prod}"
image="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY_DIR/.env" MOMENTUM_GATEWAY_IMAGE)"
[[ -n "$image" ]] || { echo "MOMENTUM_GATEWAY_IMAGE missing from $DEPLOY_DIR/.env" >&2; exit 2; }
export MOMOBOT_BACKUP_KEY="$DEPLOY_DIR/secrets/momobot-backup.key"
export MOMOBOT_BACKUP_DEST="$DEPLOY_DIR/backups"
export MOMOBOT_BACKUP_VOLUME="${PROJECT}_gateway-data"
export MOMOBOT_BACKUP_IMAGE="$image"
exec uv run --no-project --with cryptography python "$REPO/deploy/momentum/offsite_backup.py"
