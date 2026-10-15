import urllib.parse

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.gateway.routers.auth import _canonical_oidc_start_url


def request(host, scheme="http"):
    return Request({"type": "http", "method": "GET", "scheme": scheme, "server": ("gateway", 8001), "path": "/api/v1/auth/oauth/google", "query_string": b"", "headers": [(b"host", host.encode())]})


def test_local_start_moves_to_registered_callback_host_before_state_cookie():
    target = _canonical_oidc_start_url(request("127.0.0.1:2026"), "google", "https://momo.example/api/v1/auth/callback/google", "/workspace", False)
    parsed = urllib.parse.urlsplit(target)
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "momo.example", "/api/v1/auth/oauth/google")
    assert urllib.parse.parse_qs(parsed.query) == {"next": ["/workspace"], "remember_me": ["false"]}


def test_proxy_internal_http_does_not_create_redirect_loop():
    assert _canonical_oidc_start_url(request("momo.example"), "google", "https://momo.example/api/v1/auth/callback/google", "/workspace", True) is None


def test_explicit_default_tls_port_is_equivalent():
    assert _canonical_oidc_start_url(request("momo.example:443"), "google", "https://momo.example/api/v1/auth/callback/google", "/workspace", True) is None


def test_distinct_public_callback_port_is_preserved():
    target = _canonical_oidc_start_url(request("momo.example"), "google", "https://momo.example:8443/api/v1/auth/callback/google", "/workspace?x=1&y=2", True)
    assert urllib.parse.urlsplit(target).netloc == "momo.example:8443"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)["next"] == ["/workspace?x=1&y=2"]


def test_unconfigured_callback_keeps_existing_resolution():
    assert _canonical_oidc_start_url(request("localhost:2026"), "google", None, "/workspace", True) is None


@pytest.mark.parametrize("callback", ["file:///tmp/callback", "javascript:alert(1)", "https://user:password@momo.example/callback"])
def test_invalid_configured_callback_cannot_become_a_browser_link(callback):
    with pytest.raises(HTTPException):
        _canonical_oidc_start_url(request("localhost:2026"), "google", callback, "/workspace", True)
