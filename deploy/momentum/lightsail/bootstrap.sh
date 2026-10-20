#!/usr/bin/env bash
# Idempotent: safe to re-run after every release. Run as root on the box:
#   sudo /opt/momobot/src/deploy/momentum/lightsail/bootstrap.sh [--no-build] [--no-start]
#
# 1. checks out MOMOBOT_REF in /opt/momobot/src
# 2. pulls secrets from SSM Parameter Store into /opt/momobot/.env (mode 600)
# 3. builds the gateway + frontend images on this box (x86_64; the repo is public)
# 4. installs + enables the systemd units
# 5. starts the stack (Caddy gets the TLS cert) once config.yaml is in place
#
# Needs /etc/momobot/bootstrap.env (cloud-init writes it) and AWS credentials
# for the IAM user in iam-policy.json (`sudo aws configure`, once; Lightsail
# instances cannot use instance roles).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 2; }

BUILD=1; START=1
for a in "$@"; do
  case "$a" in
    --no-build) BUILD=0 ;;
    --no-start) START=0 ;;
    *) echo "usage: bootstrap.sh [--no-build] [--no-start]" >&2; exit 64 ;;
  esac
done

# shellcheck disable=SC1091
source /etc/momobot/bootstrap.env
: "${MOMOBOT_REF:?}" "${MOMOBOT_DOMAIN:?}" "${MOMOBOT_ACME_EMAIL:?}" "${MOMOBOT_SSM_PATH:?}" "${AWS_DEFAULT_REGION:?}"
export AWS_DEFAULT_REGION
grep -q REPLACE_ME /etc/momobot/bootstrap.env && { echo "fill the REPLACE_ME values in /etc/momobot/bootstrap.env" >&2; exit 2; }
DEPLOY=/opt/momobot
REPO=$DEPLOY/src
LS=$REPO/deploy/momentum/lightsail

# 1. code ---------------------------------------------------------------------
git -C "$REPO" fetch --quiet origin
if git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$MOMOBOT_REF"; then
  git -C "$REPO" checkout --quiet -B "$MOMOBOT_REF" "origin/$MOMOBOT_REF"
else
  git -C "$REPO" checkout --quiet --detach "$MOMOBOT_REF"   # tag or full sha
fi
SHA="$(git -C "$REPO" rev-parse --short=9 HEAD)"
echo "code: $MOMOBOT_REF @ $SHA"

# 2. secrets -> .env (rewritten whole, atomically) ----------------------------
# One SecureString per variable: <path>/<VAR_NAME>. These four are owned here.
aws sts get-caller-identity >/dev/null || { echo "no AWS credentials: run 'sudo aws configure'" >&2; exit 2; }
tmp="$(umask 077; mktemp "$DEPLOY/.env.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
aws ssm get-parameters-by-path --path "$MOMOBOT_SSM_PATH" --with-decryption --recursive \
  --query 'Parameters[].[Name,Value]' --output json |
  jq -r --arg skip 'MOMOBOT_DOMAIN MOMOBOT_ACME_EMAIL MOMENTUM_GATEWAY_IMAGE MOMENTUM_FRONTEND_IMAGE' --arg q "'" '
    ($skip | split(" ")) as $s
    | .[] | (.[0] | split("/") | last) as $k | select($k | IN($s[]) | not)
    | if (.[1] | (contains("\n") or contains($q))) then error("secret \($k) has a newline or single quote; store it without")
      else "\($k)=\($q)\(.[1])\($q)" end' >"$tmp"
[[ -s "$tmp" ]] || { echo "no parameters under $MOMOBOT_SSM_PATH (run ssm-push.sh on the Mac first)" >&2; exit 2; }
{
  echo "MOMOBOT_DOMAIN=$MOMOBOT_DOMAIN"
  echo "MOMOBOT_ACME_EMAIL=$MOMOBOT_ACME_EMAIL"
  echo "MOMENTUM_GATEWAY_IMAGE=deer-flow-gateway:lightsail-$SHA"
  echo "MOMENTUM_FRONTEND_IMAGE=deer-flow-frontend:lightsail-$SHA"
} >>"$tmp"
chmod 600 "$tmp"; chown root:root "$tmp"
mv "$tmp" "$DEPLOY/.env"; trap - EXIT
echo "secrets: $(grep -c . "$DEPLOY/.env") lines written to $DEPLOY/.env (mode 600)"

# 3. build (only when this commit's images are missing) -----------------------
# config.yaml/extensions_config.json may not exist before migrate-data.sh runs;
# compose only needs the files to exist for `build`, so use empty placeholders.
[[ -f $DEPLOY/config.yaml ]] || { PLACEHOLDER_CFG=1; : >"$DEPLOY/config.yaml"; }
[[ -f $DEPLOY/extensions_config.json ]] || { PLACEHOLDER_EXT=1; echo '{}' >"$DEPLOY/extensions_config.json"; }
if (( BUILD )); then
  if docker image inspect "deer-flow-gateway:lightsail-$SHA" "deer-flow-frontend:lightsail-$SHA" >/dev/null 2>&1; then
    echo "images: lightsail-$SHA already built"
  else
    echo "images: building lightsail-$SHA (frontend build takes a while)"
    "$LS/up.sh" build
  fi
  # Pre-pull the sandbox image named in config.yaml so the first agent run is
  # not slow and a bad tag fails here, not at 2am (skipped before migration).
  sb="$(awk '/^sandbox:/{s=1} s&&/^  image:/{print $2; exit}' "$DEPLOY/config.yaml")"
  if [[ -n "$sb" ]]; then docker pull "$sb" >/dev/null || echo "WARN: could not pull sandbox image $sb (x86_64 build available?)" >&2; fi
fi

# 4. systemd ------------------------------------------------------------------
install -m 644 "$LS"/systemd/momobot*.service "$LS"/systemd/momobot*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable momobot.service momobot-health.timer momobot-backup.timer >/dev/null

# 5. start --------------------------------------------------------------------
[[ ${PLACEHOLDER_CFG:-0} == 1 ]] && rm -f "$DEPLOY/config.yaml"
[[ ${PLACEHOLDER_EXT:-0} == 1 ]] && rm -f "$DEPLOY/extensions_config.json"
if (( START )) && [[ -f $DEPLOY/config.yaml && -f $DEPLOY/extensions_config.json ]]; then
  systemctl restart momobot.service
  systemctl start momobot-health.timer momobot-backup.timer
  echo "started. Public: https://$MOMOBOT_DOMAIN/health"
else
  echo "not started: config.yaml / extensions_config.json not in $DEPLOY yet (migrate-data.sh import does it), or --no-start"
fi
