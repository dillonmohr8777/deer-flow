#!/usr/bin/env bash
# MomoBot prod on the PC WSL host (Oct 29, 2026, after AWS paused the Sunlit Servers project).
# Same layers as the Mac Funnel stack: base + dood + mac/compose.funnel.yaml. nginx listens on
# 127.0.0.1:2026 only; Tailscale Funnel on Windows (:8443) terminates TLS. No Caddy, no AWS.
#   pc-up.sh            start or restart (never builds), waits for /health
#   pc-up.sh stop       stop the stack (volumes stay)
#   pc-up.sh compose …  any docker compose command
set -euo pipefail
DEPLOY=/opt/momobot
REPO=$DEPLOY/src
PROJECT=momobot-prod
ENV_FILE=$DEPLOY/.env
for f in "$ENV_FILE" "$DEPLOY/config.yaml" "$DEPLOY/extensions_config.json"; do
  [[ -f "$f" ]] || { echo "Missing $f" >&2; exit 2; }
done
[[ "$(stat -L -c %a "$ENV_FILE")" == "600" ]] || { echo "$ENV_FILE must be mode 600" >&2; exit 2; }
mkdir -p "$DEPLOY/deer-flow-home"
[[ -f "$DEPLOY/frontend.env" ]] || install -m 600 /dev/null "$DEPLOY/frontend.env"
ln -sfn "$ENV_FILE" "$REPO/.env"
ln -sfn "$DEPLOY/frontend.env" "$REPO/frontend/.env"
get() { "$REPO/deploy/momentum/vps/dotenv-get.sh" "$ENV_FILE" "$@"; }
export COMPOSE_PROJECT_NAME=$PROJECT PORT=2026 BIND_HOST=${BIND_HOST:-127.0.0.1}  # only a standby sets BIND_HOST (its VPC address)
export DEER_FLOW_CONFIG_PATH=$DEPLOY/config.yaml
export DEER_FLOW_EXTENSIONS_CONFIG_PATH=$DEPLOY/extensions_config.json
export DEER_FLOW_HOME=$DEPLOY/deer-flow-home
export MOMOBOT_REALIP_CONF=$REPO/deploy/momentum/pc/nginx-realip.conf
MOMENTUM_GATEWAY_IMAGE="$(get MOMENTUM_GATEWAY_IMAGE)"; export MOMENTUM_GATEWAY_IMAGE
MOMENTUM_FRONTEND_IMAGE="$(get MOMENTUM_FRONTEND_IMAGE)"; export MOMENTUM_FRONTEND_IMAGE
compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT"
  -f "$REPO/docker/docker-compose.yaml"
  -f "$REPO/docker/docker-compose.dood.yaml"
  -f "$REPO/deploy/momentum/mac/compose.funnel.yaml")
[[ -f "$DEPLOY/compose.pc.yaml" ]] && compose+=(-f "$DEPLOY/compose.pc.yaml")
case "${1:-up}" in
  stop) exec "${compose[@]}" stop ;;
  compose) shift; exec "${compose[@]}" "$@" ;;
  up) ;;
  *) echo "usage: pc-up.sh [up|stop|compose ...]" >&2; exit 2 ;;
esac
# Restores can widen modes; Brain Forge and the WSL bridge refuse anything that is not private (Oct 29 2026).
V=/var/lib/docker/volumes/${PROJECT}_gateway-data/_data
for d in "$V/brainforge" "$V/wsl-bridge"; do
  [[ -d "$d" ]] && { find "$d" -type d -exec chmod 700 {} +; find "$d" -type f -exec chmod 600 {} +; }
done
"${compose[@]}" up -d --no-build --wait --wait-timeout 300 redis gateway frontend nginx
for _ in $(seq 1 60); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:2026/health || true)" == 200 ]] && { echo "MomoBot healthy on 127.0.0.1:2026"; exit 0; }
  sleep 2
done
echo "/health did not return 200" >&2; exit 3
