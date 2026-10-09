"""Secret redaction for audit event ``details`` payloads.

Audit ``details`` must never carry passwords, tokens, cookies, or keys
(SOC 2 control). Nothing in this codebase already does key-name-based
redaction of an arbitrary nested payload (the closest match,
``deerflow.runtime.secret_context``, is an allowlist of specific run-context
key names, not a general-purpose scrubber), so this is a small standalone
helper.
"""

from __future__ import annotations

from typing import Any

# Substring match, case-insensitive, against dict keys. Broad on purpose:
# a false-positive redaction just drops a harmless field from an audit
# record; a false negative leaks a secret into the append-only log.
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "token",
    "secret",
    "cookie",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "access_key",
    "client_secret",
)

REDACTED_PLACEHOLDER = "[redacted]"


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def redact_audit_details(value: Any) -> Any:
    """Return a deep copy of *value* with secret-shaped keys blanked.

    Recurses through dicts and lists; any other value is returned as-is. A
    dict key whose name contains a credential-like marker (password, token,
    secret, cookie, api_key, authorization, credential, private_key,
    access_key, client_secret) has its value replaced with
    :data:`REDACTED_PLACEHOLDER`, regardless of that value's own shape.
    """
    if isinstance(value, dict):
        return {key: (REDACTED_PLACEHOLDER if isinstance(key, str) and _looks_secret(key) else redact_audit_details(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [redact_audit_details(item) for item in value]
    return value
