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
import json
import os
import pathlib
import re
import subprocess

import httpx
import pytest
import yaml
from fastapi import FastAPI

from app.gateway.routers import auth as auth_router

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
VPS_DIR = REPO_ROOT / "deploy" / "momentum" / "vps"
MOMENTUM_DIR = REPO_ROOT / "deploy" / "momentum"


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

    # postgres/redis/frontend/gateway attach to this network with no static
    # address, so Docker auto-assigns them one from ip_range. If that range
    # weren't carved out away from the static addresses, one of them could
    # start before Caddy or nginx and take the address a static container
    # needs, and the trust chain above would key on the wrong container.
    ipam = _overlay()["networks"]["deer-flow"]["ipam"]["config"][0]
    ip_range = ipaddress.ip_network(ipam["ip_range"])
    assert caddy_ip not in ip_range
    assert nginx_ip not in ip_range

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


def _docker_compose_available() -> bool:
    try:
        result = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ensure_file(path: pathlib.Path) -> bool:
    """Create an empty file if it's missing; return whether this call created it.

    ``docker compose config`` refuses to render when a service's ``env_file:``
    doesn't exist on disk (``docker-compose.yaml``'s frontend/gateway entries
    point at the real, gitignored ``.env``/``frontend/.env``). Content doesn't
    matter for rendering ``ports``, only existence -- so touch it into being
    only if absent, and let the caller remove it again afterwards.
    """
    if path.exists():
        return False
    path.write_text("", encoding="utf-8")
    return True


def _merged_vps_stack(*, project: str, momentum_tailnet_host: str | None) -> dict:
    """Render the exact stack ``deploy/momentum/vps/restart.sh`` runs.

    ``test_overlay_publishes_only_caddys_public_ports`` above only reads
    ``compose.public.yaml`` in isolation, so it can't see a port republished
    by an earlier file in restart.sh's own ``-f`` chain -- e.g.
    ``deploy/momentum/compose.momentum.yaml``'s own ``nginx.ports`` entry
    (f93c). That matters because Compose merges a service's ``ports`` list
    across ``-f`` files by *concatenation*, not override: confirmed by the
    regression test below, which renders with ``MOMENTUM_TAILNET_HOST=0.0.0.0``
    and observes the merged list keep the base file's loopback entry *and*
    gain a second, world-bound one alongside it, rather than the second
    replacing the first. A regressed default anywhere in that chain widens
    the published surface instead of merely being shadowed by a later file,
    so only a merge of the real chain (restart.sh's exact file list and
    order) can catch it -- reading any one file alone cannot.
    """
    created = [p for p in (REPO_ROOT / ".env", REPO_ROOT / "frontend" / ".env") if _ensure_file(p)]
    try:
        env = dict(os.environ)
        env.pop("MOMENTUM_TAILNET_HOST", None)
        env.update(
            {
                "COMPOSE_PROJECT_NAME": project,
                "PORT": "2026",
                "DEER_FLOW_CONFIG_PATH": str(MOMENTUM_DIR / "workspace.config.postgres.yaml"),
                "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(REPO_ROOT / "extensions_config.example.json"),
                "DEER_FLOW_HOME": str(REPO_ROOT / "backend" / ".deer-flow"),
                "MOMOBOT_CADDYFILE": str(VPS_DIR / "Caddyfile"),
                "MOMOBOT_REALIP_CONF": str(VPS_DIR / "nginx-realip.conf"),
                "MOMOBOT_DOMAIN": "momo.example.com",
                "MOMOBOT_ACME_EMAIL": "ops@example.com",
                "POSTGRES_PASSWORD": "test-password",
                "BETTER_AUTH_SECRET": "test-secret",
                "DEER_FLOW_INTERNAL_AUTH_TOKEN": "test-token",
            }
        )
        if momentum_tailnet_host is not None:
            env["MOMENTUM_TAILNET_HOST"] = momentum_tailnet_host
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(REPO_ROOT / ".env"),
                "-p",
                project,
                "-f",
                str(REPO_ROOT / "docker" / "docker-compose.yaml"),
                "-f",
                str(REPO_ROOT / "docker" / "docker-compose.dood.yaml"),
                "-f",
                str(MOMENTUM_DIR / "compose.momentum.yaml"),
                "-f",
                str(MOMENTUM_DIR / "compose.postgres.yaml"),
                "-f",
                str(VPS_DIR / "compose.public.yaml"),
                "config",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, f"docker compose config failed: {result.stderr}"
        return json.loads(result.stdout)
    finally:
        for path in created:
            path.unlink(missing_ok=True)


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker Compose not available")
def test_merged_stack_publishes_only_caddys_public_ports():
    """f93(c): the real restart.sh chain, not compose.public.yaml alone.

    ``MOMENTUM_TAILNET_HOST`` is deliberately left unset here, so this
    exercises ``compose.momentum.yaml:14``'s own ``${MOMENTUM_TAILNET_HOST:-127.0.0.1}``
    fallback directly -- restart.sh also happens to pin the variable itself
    (belt-and-suspenders, checked separately below), but that pin must never
    be the only thing standing between the file's own default and the public
    internet.
    """
    merged = _merged_vps_stack(project="f93-merge-check", momentum_tailnet_host=None)
    for name, service in merged["services"].items():
        for mapping in service.get("ports") or []:
            host_ip = mapping.get("host_ip") or "0.0.0.0"
            is_wide_open = host_ip in ("0.0.0.0", "::", "")
            assert is_wide_open == (name == "caddy"), f"{name} published {mapping} on the merged VPS stack (host_ip={host_ip!r})"


def test_restart_sh_also_pins_the_tailnet_host_to_loopback():
    """Belt-and-suspenders alongside the file default checked above.

    restart.sh unconditionally exports ``MOMENTUM_TAILNET_HOST=127.0.0.1``
    before invoking Compose; losing that line would still be safe today
    (the file's own default covers it), but must not silently start
    forwarding a caller's own wider value instead.
    """
    script = (VPS_DIR / "restart.sh").read_text(encoding="utf-8")
    assert re.search(r"^export MOMENTUM_TAILNET_HOST=127\.0\.0\.1\s*$", script, re.MULTILINE), "restart.sh must keep pinning MOMENTUM_TAILNET_HOST to loopback"


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker Compose not available")
def test_merged_stack_regresses_if_a_chained_files_ports_default_widens():
    """Same merge, but proves it actually catches a regression (not just passes).

    Compose concatenates ``ports`` lists across ``-f`` files rather than
    letting a later file override an earlier one, so a bad default anywhere
    in the chain *adds* exposure instead of merely being shadowed.
    """
    merged = _merged_vps_stack(project="f93-merge-check-regression", momentum_tailnet_host="0.0.0.0")
    nginx_hosts = {mapping.get("host_ip") for mapping in merged["services"]["nginx"].get("ports") or []}
    # Both entries, not just the wide-open one: an override merge would leave
    # only {"0.0.0.0"} here too, so asserting membership alone doesn't
    # distinguish concatenation from override -- the base file's loopback
    # entry surviving *alongside* it is the actual proof.
    assert nginx_hosts == {"127.0.0.1", "0.0.0.0"}, f"expected the merge to keep the base file's loopback entry and add a second, wide-open one, proving concatenation not override; got {nginx_hosts!r}"


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
