#!/usr/bin/env bash
# Start or restart always-on MomoBot on a Linux VPS. The Linux counterpart of
# deploy/momentum/restart.ps1: same compose files, same --no-build rule (only
# image tags you loaded or built on purpose run here), plus the public Caddy
# overlay and Postgres.
#
#   deploy/momentum/vps/restart.sh             start or restart
#   deploy/momentum/vps/restart.sh --what-if   print the merged compose config, change nothing
#
# Needs, outside git: .env at the repo root (model keys, POSTGRES_PASSWORD,
# GOOGLE_OAUTH_CLIENT_ID/SECRET, MOMOBOT_DOMAIN, MOMOBOT_ACME_EMAIL),
# frontend/.env and extensions_config.json. Never commit any of them.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROJECT="${MOMOBOT_PROJECT:-deer-flow}"
CONFIG="${MOMOBOT_CONFIG:-$REPO/deploy/momentum/workspace.config.postgres.yaml}"
ENV_FILE="${MOMOBOT_ENV_FILE:-$REPO/.env}"
EXTENSIONS="${MOMOBOT_EXTENSIONS:-$REPO/extensions_config.json}"
PORT="${PORT:-2026}"

if ! docker info >/dev/null 2>&1; then
  echo "Docker engine not reachable. Is the docker service running?" >&2
  exit 2
fi
for f in "$ENV_FILE" "$CONFIG" "$EXTENSIONS"; do
  [[ -f "$f" ]] || { echo "Missing $f" >&2; exit 2; }
done

export COMPOSE_PROJECT_NAME="$PROJECT"
export PORT
# nginx's own host port stays on loopback; Caddy is the public listener.
export MOMENTUM_TAILNET_HOST=127.0.0.1
export DEER_FLOW_CONFIG_PATH="$CONFIG"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$EXTENSIONS"
export DEER_FLOW_HOME="$REPO/backend/.deer-flow"
export MOMOBOT_CADDYFILE="$REPO/deploy/momentum/vps/Caddyfile"

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT"
  -f "$REPO/docker/docker-compose.yaml"
  -f "$REPO/docker/docker-compose.dood.yaml"
  -f "$REPO/deploy/momentum/compose.momentum.yaml"
  -f "$REPO/deploy/momentum/compose.postgres.yaml"
  -f "$REPO/deploy/momentum/vps/compose.public.yaml")

if [[ "${1:-}" == "--what-if" ]]; then
  exec "${compose[@]}" config
fi

"${compose[@]}" up -d --no-build --wait --wait-timeout 240 postgres gateway frontend nginx redis caddy

deadline=$((SECONDS + 120))
code=000
while (( SECONDS < deadline )); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/" || true)"
  [[ "$code" == "200" ]] && break
  sleep 2
done
if [[ "$code" != "200" ]]; then
  echo "http://127.0.0.1:$PORT/ did not return 200 (got $code). Check: ${compose[*]} ps" >&2
  exit 3
fi
domain="$("$REPO/deploy/momentum/vps/dotenv-get.sh" "$ENV_FILE" MOMOBOT_DOMAIN "<MOMOBOT_DOMAIN in .env>")"
echo "UI http://127.0.0.1:$PORT/ -> 200. Public: https://$domain/"
