"""One-time MFA recovery codes: generation, hashing, constant-time matching.

Mirrors ``app/gateway/auth/pat.py``'s token pattern: a raw, high-entropy
value shown to the user exactly once, persisted only as a SHA-256 digest,
matched with ``hmac.compare_digest``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

RECOVERY_CODE_COUNT = 10
_RANDOM_BYTES = 5  # 40 bits per code; hashed + rate-limited, not a standalone secret


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """*count* fresh, human-typeable recovery codes (``xxxxx-xxxxx`` hex groups)."""
    codes = []
    while len(codes) < count:
        raw = secrets.token_hex(_RANDOM_BYTES)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def _normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace("-", "")


def hash_recovery_code(code: str) -> str:
    """SHA-256 hex digest of a normalized (case/dash-insensitive) recovery code."""
    return hashlib.sha256(_normalize_recovery_code(code).encode("utf-8")).hexdigest()


def recovery_code_matches(stored_hash: str, code: str) -> bool:
    """Constant-time comparison of a candidate code against a stored hash."""
    if not stored_hash or not code:
        return False
    return hmac.compare_digest(stored_hash, hash_recovery_code(code))
