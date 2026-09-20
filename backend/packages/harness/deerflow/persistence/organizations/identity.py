"""Stable server-owned private organization identity."""

from __future__ import annotations

import hashlib


def _digest(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def private_organization_id(user_id: str) -> str:
    """Return the fixed private-organization identifier for one audit owner."""
    return f"private-{_digest(user_id)[:48]}"


def private_organization_slug(user_id: str) -> str:
    """Return a non-sensitive display slug; never expose the owner identifier."""
    return f"personal-{_digest(user_id)[:20]}"
