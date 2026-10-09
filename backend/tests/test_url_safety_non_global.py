"""Default web-tool admission excludes shared and site-local networks."""

import ipaddress

import pytest

from deerflow.community.url_safety import validate_public_http_url


@pytest.mark.parametrize("address", ["100.64.0.1", "100.100.100.200", "100.127.255.254", "fec0::1"])
def test_shared_and_site_local_addresses_are_blocked(address):
    host = f"[{address}]" if ":" in address else address
    url = f"https://{host}/"
    assert validate_public_http_url(url) is not None
    assert validate_public_http_url(url, allow_private_addresses=True) is None


def test_mixed_public_and_shared_dns_answer_is_blocked():
    assert validate_public_http_url("https://example.test/", resolver=lambda _: [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("100.64.0.1")]) is not None


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
def test_global_unicast_addresses_remain_allowed(address):
    assert validate_public_http_url("https://example.test/", resolver=lambda _: [ipaddress.ip_address(address)]) is None
