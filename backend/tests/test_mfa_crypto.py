from __future__ import annotations

import pytest

from app.gateway.auth.config import AuthConfig
from app.gateway.auth.mfa_crypto import InvalidToken, decrypt_totp_secret, encrypt_totp_secret


@pytest.fixture(autouse=True)
def _fixed_jwt_secret(monkeypatch):
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="mfa-crypto-test-secret-at-least-32-bytes-long"))


def test_encrypt_decrypt_round_trip():
    secret = "JBSWY3DPEHPK3PXP"
    token = encrypt_totp_secret(secret)
    assert token != secret
    assert decrypt_totp_secret(token) == secret


def test_encrypt_is_nondeterministic_ciphertext():
    secret = "JBSWY3DPEHPK3PXP"
    assert encrypt_totp_secret(secret) != encrypt_totp_secret(secret)


def test_decrypt_fails_under_a_different_jwt_secret(monkeypatch):
    token = encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="a-completely-different-deployment-secret-value"))
    with pytest.raises(InvalidToken):
        decrypt_totp_secret(token)
