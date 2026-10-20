#!/usr/bin/env bash
# Run on the Mac, by Dillon. Copies each KEY=VALUE from ~/momobot-prod/.env into
# AWS SSM Parameter Store as a SecureString at <path>/KEY, so bootstrap.sh can
# rebuild /opt/momobot/.env on the server. Values are never printed or put on a
# command line (they go to `aws` through stdin JSON). Default is a dry run that
# lists key NAMES only.
#
#   ssm-push.sh            dry run
#   ssm-push.sh --apply    write to SSM (Dillon runs this; needs a live aws login)
set -euo pipefail
ENV_FILE="${MOMOBOT_ENV_FILE:-$HOME/momobot-prod/.env}"
SSM_PATH="${MOMOBOT_SSM_PATH:-/momobot/prod}"
REGION="${AWS_DEFAULT_REGION:-us-east-2}"
# Set per host by bootstrap.sh, so never pushed.
SKIP=" MOMOBOT_DOMAIN MOMOBOT_ACME_EMAIL MOMENTUM_GATEWAY_IMAGE MOMENTUM_FRONTEND_IMAGE "
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 2; }

n=0
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]%$'\r'}"
  [[ "$SKIP" == *" $key "* ]] && continue
  if [[ "$val" =~ ^\"(.*)\"$ || "$val" =~ ^\'(.*)\'$ ]]; then val="${BASH_REMATCH[1]}"; fi
  [[ -n "$val" ]] || { echo "skip (empty): $key"; continue; }
  if [[ "$val" == *"'"* ]]; then echo "skip (contains a single quote, store by hand): $key" >&2; continue; fi
  n=$((n + 1))
  if (( APPLY )); then
    jq -n --arg name "$SSM_PATH/$key" --arg value "$val" \
      '{Name:$name,Value:$value,Type:"SecureString",Overwrite:true}' |
      aws ssm put-parameter --region "$REGION" --cli-input-json file:///dev/stdin >/dev/null
    echo "put   $SSM_PATH/$key"
  else
    echo "would put $SSM_PATH/$key"
  fi
done <"$ENV_FILE"
echo "$n parameter(s) $([[ $APPLY == 1 ]] && echo written || echo 'listed (dry run; add --apply)')"
