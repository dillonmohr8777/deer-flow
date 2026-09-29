#!/usr/bin/env bash
# Nightly encrypted backup of the Mac stack's gateway volume (SQLite DB,
# .jwt_secret, uploads, agents). Wraps ../offsite_backup.py with Mac paths.
# Output: $MOMOBOT_DEPLOY_DIR/backups/*.enc + receipts; key in secrets/ (0600).
set -euo pipefail
umask 077
export PATH="$HOME/.orbstack/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# Pin the engine to OrbStack (the CLI's default context may be Docker Desktop)
# and, when present, use the deploy dir's docker config: anonymous pulls with a
# no-op credential helper, so nothing waits on a macOS keychain prompt.
export DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.orbstack/run/docker.sock}"
DEPLOY_DIR="${MOMOBOT_DEPLOY_DIR:-$HOME/momobot-prod}"
[[ -d "$DEPLOY_DIR/docker-config" ]] && export DOCKER_CONFIG="$DEPLOY_DIR/docker-config"
[[ -d "$DEPLOY_DIR/bin" ]] && export PATH="$DEPLOY_DIR/bin:$PATH"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROJECT="${MOMOBOT_PROJECT:-momobot-prod}"
image="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY_DIR/.env" MOMENTUM_GATEWAY_IMAGE)"
[[ -n "$image" ]] || { echo "MOMENTUM_GATEWAY_IMAGE missing from $DEPLOY_DIR/.env" >&2; exit 2; }
export MOMOBOT_BACKUP_KEY="$DEPLOY_DIR/secrets/momobot-backup.key"
export MOMOBOT_BACKUP_DEST="$DEPLOY_DIR/backups"
export MOMOBOT_BACKUP_VOLUME="${PROJECT}_gateway-data"
export MOMOBOT_BACKUP_IMAGE="$image"
exec uv run --no-project --with cryptography python "$REPO/deploy/momentum/offsite_backup.py"
