"""RFC 6238 TOTP (Time-Based One-Time Password), stdlib only.

HOTP (RFC 4226) truncation plus the RFC 6238 time-step wrapper. Verified
against the RFC 6238 Appendix B test vectors in ``tests/test_totp.py``.
No third-party TOTP dependency: this is small enough that hmac + hashlib
+ base64 cover it exactly, and it keeps the encrypted-at-rest secret's
raw bytes from ever crossing a library boundary we don't control.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
from urllib.parse import quote

_ALGORITHMS: dict[str, str] = {"sha1": "sha1", "sha256": "sha256", "sha512": "sha512"}
_DEFAULT_STEP_SECONDS = 30
_DEFAULT_DIGITS = 6
_DEFAULT_VALID_WINDOW = 1  # RFC 6238 recommends allowing +/- one step for clock drift
_SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommended minimum


def generate_totp_secret(length: int = _SECRET_BYTES) -> str:
    """A fresh random secret, base32-encoded (no padding) for otpauth:// / manual entry."""
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _decode_secret(secret_b32: str) -> bytes:
    # otpauth secrets are conventionally uppercase and unpadded; base32decode
    # requires padding back to a multiple of 8 chars.
    normalized = secret_b32.strip().upper()
    padding = "=" * (-len(normalized) % 8)
    return base64.b32decode(normalized + padding)


def hotp_code(secret: bytes, counter: int, *, digits: int = _DEFAULT_DIGITS, algorithm: str = "sha1") -> str:
    """RFC 4226 HOTP value for one counter step."""
    digestmod = _ALGORITHMS[algorithm]
    counter_bytes = struct.pack(">Q", counter)
    mac = hmac.new(secret, counter_bytes, digestmod).digest()
    offset = mac[-1] & 0x0F
    truncated = int.from_bytes(mac[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def totp_code(
    secret_b32: str,
    *,
    at: float | None = None,
    step: int = _DEFAULT_STEP_SECONDS,
    digits: int = _DEFAULT_DIGITS,
    algorithm: str = "sha1",
) -> str:
    """The current (or ``at``-time) TOTP code for a base32 secret."""
    counter = int((at if at is not None else time.time()) // step)
    return hotp_code(_decode_secret(secret_b32), counter, digits=digits, algorithm=algorithm)


def verify_totp_code(
    secret_b32: str,
    code: str,
    *,
    at: float | None = None,
    step: int = _DEFAULT_STEP_SECONDS,
    digits: int = _DEFAULT_DIGITS,
    algorithm: str = "sha1",
    valid_window: int = _DEFAULT_VALID_WINDOW,
) -> bool:
    """Constant-time check of ``code`` against the +/- ``valid_window`` steps around now."""
    if not code or not code.isdigit() or len(code) != digits:
        return False
    secret = _decode_secret(secret_b32)
    counter = int((at if at is not None else time.time()) // step)
    matched = False
    for offset in range(-valid_window, valid_window + 1):
        candidate = hotp_code(secret, counter + offset, digits=digits, algorithm=algorithm)
        # Compare every window step (no early return) so the response time
        # does not leak which offset (if any) matched.
        matched = matched or hmac.compare_digest(candidate, code)
    return matched


def build_otpauth_uri(secret_b32: str, account_name: str, *, issuer: str = "MomoBot") -> str:
    """``otpauth://totp/...`` URI for QR-code / authenticator-app enrollment.

    Per the otpauth URI convention, the label is ``issuer:account`` with a
    literal colon separator; only the two parts either side of it are
    percent-encoded.
    """
    label = f"{quote(issuer)}:{quote(account_name)}"
    query = f"secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits={_DEFAULT_DIGITS}&period={_DEFAULT_STEP_SECONDS}"
    return f"otpauth://totp/{label}?{query}"
