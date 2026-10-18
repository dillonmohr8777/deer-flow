#!/usr/bin/env bash
# Start, build, stop or inspect the MomoBot prod stack on the Lightsail box.
# Same compose layers as the Mac (base + dood + mac/compose.funnel.yaml, which
# fixes the subnet and the realip include) plus the public Caddy overlay.
#
#   up.sh                start or restart (never builds)
#   up.sh build          build gateway + frontend from the checked-out commit
#   up.sh stop           stop the stack (volumes stay)
#   up.sh --what-if      print the merged compose config, change nothing
#   up.sh compose ARGS   any other docker compose command (logs, ps, exec...)
#
# Layout (all outside git): /opt/momobot/{.env,config.yaml,extensions_config.json,
# frontend.env,deer-flow-home}. bootstrap.sh writes .env from SSM.
set -euo pipefail

DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LS="$REPO/deploy/momentum/lightsail"
PROJECT="${MOMOBOT_PROJECT:-momobot-prod}"   # same name as the Mac: volume names carry over
ENV_FILE="$DEPLOY/.env"
PORT="${PORT:-2026}"

for f in "$ENV_FILE" "$DEPLOY/config.yaml" "$DEPLOY/extensions_config.json"; do
  [[ -f "$f" ]] || { echo "Missing $f (bootstrap.sh writes .env; migrate-data.sh import brings the rest)" >&2; exit 2; }
done
[[ "$(stat -c %a "$ENV_FILE")" == "600" ]] || { echo "$ENV_FILE must be mode 600" >&2; exit 2; }

# docker/docker-compose.yaml reads ../.env and ../frontend/.env relative to itself.
mkdir -p "$DEPLOY/deer-flow-home"
[[ -f "$DEPLOY/frontend.env" ]] || install -m 600 /dev/null "$DEPLOY/frontend.env"
ln -sfn "$ENV_FILE" "$REPO/.env"
ln -sfn "$DEPLOY/frontend.env" "$REPO/frontend/.env"

get() { "$REPO/deploy/momentum/vps/dotenv-get.sh" "$ENV_FILE" "$@"; }
export COMPOSE_PROJECT_NAME="$PROJECT"
export PORT
export BIND_HOST=127.0.0.1                      # Caddy is the only public listener
export DEER_FLOW_CONFIG_PATH="$DEPLOY/config.yaml"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$DEPLOY/extensions_config.json"
export DEER_FLOW_HOME="$DEPLOY/deer-flow-home"
export MOMOBOT_REALIP_CONF="$LS/nginx-realip.conf"
export MOMOBOT_CADDYFILE="$REPO/deploy/momentum/vps/Caddyfile"
# Read the two non-secret caddy values without sourcing .env.
MOMOBOT_DOMAIN="$(get MOMOBOT_DOMAIN)"; export MOMOBOT_DOMAIN
MOMOBOT_ACME_EMAIL="$(get MOMOBOT_ACME_EMAIL)"; export MOMOBOT_ACME_EMAIL

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT"
  -f "$REPO/docker/docker-compose.yaml"
  -f "$REPO/docker/docker-compose.dood.yaml"
  -f "$REPO/deploy/momentum/mac/compose.funnel.yaml"
  -f "$REPO/deploy/momentum/vps/compose.public.yaml"
  -f "$LS/compose.caddy-ip.yaml")

case "${1:-up}" in
  --what-if) exec "${compose[@]}" config ;;
  build) exec "${compose[@]}" build gateway frontend ;;   # image names come from MOMENTUM_*_IMAGE
  stop) exec "${compose[@]}" stop ;;
  compose) shift; exec "${compose[@]}" "$@" ;;
  up) ;;
  *) echo "usage: up.sh [up|build|stop|--what-if|compose ARGS...]" >&2; exit 64 ;;
esac

"${compose[@]}" up -d --no-build --wait --wait-timeout 240 redis gateway frontend nginx caddy
deadline=$((SECONDS + 120)); code=000
while (( SECONDS < deadline )); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/health" || true)"
  [[ "$code" == 200 ]] && break
  sleep 2
done
[[ "$code" == 200 ]] || { echo "http://127.0.0.1:$PORT/health did not return 200 (got $code)" >&2; exit 3; }
echo "UI http://127.0.0.1:$PORT/health -> 200. Public: https://$MOMOBOT_DOMAIN/"
