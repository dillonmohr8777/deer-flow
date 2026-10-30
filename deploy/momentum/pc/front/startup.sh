#!/bin/bash
# MomoBot front (GCE e2-micro): Caddy TLS for momobot.needmomentum.com, proxies to the PC's Tailscale Funnel.
set -e
if ! command -v caddy >/dev/null; then
  apt-get update -q && apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
curl -s -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/attributes/caddyfile' > /etc/caddy/Caddyfile.new
if [ -s /etc/caddy/Caddyfile.new ] && ! cmp -s /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile; then
  mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile && systemctl reload caddy || systemctl restart caddy
fi
systemctl enable --now caddy
