#!/usr/bin/env bash
# Print one NON-SECRET value from a docker-compose style .env without
# sourcing it (no shell expansion, nothing else leaks into the environment).
# Quotes around the value are stripped. Usage: dotenv-get.sh FILE KEY [DEFAULT]
set -euo pipefail
file="$1"; key="$2"; default="${3:-}"
value=""
if [[ -f "$file" ]]; then
  line="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -1 || true)"
  value="${line#*=}"
  value="${value%$'\r'}"
  if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
    value="${BASH_REMATCH[1]}"
  fi
fi
printf '%s\n' "${value:-$default}"
