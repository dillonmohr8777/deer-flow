#!/usr/bin/env bash
# Write MomoBot's runtime env to tmpfs before the stack starts (systemd ExecStartPre).
# Secrets come from SSM Parameter Store (/momobot/prod/<VAR>, SecureString) through the
# instance role, so no key sits on the box. The file lives in /run (tmpfs): it is gone on
# reboot and rewritten here at start. An optional host-only 1Password token resolves
# Browserbase credentials. Non-secret settings come from /opt/momobot/settings.env.
# Prints only the key count.
set -euo pipefail
OUT="${MOMOBOT_ENV_FILE:-/run/momobot/.env}"
SSM_PATH="${MOMOBOT_SSM_PATH:-/momobot/prod}"
SETTINGS="${MOMOBOT_SETTINGS:-/opt/momobot/settings.env}"
PYTHON="${MOMOBOT_SECRETS_PYTHON:-python3}"
install -d -m 700 "$(dirname "$OUT")"
tmp="$(umask 077; mktemp "$OUT.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
aws ssm get-parameters-by-path --region "${AWS_REGION:-us-east-2}" --path "$SSM_PATH" --with-decryption --recursive \
  --query 'Parameters[].[Name,Value]' --output json |
  "$PYTHON" "$(dirname "$0")/render_secrets.py" "$SETTINGS" >"$tmp"
[[ -s "$tmp" ]] || { echo "no parameters under $SSM_PATH" >&2; exit 2; }
chmod 600 "$tmp"
mv -f "$tmp" "$OUT"
trap - EXIT
echo "env ready: $(grep -c '=' "$OUT") keys in $OUT"
