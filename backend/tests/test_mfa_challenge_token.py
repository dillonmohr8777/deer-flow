from __future__ import annotations

from datetime import timedelta

import pytest

from app.gateway.auth.config import AuthConfig
from app.gateway.auth.errors import TokenError
from app.gateway.auth.jwt import create_access_token, create_mfa_challenge_token, decode_mfa_challenge_token


@pytest.fixture(autouse=True)
def _fixed_jwt_secret(monkeypatch):
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="mfa-challenge-test-secret-at-least-32-bytes"))


def test_create_and_decode_round_trip():
    token = create_mfa_challenge_token("user-1", "jti-1")
    payload = decode_mfa_challenge_token(token)
    assert not isinstance(payload, TokenError)
    assert payload.sub == "user-1"
    assert payload.jti == "jti-1"
    assert payload.typ == "mfa_challenge"


def test_expired_challenge_is_rejected():
    token = create_mfa_challenge_token("user-1", "jti-1", expires_delta=timedelta(seconds=-1))
    assert decode_mfa_challenge_token(token) == TokenError.EXPIRED


def test_a_normal_access_token_is_not_a_valid_mfa_challenge():
    """An access token and a challenge token are both HS256 JWTs signed with the
    same secret -- `typ` is what stops one from being replayed as the other."""
    token = create_access_token("user-1", token_version=0)
    assert decode_mfa_challenge_token(token) == TokenError.MALFORMED


def test_wrong_signature_is_rejected(monkeypatch):
    token = create_mfa_challenge_token("user-1", "jti-1")
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="a-totally-different-secret-value-here"))
    assert decode_mfa_challenge_token(token) == TokenError.INVALID_SIGNATURE


def test_garbage_token_is_malformed():
    assert decode_mfa_challenge_token("not-a-jwt") == TokenError.MALFORMED
