"""Encryption at rest for TOTP secrets.

Derives a dedicated Fernet key from the deployment's JWT secret (the same
secret ``app/gateway/auth/config.py`` already loads: ``AUTH_JWT_SECRET``,
falling back to a persisted ``.jwt_secret`` file) via HMAC-SHA256 domain
separation. Reusing that already-loaded, already-backed-up secret as HKDF
input material (RFC 5869) avoids provisioning, documenting, and backing up
a second deployment secret purely for MFA -- and mirrors the sha256-digest
Fernet key derivation ``ChannelCredentialCipher.from_key`` already uses in
``deerflow.persistence.channel_connections.sql``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.gateway.auth.config import get_auth_config

__all__ = ["InvalidToken", "decrypt_totp_secret", "encrypt_totp_secret"]

_HKDF_INFO = b"deerflow-mfa-totp-secret-encryption-v1"


def _fernet() -> Fernet:
    jwt_secret = get_auth_config().jwt_secret.encode("utf-8")
    derived_key = hmac.new(jwt_secret, _HKDF_INFO, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_totp_secret(secret_b32: str) -> str:
    """Encrypt a base32 TOTP secret for storage in ``user_mfa.secret_encrypted``."""
    return _fernet().encrypt(secret_b32.encode("utf-8")).decode("ascii")


def decrypt_totp_secret(token: str) -> str:
    """Inverse of :func:`encrypt_totp_secret`. Raises ``InvalidToken`` on tamper/wrong key."""
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
