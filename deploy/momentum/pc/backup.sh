#!/usr/bin/env bash
# Nightly MomoBot backup on the PC (off AWS). Online-safe SQLite snapshot (backup_volume.py), config, extensions,
# redis RDB and the /opt/momobot data+code mounts, AES-256 encrypted with /opt/momobot/secrets/backup.key.
# Output: /opt/momobot/backups/momobot-<stamp>.tgz.enc + .json receipt; keeps 7. The Mac copies each new one to GCS.
set -euo pipefail
DEPLOY=/opt/momobot; REPO=$DEPLOY/src; PROJECT=momobot-prod; OUT=$DEPLOY/backups; KEY=$DEPLOY/secrets/backup.key
mkdir -p "$OUT"; umask 077
IMAGE="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMENTUM_GATEWAY_IMAGE)"
STAGE="$(mktemp -d "$DEPLOY/backup-stage.XXXXXX")"; SNAP="${PROJECT}_backup-snap-$$"
cleanup() { docker volume rm -f "$SNAP" >/dev/null 2>&1 || true; rm -rf "$STAGE"; }; trap cleanup EXIT
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker volume create "$SNAP" >/dev/null
docker run --rm --network none --mount "type=volume,source=${PROJECT}_gateway-data,target=/source" \
  --mount "type=volume,source=$SNAP,target=/backup" \
  --mount "type=bind,source=$REPO/deploy/momentum/backup_volume.py,target=/tmp/backup.py,readonly" \
  --entrypoint python "$IMAGE" /tmp/backup.py >/dev/null
docker run --rm --network none --mount "type=volume,source=$SNAP,target=/b,readonly" -v "$STAGE:/out" \
  --entrypoint tar "$IMAGE" czf /out/gateway-data.tgz -C /b --exclude=./agency-evals .
cp "$DEPLOY/config.yaml" "$DEPLOY/extensions_config.json" "$STAGE/"
docker exec "${PROJECT}-redis" redis-cli --rdb - >"$STAGE/redis.rdb" 2>/dev/null
tar czf "$STAGE/ec2-mounts.tgz" -C "$DEPLOY" data code
(cd "$STAGE" && sha256sum ./* >MANIFEST.sha256)
tar czf - -C "$STAGE" . | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass file:"$KEY" -out "$OUT/momobot-$stamp.tgz.enc"
# read-back: decrypt and list, so a bad archive never counts as a backup
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:"$KEY" -in "$OUT/momobot-$stamp.tgz.enc" | tar tzf - > "$STAGE/.list"
grep -q "gateway-data.tgz" "$STAGE/.list" || { rm -f "$OUT/momobot-$stamp.tgz.enc"; echo "read-back failed" >&2; exit 1; }
sha=$(sha256sum "$OUT/momobot-$stamp.tgz.enc" | cut -d' ' -f1); size=$(stat -c %s "$OUT/momobot-$stamp.tgz.enc")
printf '{"state":"PASS","file":"momobot-%s.tgz.enc","sha256":"%s","bytes":%s,"at":"%s"}\n' "$stamp" "$sha" "$size" "$(date -u +%FT%TZ)" > "$OUT/momobot-$stamp.json"
ls -1t "$OUT"/momobot-*.tgz.enc | tail -n +8 | while read -r f; do rm -f "$f" "${f%.tgz.enc}.json"; done
echo "backup ok: $OUT/momobot-$stamp.tgz.enc ($size bytes)"
