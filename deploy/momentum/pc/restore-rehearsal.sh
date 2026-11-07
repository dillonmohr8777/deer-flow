#!/usr/bin/env bash
# Restore rehearsal for the PC host. Decrypts the newest backup (or a named stamp), verifies MANIFEST.sha256,
# restores it into scratch docker volumes and starts a second gateway stack that is never exposed:
#   - gateway + redis sit on an --internal docker network (no egress, so Slack, LLMs and the scheduler cannot
#     reach anything, and no prod secret is copied in; the app env is dummy values)
#   - a small nginx publishes 127.0.0.1:$PORT -> scratch gateway only
#   - every object is named momoreh-<run>*; prod containers, volumes and the prod compose project are never touched
# Compares row counts with prod (counts only, read-only), prints a timing table, then removes everything it made.
#   sudo restore-rehearsal.sh [stamp|newest]      KEEP=1 keeps the scratch stack; PORT=2927 changes the port
set -euo pipefail
DEPLOY=/opt/momobot; KEY=$DEPLOY/secrets/backup.key; BK=$DEPLOY/backups; PROJECT=momobot-prod
PORT=${PORT:-2927}; RUN=$(date -u +%m%d%H%M%S); P=momoreh-$RUN
WORK=$DEPLOY/restore/rehearsal-$RUN; INT=$P-net
GW=$P-gateway; RD=$P-redis; PX=$P-proxy; VG=${P}_gateway-data; VR=${P}_redis-data
IMAGE="$("$DEPLOY/src/deploy/momentum/vps/dotenv-get.sh" "$DEPLOY/.env" MOMENTUM_GATEWAY_IMAGE)"
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 2; }
if systemctl is-active --quiet momobot-backup.service; then echo "a backup is running; wait for it" >&2; exit 3; fi
ss -ltn | grep -q ":$PORT " && { echo "port $PORT is in use" >&2; exit 3; }
TIMES=(); t0=$(date +%s.%N)
step() { local n=$1; shift; local s=$(date +%s.%N); "$@"; TIMES+=("$(awk -v a="$s" -v b="$(date +%s.%N)" -v n="$n" 'BEGIN{printf "%-34s %7.1fs", n, b-a}')"); echo "[$n] done"; }
teardown() {
  [[ "${KEEP:-0}" == 1 ]] && { echo "KEEP=1: scratch stack $P left running on 127.0.0.1:$PORT"; return; }
  docker rm -f "$PX" "$GW" "$RD" >/dev/null 2>&1 || true
  docker network rm "$INT" >/dev/null 2>&1 || true
  docker volume rm -f "$VG" "$VR" >/dev/null 2>&1 || true
  rm -rf "$WORK"
  echo "teardown: removed containers $PX $GW $RD, network $INT, volumes $VG $VR, dir $WORK"
}
trap teardown EXIT
mkdir -p "$WORK/stage"; chmod 700 "$WORK"

