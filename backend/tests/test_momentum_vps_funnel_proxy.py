"""f23 on the VPS/Caddy deploy: one internet client's failed logins must not
lock out everyone else.

Chain: browser -> Caddy (public 80/443, terminates TLS, sets X-Forwarded-For
to the real client since nothing sits in front of it) -> nginx (arrives from
Caddy's fixed compose address) -> Gateway (arrives from nginx). The Gateway
keys its login limiter on the TCP peer unless that peer is in
AUTH_TRUSTED_PROXIES, in which case it takes nginx's X-Real-IP. Without the
overlay every request would share nginx's bucket; these tests pin the
overlay's addresses to each other and drive the real login route from
nginx's address. Same shape as test_momentum_mac_funnel_proxy.py, with Caddy
standing in for tailscaled.
"""

from __future__ import annotations

import ipaddress
import pathlib
import re

import httpx
import pytest
import yaml
from fastapi import FastAPI

from app.gateway.routers import auth as auth_router

VPS_DIR = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "momentum" / "vps"


def _overlay() -> dict:
    return yaml.safe_load((VPS_DIR / "compose.public.yaml").read_text(encoding="utf-8"))


def _realip_directives() -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for raw in (VPS_DIR / "nginx-realip.conf").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, value = line.rstrip(";").partition(" ")
        directives.setdefault(name, []).append(value.strip())
    return directives


def _addresses() -> tuple[ipaddress.IPv4Network, ipaddress.IPv4Address, ipaddress.IPv4Address, str]:
    overlay = _overlay()
    ipam = overlay["networks"]["deer-flow"]["ipam"]["config"][0]
    subnet = ipaddress.ip_network(ipam["subnet"])
    caddy_ip = ipaddress.ip_address(overlay["services"]["caddy"]["networks"]["deer-flow"]["ipv4_address"])
    nginx_ip = ipaddress.ip_address(overlay["services"]["nginx"]["networks"]["deer-flow"]["ipv4_address"])
    env = dict(item.split("=", 1) for item in overlay["services"]["gateway"]["environment"])
    return subnet, caddy_ip, nginx_ip, env["AUTH_TRUSTED_PROXIES"]


def test_overlay_trusts_exactly_one_hop_at_each_layer():
    subnet, caddy_ip, nginx_ip, trusted = _addresses()
    assert caddy_ip in subnet and nginx_ip in subnet and nginx_ip != caddy_ip

    directives = _realip_directives()
    # nginx believes X-Forwarded-For only from Caddy's fixed address, never
    # from another container on the compose network.
    assert directives["set_real_ip_from"] == [str(caddy_ip)]
    assert directives["real_ip_header"] == ["X-Forwarded-For"]
    assert directives["real_ip_recursive"] == ["off"]

    # The Gateway believes X-Real-IP only from nginx's fixed address.
    assert [ipaddress.ip_network(entry.strip()) for entry in trusted.split(",")] == [ipaddress.ip_network(f"{nginx_ip}/32")]


def test_overlay_publishes_only_caddys_public_ports():
    overlay = _overlay()
    for name, service in overlay["services"].items():
        if name == "caddy":
            continue
        assert "ports" not in service, f"{name} must not publish a port in the public overlay"
    command = overlay["services"]["nginx"]["command"]
    # The include is verified before nginx starts, so a failed injection
    # fails closed instead of serving with one shared bucket.
    assert "include /etc/nginx/momentum-realip.conf;" in command
    # Compose turns a "\\n" in this string into a real newline, which broke
    # the sed on the Mac overlay's first deploy (nginx restart-looped).
    assert "\\n" not in command
    assert re.search(r"grep -q 'include /etc/nginx/momentum-realip\.conf;'", command)


@pytest.mark.asyncio
async def test_failed_logins_from_one_client_do_not_lock_out_another(monkeypatch):
    _, _, nginx_ip, trusted = _addresses()
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", trusted)
    monkeypatch.setattr(auth_router, "_login_throttle_policy", lambda: (3, 300.0))

    class _WrongPassword:
        async def authenticate(self, credentials):
            return None

    monkeypatch.setattr(auth_router, "get_local_provider", lambda: _WrongPassword())
    auth_router._login_attempts.clear()

    app = FastAPI()
    app.include_router(auth_router.router)
    # Every request reaches the Gateway from nginx, as in production.
    transport = httpx.ASGITransport(app=app, client=(str(nginx_ip), 40000))

    async def login(real_ip: str) -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway:8001") as client:
            response = await client.post("/api/v1/auth/login/local", data={"username": "someone@example.com", "password": "wrong"}, headers={"X-Real-IP": real_ip})
            return response.status_code

    try:
        attacker, colleague = "198.51.100.7", "203.0.113.20"
        for _ in range(3):
            assert await login(attacker) == 401
        assert await login(attacker) == 429
        # A different internet client is judged on its own record.
        assert await login(colleague) == 401
        assert colleague not in auth_router._login_attempts or auth_router._login_attempts[colleague][0] == 1

        # Control: without the overlay's trust setting, the same traffic
        # collapses onto nginx's address and the colleague is locked out too.
        auth_router._login_attempts.clear()
        monkeypatch.delenv("AUTH_TRUSTED_PROXIES")
        for _ in range(3):
            await login(attacker)
        assert await login(colleague) == 429
    finally:
        auth_router._login_attempts.clear()
