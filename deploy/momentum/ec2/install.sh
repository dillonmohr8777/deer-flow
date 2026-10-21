#!/usr/bin/env bash
# One-time (idempotent) EC2 host setup: jq, the Lightsail kit's systemd units plus the EC2
# drop-ins, and the backup bucket name. Run as root with the repo checked out at /opt/momobot/src:
#   sudo MOMOBOT_BACKUP_BUCKET=momobot-prod-backups-<account> /opt/momobot/src/deploy/momentum/ec2/install.sh
set -euo pipefail
SRC=/opt/momobot/src/deploy/momentum
command -v jq >/dev/null || apt-get install -y -qq jq >/dev/null
install -d -m 755 /etc/momobot
if [[ -n "${MOMOBOT_BACKUP_BUCKET:-}" ]]; then
  printf 'MOMOBOT_BACKUP_BUCKET=%s\n' "$MOMOBOT_BACKUP_BUCKET" >/etc/momobot/bootstrap.env
fi
install -m 644 "$SRC"/lightsail/systemd/momobot*.service "$SRC"/lightsail/systemd/momobot*.timer /etc/systemd/system/
for unit in momobot momobot-backup momobot-health; do
  install -d "/etc/systemd/system/$unit.service.d"
  install -m 644 "$SRC/ec2/systemd/momobot-ec2.conf" "/etc/systemd/system/$unit.service.d/ec2.conf"
done
install -m 644 "$SRC/ec2/systemd/momobot-secrets.conf" /etc/systemd/system/momobot.service.d/secrets.conf
systemctl daemon-reload
systemctl enable momobot.service >/dev/null
systemctl enable --now momobot-backup.timer momobot-health.timer >/dev/null
echo "units installed: momobot (starts on boot), backup (nightly to S3), health (every 15 min)"
