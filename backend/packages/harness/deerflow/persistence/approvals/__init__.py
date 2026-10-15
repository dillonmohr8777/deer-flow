"""Approvals inbox persistence: ORM model and owner-scoped repository."""

from __future__ import annotations

from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.approvals.sql import PendingActionRepository

__all__ = ["PendingActionRepository", "PendingActionRow"]
