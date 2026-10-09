"""Configuration for the M4 entitlement gate.

Design: ``docs/momo-week/m4-entitlement.md`` (task ``c2``). Mirrors
:class:`~deerflow.config.authorization_config.AuthorizationConfig` in shape —
default ``enabled: false`` preserves today's behavior where every active
member of an organization can do everything, matching the "no billing yet"
rollout in the design's §4.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntitlementDefaultLimitsConfig(BaseModel):
    """Backfill ceilings for the single-owner org's ``*.max`` keys (design §4 step 2).

    Left ``None`` until Dillon sets a number (design §7.1, open question) — an
    unset value must not be baked into the migration as a guess.
    """

    projects_max: int | None = Field(default=None, description="Backfilled organization_entitlements.projects.max limit_value")
    workflows_max: int | None = Field(default=None, description="Backfilled organization_entitlements.workflows.max limit_value")
    brands_max: int | None = Field(default=None, description="Backfilled organization_entitlements.brands.max limit_value")
    repair_minutes_monthly: int | None = Field(default=None, description="Backfilled organization_entitlements.repair_minutes.monthly limit_value")


class EntitlementConfig(BaseModel):
    """Configuration for the server-side entitlement evaluator and gate."""

    enabled: bool = Field(default=False, description="Enable the entitlement gate. Off leaves every route's current behavior unchanged.")
    fail_closed: bool = Field(default=True, description="Deny (rather than allow) when the provider errors and no cached snapshot is usable")
    grace_period_seconds: int = Field(
        default=300,
        description="How long a process-level cached snapshot keeps serving decisions after the last successful provider read, before failing closed (design §3)",
    )
    default_limits: EntitlementDefaultLimitsConfig = Field(default_factory=EntitlementDefaultLimitsConfig, description="Backfill ceilings for the single-owner org's limit keys")


_entitlement_config: EntitlementConfig | None = None


def get_entitlement_config() -> EntitlementConfig:
    """Get the entitlement config, returning defaults if not loaded."""
    global _entitlement_config
    if _entitlement_config is None:
        _entitlement_config = EntitlementConfig()
    return _entitlement_config


def load_entitlement_config_from_dict(data: dict) -> EntitlementConfig:
    """Load entitlement config from a dict (called during AppConfig loading)."""
    global _entitlement_config
    _entitlement_config = EntitlementConfig.model_validate(data)
    return _entitlement_config


def reset_entitlement_config() -> None:
    """Reset the cached config instance. Used in tests to prevent singleton leaks."""
    global _entitlement_config
    _entitlement_config = None


def resolve_current_entitlement_config() -> EntitlementConfig:
    """Best-effort ``AppConfig().entitlements`` lookup for request-path callers.

    A route gated by the entitlement evaluator must not 500 just because no
    ``AppConfig`` has been loaded yet (e.g. a router-level unit test that
    builds a bare app and never touches config) -- that failure is
    indistinguishable from "entitlements were never turned on" here, so it
    degrades to the same default-disabled config rather than raising.
    """
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().entitlements
    except Exception:
        return EntitlementConfig()
