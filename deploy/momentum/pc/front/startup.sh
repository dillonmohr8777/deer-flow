#!/bin/bash
# MomoBot front (GCE e2-micro): Caddy TLS for momobot.needmomentum.com, proxies to the PC's tailnet-only origin (never a public Funnel, see ../README.md).
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
    cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.prev 2>/dev/null || rm -f /etc/caddy/Caddyfile.prev
    mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
    if ! systemctl reload caddy; then
      # put the previous file back so the next run still sees a difference and retries the reload
      echo "caddy reload failed; restoring previous Caddyfile" >&2
      if [ -f /etc/caddy/Caddyfile.prev ]; then mv /etc/caddy/Caddyfile.prev /etc/caddy/Caddyfile; else rm -f /etc/caddy/Caddyfile; fi
    fi
    rm -f /etc/caddy/Caddyfile.prev
  fi
else
  echo "caddyfile fetch or validation failed; keeping existing Caddyfile" >&2
  rm -f /etc/caddy/Caddyfile.new
fi
systemctl enable --now caddy
