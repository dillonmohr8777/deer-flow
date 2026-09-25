"""AI Academy persistence: per-person lesson completion."""

from __future__ import annotations

from deerflow.persistence.academy.model import AcademyProgressRow
from deerflow.persistence.academy.sql import AcademyProgressRepository

__all__ = ["AcademyProgressRepository", "AcademyProgressRow"]
