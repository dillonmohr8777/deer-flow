#!/bin/bash
# MomoBot front (GCE e2-micro): Caddy TLS for momobot.needmomentum.com, proxies to the PC's Tailscale Funnel.
set -e
if ! command -v caddy >/dev/null; then
  apt-get update -q && apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
if curl -fsS -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/attributes/caddyfile' > /etc/caddy/Caddyfile.new \
  && [ -s /etc/caddy/Caddyfile.new ] \
  && caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile.new >/dev/null 2>&1; then
  if ! cmp -s /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile; then
    mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
    systemctl reload caddy || echo "caddy reload failed; keeping running config" >&2
  fi
else
  echo "caddyfile fetch or validation failed; keeping existing Caddyfile" >&2
  rm -f /etc/caddy/Caddyfile.new
fi
systemctl enable --now caddy