pick() {
  local want=${1:-newest} r
  if [[ $want == newest ]]; then r=$(ls -1t "$BK"/momobot-*.json | head -1); else r="$BK/momobot-$want.json"; fi
  STAMP=$(basename "${r%.json}"); ENC="$BK/$STAMP.tgz.enc"
  grep -q '"state":"PASS"' "$r" || { echo "receipt $r is not PASS" >&2; exit 4; }
  [[ "$(sha256sum "$ENC" | cut -d' ' -f1)" == "$(sed -E 's/.*"sha256":"([0-9a-f]+)".*/\1/' "$r")" ]] || { echo "archive sha256 differs from receipt" >&2; exit 4; }
  echo "archive $STAMP ($(stat -c %s "$ENC") bytes) matches its receipt"
}
decrypt() { openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:"$KEY" -in "$ENC" | tar xzf - -C "$WORK/stage"; }
manifest() { (cd "$WORK/stage" && sha256sum -c MANIFEST.sha256); }
restore_volumes() {
  docker volume create "$VG" >/dev/null; docker volume create "$VR" >/dev/null
  docker run --rm --network none -v "$VG:/d" -v "$WORK/stage:/in:ro" --entrypoint tar "$IMAGE" xzf /in/gateway-data.tgz -C /d
  docker run --rm --network none -v "$VR:/d" -v "$WORK/stage:/in:ro" --entrypoint sh "$IMAGE" -c 'cp /in/redis.rdb /d/dump.rdb'
  # same re-privatizing as pc-up.sh: Brain Forge and the WSL bridge refuse non-private modes
  local v=/var/lib/docker/volumes/$VG/_data
  for d in "$v/brainforge" "$v/wsl-bridge"; do [[ -d $d ]] && { find "$d" -type d -exec chmod 700 {} +; find "$d" -type f -exec chmod 600 {} +; }; done
  mkdir -p "$WORK/mounts" && tar xzf "$WORK/stage/ec2-mounts.tgz" -C "$WORK/mounts"
}
start_stack() {
  # scratch config: Slack and the scheduler off, so even a leaked route cannot act; secrets stay out of the scratch env
  cp "$WORK/stage/config.yaml" "$WORK/config.yaml"; cp "$WORK/stage/extensions_config.json" "$WORK/extensions_config.json"
  python3 - "$WORK/config.yaml" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
s = re.sub(r"(?m)^(scheduler:\n  enabled:) true", r"\1 false", s)
s = re.sub(r"(?m)^(  slack:\n    enabled:) true", r"\1 false", s)
open(p, "w").write(s)
PY
  docker network create --internal "$INT" >/dev/null
  docker run -d --name "$RD" --network "$INT" --network-alias redis -v "$VR:/data" redis:7-alpine >/dev/null
  local m="$WORK/mounts"
  local args=(-d --name "$GW" --network "$INT" --network-alias gateway --memory 4g --cpus 2 -w /app
    -e CI=true -e DEER_FLOW_PROJECT_ROOT=/app -e DEER_FLOW_HOME=/app/backend/.deer-flow
    -e DEER_FLOW_CONFIG_PATH=/app/backend/config.yaml -e DEER_FLOW_EXTENSIONS_CONFIG_PATH=/app/backend/extensions_config.json
    -e DEER_FLOW_STREAM_BRIDGE_REDIS_URL=redis://redis:6379/0
    -e DEER_FLOW_CHANNELS_LANGGRAPH_URL=http://gateway:8001/api -e DEER_FLOW_CHANNELS_GATEWAY_URL=http://gateway:8001
    -e GATEWAY_WORKERS=1 -e "DEER_FLOW_INTERNAL_AUTH_TOKEN=rehearsal-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    -e ANTHROPIC_API_KEY=rehearsal-dummy -e GOOGLE_OAUTH_CLIENT_ID=rehearsal-dummy -e GOOGLE_OAUTH_CLIENT_SECRET=rehearsal-dummy
    -e SLACK_APP_TOKEN=rehearsal-dummy -e SLACK_BOT_TOKEN=rehearsal-dummy
    -v "$WORK/config.yaml:/app/backend/config.yaml:ro" -v "$WORK/extensions_config.json:/app/backend/extensions_config.json"
    -v "$VG:/app/backend/.deer-flow")
  [[ -d $m/data/skills ]] && args+=(-v "$m/data/skills:/app/skills:ro")
  [[ -d $m/data/admission ]] && args+=(-v "$m/data/admission:/var/momo-admission")
  [[ -d $m/data/lobby-notes ]] && args+=(-v "$m/data/lobby-notes:/var/momo-lobby-notes:ro")
  [[ -d $m/data/people ]] && args+=(-v "$m/data/people:/var/momo-people:ro")
  [[ -d $m/data/brand ]] && args+=(-v "$m/data/brand:/var/momobot-brand:ro")
  [[ -d $m/code ]] && args+=(-v "$m/code/momo_guard.py:/app/backend/packages/harness/deerflow/community/browser_automation/momo_guard.py:ro"
    -v "$m/code/momo_protocol.py:/app/backend/packages/harness/deerflow/community/browser_automation/momo_protocol.py:ro")
  # operator extension (inert unless config names it): reuse the prod bind source read-only so a missing path cannot fail the start
  local ext; ext=$(awk '/source: \/opt\/momobot\/extensions\//{print $2; exit}' "$DEPLOY/compose.pc.yaml" 2>/dev/null || true)
  [[ -n "$ext" && -d "$ext" ]] && args+=(-v "$ext:/app/backend/$(basename "$ext"):ro")
  docker run "${args[@]}" "$IMAGE" sh -c "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --workers 1" >/dev/null
  printf 'server { listen 80; location / { proxy_pass http://gateway:8001; proxy_set_header Host $host; } }\n' > "$WORK/proxy.conf"
  docker create --name "$PX" -p "127.0.0.1:$PORT:80" -v "$WORK/proxy.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine >/dev/null
  docker network connect --alias gateway-proxy "$INT" "$PX"; docker start "$PX" >/dev/null
}
wait_health() {
  for _ in $(seq 1 90); do
    [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/health" || true)" == 200 ]] && break; sleep 2
  done
  HEALTH=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/health" || true)
  READY=$(curl -s --max-time 5 "http://127.0.0.1:$PORT/health/ready" || true)
  echo "scratch /health=$HEALTH /health/ready=$READY"
  [[ $HEALTH == 200 ]] || { docker logs --tail 40 "$GW" >&2 || true; exit 5; }
}
COUNT_PY='
import sqlite3, sys
c = sqlite3.connect("file:/d/data/deerflow.db?mode=ro", uri=True)
for t in ("users","threads_meta","runs","run_events","checkpoints","organizations","clients","scheduled_tasks","audit_events"):
    print(t, c.execute(f"select count(*) from [{t}]").fetchone()[0])'
compare() {
  docker run --rm --network none -v "${PROJECT}_gateway-data:/d:ro" --entrypoint python "$IMAGE" -c "$COUNT_PY" > "$WORK/prod.counts"
  docker run --rm --network none -v "$VG:/d:ro" --entrypoint python "$IMAGE" -c "$COUNT_PY" > "$WORK/scratch.counts"
  echo "table                 prod  restored  delta(prod-restored)"
  join <(sort "$WORK/prod.counts") <(sort "$WORK/scratch.counts") | awk '{printf "%-20s %6d %8d %6d\n", $1, $2, $3, $2-$3}'
}
step "pick+verify receipt" pick "${1:-newest}"
step "decrypt+extract" decrypt
step "MANIFEST.sha256 check" manifest
step "restore into scratch volumes" restore_volumes
step "start scratch stack" start_stack
step "wait for /health" wait_health
step "row counts vs prod" compare
total=$(awk -v a="$t0" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
echo; echo "== timing =="; printf '%s\n' "${TIMES[@]}"; echo "total (excl. teardown)            ${total}s"
