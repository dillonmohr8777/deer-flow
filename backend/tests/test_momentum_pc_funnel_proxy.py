"""f23 on the PC host: the GCE Caddy front is tailscaled's client, so
X-Forwarded-For is always the front VM. Caddy sends the real client in
X-Real-IP and the PC nginx trusts that header from the compose gateway only.
"""

from __future__ import annotations

import pathlib

import yaml

MOMENTUM_DIR = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "momentum"
PC_DIR = MOMENTUM_DIR / "pc"


def _realip_directives() -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for raw in (PC_DIR / "nginx-realip.conf").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, value = line.rstrip(";").partition(" ")
        directives.setdefault(name, []).append(value.strip())
    return directives


def test_pc_nginx_trusts_x_real_ip_from_the_compose_gateway_only():
    overlay = yaml.safe_load((MOMENTUM_DIR / "mac" / "compose.funnel.yaml").read_text(encoding="utf-8"))
    gateway = overlay["networks"]["deer-flow"]["ipam"]["config"][0]["gateway"]
    directives = _realip_directives()
    assert directives["set_real_ip_from"] == [gateway]
    assert directives["real_ip_header"] == ["X-Real-IP"]
    assert directives["real_ip_recursive"] == ["off"]


def test_pc_up_uses_the_pc_realip_conf():
    text = (PC_DIR / "pc-up.sh").read_text(encoding="utf-8")
    assert "MOMOBOT_REALIP_CONF=$REPO/deploy/momentum/pc/nginx-realip.conf" in text


def test_caddy_front_sends_the_client_address_in_x_real_ip():
    text = (PC_DIR / "front" / "Caddyfile").read_text(encoding="utf-8")
    assert "header_up X-Real-IP {remote_host}" in text
