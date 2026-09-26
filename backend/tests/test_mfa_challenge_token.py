from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.gateway.auth.config import AuthConfig
from app.gateway.auth.errors import TokenError
from app.gateway.auth.jwt import create_access_token, create_mfa_challenge_token, decode_mfa_challenge_token, decode_token


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


def test_an_mfa_challenge_is_not_a_valid_access_token():
    """The reverse of the test above. Without it a challenge (issued after the
    password but before the TOTP code) decodes as a session with ver=0, so
    replaying it as the access_token cookie skips MFA entirely."""
    token = create_mfa_challenge_token("user-1", "jti-1")
    assert decode_token(token) == TokenError.MALFORMED


def test_access_tokens_without_a_type_claim_stay_valid():
    """Sessions minted before access tokens carried ``typ`` must keep working."""
    import jwt as pyjwt

    from app.gateway.auth.config import get_auth_config

    now = datetime.now(UTC)
    legacy = pyjwt.encode({"sub": "user-1", "exp": now + timedelta(hours=1), "iat": now, "ver": 0}, get_auth_config().jwt_secret, algorithm="HS256")
    payload = decode_token(legacy)
    assert not isinstance(payload, TokenError)
    assert payload.sub == "user-1"


def test_new_access_tokens_declare_their_type():
    import jwt as pyjwt

    from app.gateway.auth.config import get_auth_config

    token = create_access_token("user-1", token_version=3)
    claims = pyjwt.decode(token, get_auth_config().jwt_secret, algorithms=["HS256"])
    assert claims["typ"] == "access"
    payload = decode_token(token)
    assert not isinstance(payload, TokenError) and payload.ver == 3


def test_other_tokens_we_sign_are_refused_not_raised():
    """An OIDC state cookie is signed with the same secret but has no ``sub``."""
    from app.gateway.auth.oidc_state import OIDCStatePayload, _sign_state_payload

    state = _sign_state_payload(OIDCStatePayload(provider="google", state="s"))
    assert decode_token(state) == TokenError.MALFORMED


def test_wrong_signature_is_rejected(monkeypatch):
    token = create_mfa_challenge_token("user-1", "jti-1")
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="a-totally-different-secret-value-here"))
    assert decode_mfa_challenge_token(token) == TokenError.INVALID_SIGNATURE


def test_garbage_token_is_malformed():
    assert decode_mfa_challenge_token("not-a-jwt") == TokenError.MALFORMED
