#!/usr/bin/env bash
# Start or restart public MomoBot on the Mac mini (OrbStack + Tailscale Funnel).
# Same --no-build rule as the PC and VPS kits: only image tags built or loaded
# on purpose run here.
#
#   deploy/momentum/mac/restart.sh             start or restart (waits for Docker)
#   deploy/momentum/mac/restart.sh --what-if   print the merged compose config, change nothing
#
# Needs, outside git, in $MOMOBOT_DEPLOY_DIR (default ~/momobot-prod):
#   .env                    mode 600: model keys, image tags, secrets
#   config.yaml             the gateway config
#   extensions_config.json
# and, because docker/docker-compose.yaml reads ../.env and ../frontend/.env
# relative to itself, two symlinks in this checkout:
#   <repo>/.env -> $MOMOBOT_DEPLOY_DIR/.env
#   <repo>/frontend/.env -> $MOMOBOT_DEPLOY_DIR/frontend.env
# Never commit any of them.
set -euo pipefail
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
ENV_FILE="$DEPLOY_DIR/.env"
CONFIG="$DEPLOY_DIR/config.yaml"
EXTENSIONS="$DEPLOY_DIR/extensions_config.json"
PORT="${PORT:-2026}"

# At login OrbStack may still be starting: wait up to 5 minutes.
for _ in $(seq 1 150); do
  docker info >/dev/null 2>&1 && break
  sleep 2
done
if ! docker info >/dev/null 2>&1; then
  echo "Docker engine not reachable. Is OrbStack running?" >&2
  exit 2
fi
for f in "$ENV_FILE" "$CONFIG" "$EXTENSIONS" "$REPO/.env" "$REPO/frontend/.env"; do
  [[ -e "$f" ]] || { echo "Missing $f" >&2; exit 2; }
done
if [[ "$(stat -f %Lp "$ENV_FILE")" != "600" ]]; then
  echo "$ENV_FILE must be mode 600" >&2
  exit 2
fi
# f93(b): nginx-realip.conf trusts XFF from any host-originated connection,
# which a per-thread agent sandbox could reach via host.docker.internal --
# closed only as long as the sandbox's own network has no route to the host,
# which "isolated"/"allowlist" mode guarantees and the code default "open"
# (local_backend.py:593) does not. Refuse to start rather than silently
# publish an unauthenticated way to forge the client IP.
network_mode="$(uv run --no-project --with pyyaml python3 -c '
import sys
import yaml
with open(sys.argv[1], encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
network = ((data.get("sandbox") or {}).get("network")) or {}
print(network.get("mode", "open"))
' "$CONFIG")"
if [[ "$network_mode" != "isolated" && "$network_mode" != "allowlist" ]]; then
  echo "$CONFIG: sandbox.network.mode is '$network_mode', must be \"isolated\" or \"allowlist\" on this publicly-reachable deployment (see nginx-realip.conf)" >&2
  exit 2
fi

export COMPOSE_PROJECT_NAME="$PROJECT"
export PORT
# Loopback only, whatever .env says: Funnel is the only public listener.
export BIND_HOST=127.0.0.1
export DEER_FLOW_CONFIG_PATH="$CONFIG"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$EXTENSIONS"
export DEER_FLOW_HOME="$DEPLOY_DIR/deer-flow-home"
export MOMOBOT_REALIP_CONF="$REPO/deploy/momentum/mac/nginx-realip.conf"

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT"
  -f "$REPO/docker/docker-compose.yaml"
  -f "$REPO/docker/docker-compose.dood.yaml"
  -f "$REPO/deploy/momentum/mac/compose.funnel.yaml")

if [[ "${1:-}" == "--what-if" ]]; then
  exec "${compose[@]}" config
fi

"${compose[@]}" up -d --no-build --wait --wait-timeout 240 redis gateway frontend nginx

deadline=$((SECONDS + 120))
code=000
while (( SECONDS < deadline )); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/health" || true)"
  [[ "$code" == "200" ]] && break
  sleep 2
done
if [[ "$code" != "200" ]]; then
  echo "http://127.0.0.1:$PORT/health did not return 200 (got $code). Check: ${compose[*]} ps" >&2
  exit 3
fi
echo "UI http://127.0.0.1:$PORT/ healthy."
