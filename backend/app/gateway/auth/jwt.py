"""JWT token creation and verification."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from pydantic import BaseModel, ValidationError

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import TokenError

ACCESS_TOKEN_TYPE = "access"
MFA_CHALLENGE_TYPE = "mfa_challenge"
MFA_CHALLENGE_TTL = timedelta(minutes=5)


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # user_id
    exp: datetime
    iat: datetime | None = None
    ver: int = 0  # token_version — must match User.token_version


def create_access_token(user_id: str, expires_delta: timedelta | None = None, token_version: int = 0) -> str:
    """Create a JWT access token.

    Args:
        user_id: The user's UUID as string
        expires_delta: Optional custom expiry, defaults to 7 days
        token_version: User's current token_version for invalidation

    Returns:
        Encoded JWT string
    """
    config = get_auth_config()
    expiry = expires_delta or timedelta(days=config.token_expiry_days)

    now = datetime.now(UTC)
    payload = {"sub": user_id, "exp": now + expiry, "iat": now, "ver": token_version, "typ": ACCESS_TOKEN_TYPE}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenPayload | TokenError:
    """Decode and validate a JWT token.

    Returns:
        TokenPayload if valid, or a specific TokenError variant.
    """
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        # Every token this module signs shares one secret, so the type claim
        # is what keeps them apart. An MFA challenge (issued after the
        # password, before the TOTP code) carries ``typ: mfa_challenge`` and
        # would otherwise decode as a session with ver=0, skipping MFA.
        # Access tokens minted before ``typ`` existed have no claim and stay
        # valid; anything that declares another type is refused.
        token_type = payload.get("typ")
        if token_type is not None and token_type != ACCESS_TOKEN_TYPE:
            return TokenError.MALFORMED
        return TokenPayload(**payload)
    except ValidationError:
        # Signed by us but not shaped like a session (e.g. an OIDC state
        # cookie): refuse it cleanly instead of raising into the request.
        return TokenError.MALFORMED
    except jwt.ExpiredSignatureError:
        return TokenError.EXPIRED
    except jwt.InvalidSignatureError:
        return TokenError.INVALID_SIGNATURE
    except jwt.PyJWTError:
        return TokenError.MALFORMED


class MfaChallengePayload(BaseModel):
    """Payload for the short-lived, single-use MFA login challenge.

    ``typ`` pins this to its one purpose so a normal access token (or any
    other future short-lived token this module grows) can never be replayed
    as an MFA challenge even though both are HS256 JWTs signed with the same
    secret.
    """

    sub: str  # user_id
    jti: str  # opaque id; the single-use / attempt-count record is server-side (routers/auth.py)
    typ: Literal["mfa_challenge"]
    exp: datetime
    iat: datetime | None = None


def create_mfa_challenge_token(user_id: str, jti: str, *, expires_delta: timedelta = MFA_CHALLENGE_TTL) -> str:
    """Sign a short-lived MFA challenge naming *user_id* and the caller-chosen *jti*.

    The caller (routers/auth.py) is responsible for the single-use /
    rate-limited server-side record keyed by ``jti`` -- this only proves the
    challenge was minted by this deployment and for this user, not that it
    is still unconsumed.
    """
    config = get_auth_config()
    now = datetime.now(UTC)
    payload = {"sub": user_id, "jti": jti, "typ": MFA_CHALLENGE_TYPE, "exp": now + expires_delta, "iat": now}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_mfa_challenge_token(token: str) -> MfaChallengePayload | TokenError:
    """Decode and validate an MFA challenge token.

    Returns:
        MfaChallengePayload if valid, or a specific TokenError variant. A
        token missing/mismatching the ``typ`` claim -- including a normal
        access token -- decodes to ``TokenError.MALFORMED``.
    """
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        return MfaChallengePayload(**payload)
    except jwt.ExpiredSignatureError:
        return TokenError.EXPIRED
    except jwt.InvalidSignatureError:
        return TokenError.INVALID_SIGNATURE
    except (jwt.PyJWTError, ValueError):
        # ValueError also catches pydantic's ValidationError (e.g. a missing
        # or wrong `typ`), which is a subclass of ValueError.
        return TokenError.MALFORMED
