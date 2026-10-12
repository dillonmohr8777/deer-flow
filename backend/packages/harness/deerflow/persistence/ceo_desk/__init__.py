"""CEO Desk daily-digest persistence (queue item e14)."""

from __future__ import annotations

from deerflow.persistence.ceo_desk.model import CeoDeskDigestRow
from deerflow.persistence.ceo_desk.sql import CeoDeskDigestRepository

__all__ = [
    "CeoDeskDigestRepository",
    "CeoDeskDigestRow",
]
