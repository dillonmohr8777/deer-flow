#!/usr/bin/env bash
# MomoBot self-heal (PC). Every 2 min: /health on 127.0.0.1:2026. Two misses in a row -> restart the stack.
# Writes one JSON line per run to /var/log/momobot/health.jsonl and a one-word status to /run/momobot-health.
set -u
LOG=/var/log/momobot/health.jsonl; STATE=/var/lib/momobot-watchdog; mkdir -p "$STATE"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:2026/health || echo 000)
disk=$(df -Pm /var/lib/docker | awk 'NR==2{print $4}')
fails=$(cat "$STATE/fails" 2>/dev/null || echo 0)
action=none
if [[ "$code" == 200 ]]; then fails=0; else fails=$((fails+1)); fi
if (( fails >= 2 )); then
  if [[ -f /opt/momobot/MAINTENANCE ]]; then action=skipped-maintenance
  else action=restart; systemctl restart momobot.service >/dev/null 2>&1 && action=restarted || action=restart-failed; fails=0
  fi
fi
echo "$fails" > "$STATE/fails"
st=ok; [[ "$code" == 200 ]] || st=down; (( disk < 10240 )) && st="$st,lowdisk"
echo "$st" > /run/momobot-health
printf '{"at":"%s","health":"%s","fails":%s,"disk_free_mib":%s,"action":"%s"}\n' "$(date -u +%FT%TZ)" "$code" "$fails" "$disk" "$action" >> "$LOG"
