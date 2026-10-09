"""RFC 6238 TOTP test vectors (Appendix B) plus enrollment/verification edge cases."""

from __future__ import annotations

import pytest

from app.gateway.auth.totp import (
    build_otpauth_uri,
    generate_totp_secret,
    hotp_code,
    totp_code,
    verify_totp_code,
)

# RFC 6238 Appendix B secrets (ASCII, used as raw HMAC key bytes directly --
# the RFC vectors are defined over the raw secret, not a base32 encoding of it).
_SECRET_SHA1 = b"12345678901234567890"
_SECRET_SHA256 = b"12345678901234567890123456789012"
_SECRET_SHA512 = b"1234567890123456789012345678901234567890123456789012345678901234"

# (unix_time, algorithm, secret, expected 8-digit code)
_RFC_VECTORS = [
    (59, "sha1", _SECRET_SHA1, "94287082"),
    (59, "sha256", _SECRET_SHA256, "46119246"),
    (59, "sha512", _SECRET_SHA512, "90693936"),
    (1111111109, "sha1", _SECRET_SHA1, "07081804"),
    (1111111109, "sha256", _SECRET_SHA256, "68084774"),
    (1111111109, "sha512", _SECRET_SHA512, "25091201"),
    (1111111111, "sha1", _SECRET_SHA1, "14050471"),
    (1111111111, "sha256", _SECRET_SHA256, "67062674"),
    (1111111111, "sha512", _SECRET_SHA512, "99943326"),
    (1234567890, "sha1", _SECRET_SHA1, "89005924"),
    (1234567890, "sha256", _SECRET_SHA256, "91819424"),
    (1234567890, "sha512", _SECRET_SHA512, "93441116"),
    (2000000000, "sha1", _SECRET_SHA1, "69279037"),
    (2000000000, "sha256", _SECRET_SHA256, "90698825"),
    (2000000000, "sha512", _SECRET_SHA512, "38618901"),
    (20000000000, "sha1", _SECRET_SHA1, "65353130"),
    (20000000000, "sha256", _SECRET_SHA256, "77737706"),
    (20000000000, "sha512", _SECRET_SHA512, "47863826"),
]


@pytest.mark.parametrize(("unix_time", "algorithm", "secret", "expected"), _RFC_VECTORS)
def test_rfc6238_vectors(unix_time, algorithm, secret, expected):
    counter = unix_time // 30
    assert hotp_code(secret, counter, digits=8, algorithm=algorithm) == expected


def test_generate_totp_secret_is_base32_and_random():
    a = generate_totp_secret()
    b = generate_totp_secret()
    assert a != b
    # No padding, decodable, default 20-byte (160-bit) length.
    assert "=" not in a
    import base64

    padded = a + "=" * (-len(a) % 8)
    assert len(base64.b32decode(padded)) == 20


def test_totp_code_and_verify_round_trip():
    secret = generate_totp_secret()
    now = 1_700_000_000.0
    code = totp_code(secret, at=now)
    assert len(code) == 6 and code.isdigit()
    assert verify_totp_code(secret, code, at=now) is True


def test_verify_totp_code_allows_plus_minus_one_step():
    secret = generate_totp_secret()
    now = 1_700_000_000.0
    code = totp_code(secret, at=now)
    assert verify_totp_code(secret, code, at=now + 30) is True
    assert verify_totp_code(secret, code, at=now - 30) is True
    assert verify_totp_code(secret, code, at=now + 61) is False
    assert verify_totp_code(secret, code, at=now - 61) is False


def test_verify_totp_code_rejects_wrong_code():
    secret = generate_totp_secret()
    now = 1_700_000_000.0
    code = totp_code(secret, at=now)
    wrong = "0" * 6 if code != "0" * 6 else "1" * 6
    assert verify_totp_code(secret, wrong, at=now) is False


def test_verify_totp_code_rejects_malformed_input():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "") is False
    assert verify_totp_code(secret, "12345") is False  # too short
    assert verify_totp_code(secret, "abcdef") is False  # not digits
    assert verify_totp_code(secret, "1234567") is False  # too long


def test_build_otpauth_uri_contains_secret_and_issuer():
    secret = generate_totp_secret()
    uri = build_otpauth_uri(secret, "user@example.com", issuer="MomoBot")
    assert uri.startswith("otpauth://totp/MomoBot:user%40example.com?")
    assert f"secret={secret}" in uri
    assert "issuer=MomoBot" in uri
    assert "digits=6" in uri
    assert "period=30" in uri
