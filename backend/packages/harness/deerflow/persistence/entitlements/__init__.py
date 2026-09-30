"""M4 entitlement gate persistence — ORM model and repository."""

from __future__ import annotations

from deerflow.persistence.entitlements.model import OrganizationEntitlementRow
from deerflow.persistence.entitlements.sql import EntitlementRepository

__all__ = ["EntitlementRepository", "OrganizationEntitlementRow"]
