#!/usr/bin/env bash
# Nightly backup to S3: online-safe snapshot of the gateway volume (SQLite via
# the backup API, see ../backup_volume.py), plus config.yaml and
# extensions_config.json. NEVER .env: SSM is the source of truth for secrets.
# Needs AWS credentials for the IAM user in iam-policy.json (root's ~/.aws) and
# MOMOBOT_BACKUP_BUCKET in /etc/momobot/bootstrap.env. The bucket should have
# default encryption on and block public access (RUNBOOK step 3).
set -euo pipefail
DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck disable=SC1091
source /etc/momobot/bootstrap.env
: "${MOMOBOT_BACKUP_BUCKET:?set MOMOBOT_BACKUP_BUCKET in /etc/momobot/bootstrap.env}"
PROJECT="${MOMOBOT_PROJECT:-momobot-prod}"
IMAGE="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMENTUM_GATEWAY_IMAGE)"
STAGE="$(mktemp -d "$DEPLOY/backup-stage.XXXXXX")"
SNAP="${PROJECT}_backup-snap-$$"
cleanup() { docker volume rm -f "$SNAP" >/dev/null 2>&1 || true; rm -rf "$STAGE"; }
trap cleanup EXIT

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker volume create "$SNAP" >/dev/null
docker run --rm --network none \
  --mount "type=volume,source=${PROJECT}_gateway-data,target=/source,readonly" \
  --mount "type=volume,source=$SNAP,target=/backup" \
  --mount "type=bind,source=$REPO/deploy/momentum/backup_volume.py,target=/tmp/backup.py,readonly" \
  --entrypoint python "$IMAGE" /tmp/backup.py >/dev/null
docker run --rm --network none --mount "type=volume,source=$SNAP,target=/b,readonly" \
  -v "$STAGE:/out" alpine tar czf /out/gateway-data.tgz -C /b --exclude=./agency-evals .
cp "$DEPLOY/config.yaml" "$DEPLOY/extensions_config.json" "$STAGE/"
(cd "$STAGE" && sha256sum ./* >MANIFEST.sha256)   # same layout migrate-data.sh import reads
tar czf "$DEPLOY/backup-$stamp.tgz" -C "$STAGE" .
trap 'rm -f "$DEPLOY/backup-$stamp.tgz"; cleanup' EXIT

aws s3 cp "$DEPLOY/backup-$stamp.tgz" "s3://$MOMOBOT_BACKUP_BUCKET/nightly/momobot-$stamp.tgz" --sse AES256 --only-show-errors
# Read-back check: the object exists and the size matches.
local_size="$(stat -c %s "$DEPLOY/backup-$stamp.tgz")"
remote_size="$(aws s3api head-object --bucket "$MOMOBOT_BACKUP_BUCKET" --key "nightly/momobot-$stamp.tgz" --query ContentLength --output text)"
[[ "$local_size" == "$remote_size" ]] || { echo "S3 size mismatch ($local_size vs $remote_size)" >&2; exit 1; }
touch "$DEPLOY/last-backup-ok"
echo "backup ok: s3://$MOMOBOT_BACKUP_BUCKET/nightly/momobot-$stamp.tgz ($local_size bytes)"
# Retention: set a bucket lifecycle rule on nightly/ (RUNBOOK step 3), not here.
