"""OIDC / SSO authentication configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OIDCProviderConfig(BaseModel):
    """Configuration for a single OIDC identity provider (Keycloak, Google, Azure AD, etc.)."""

    display_name: str = Field(description="Human-readable name shown on the login button")
    issuer: str = Field(description="OIDC issuer URL (e.g. https://keycloak.example.com/realms/deerflow)")
    client_id: str = Field(description="OAuth2 client ID assigned by the provider")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret ($ENV_VAR references supported)")
    redirect_uri: str | None = Field(default=None, description="Callback URL the provider will redirect to after auth")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="OIDC scopes to request (must include openid)",
    )
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = Field(
        default="client_secret_post",
        description="How the client authenticates at the token endpoint",
    )

    # ── User provisioning ─────────────────────────────────────────────
    auto_create_users: bool = Field(
        default=True,
        description="Automatically create a DeerFlow user on first SSO login",
    )
    auto_create_requires_invitation: bool = Field(
        default=False,
        description=(
            "Only auto-create a user on first SSO login when the provider-verified email holds a pending "
            "workspace invitation: not consumed, not expired, in an active shared workspace, issued by a "
            "still-active owner or admin. Without one the login gets the same 403 as auto_create_users: false. "
            "Needs auto_create_users: true to have any effect; existing linked accounts keep signing in "
            "after their invitation is used."
        ),
    )
    link_existing_accounts: bool = Field(
        default=False,
        description=(
            "Let a first SSO login link to the one existing local account with the same email "
            "(case-insensitive) instead of refusing with 409. Only when the provider reports the email "
            "verified, auth.local.allow_registration is false (a self-registered account never proved it "
            "owns its email), exactly one account has that email, and it is active, has no SSO identity "
            "yet and no two-factor authentication, and was not created by accepting a workspace invitation "
            "issued by anyone other than a global admin (the inviter holds the token and sets the "
            "password, so the invited email was never proven). Every link and refusal is audited. The registration "
            "check sees only the current setting: enable this only if no account on the deployment was "
            "self-registered while registration was open (or after reviewing those accounts), and only "
            "for a provider that verifies email ownership, such as Google."
        ),
    )
    require_verified_email: bool = Field(
        default=True,
        description="Reject authentication if the provider does not report the email as verified",
    )
    allowed_email_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only allow users whose email domain is in this list (e.g. ['example.com'])",
    )
    admin_emails: list[str] = Field(
        default_factory=list,
        description="Users with these email addresses are automatically granted the admin role on first login",
    )

    # ── PKCE / nonce ──────────────────────────────────────────────────
    pkce_enabled: bool = Field(default=True, description="Enable PKCE (S256) for the authorization code flow")
    nonce_enabled: bool = Field(default=True, description="Include and validate the nonce claim in ID tokens")

    # ── Endpoint overrides (for providers with non-standard discovery) ─
    authorization_endpoint: str | None = Field(default=None)
    token_endpoint: str | None = Field(default=None)
    userinfo_endpoint: str | None = Field(default=None)
    jwks_uri: str | None = Field(default=None)


class OIDCAuthConfig(BaseModel):
    """Top-level OIDC authentication configuration."""

    enabled: bool = Field(default=False, description="Enable OIDC SSO authentication")
    frontend_base_url: str | None = Field(
        default=None,
        description="Base URL of the frontend (used for callback redirects when behind a reverse proxy)",
    )
    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider IDs to their configuration (e.g. keycloak, google, azure)",
    )


class LocalAuthConfig(BaseModel):
    """Configuration for the built-in email/password authentication provider."""

    allow_registration: bool = Field(
        default=True,
        description=(
            "Allow visitors to self-register a local account via POST /api/v1/auth/register. "
            "Set to false when accounts are provisioned exclusively through SSO — the OIDC "
            "provisioning policy (allowed_email_domains, require_verified_email, auto_create_users) "
            "does not apply to local registration."
        ),
    )
    max_login_attempts: int = Field(
        default=5,
        ge=2,
        description=(
            "Failed login attempts allowed from one client IP before it is locked out of "
            "POST /api/v1/auth/login/local. Defaults preserve the historical hardcoded policy. "
            "Raise it when many users share an egress IP (corporate proxy / NAT); lower it for "
            "a stricter posture. Minimum 2: one failed attempt must never lock an IP, or a "
            "single typo would block everyone behind a shared egress — the strictest legal "
            "value locks after the second failure. The counter is per-Gateway-worker "
            "(in-process), so effective attempts in multi-worker deployments scale with "
            "worker count."
        ),
    )
    lockout_seconds: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
        description=("Seconds an IP stays locked out after reaching auth.local.max_login_attempts. Defaults preserve the historical hardcoded policy (5 minutes)."),
    )


class AuthAppConfig(BaseModel):
    """Authentication configuration section for the DeerFlow app config."""

    oidc: OIDCAuthConfig = Field(default_factory=OIDCAuthConfig, description="OIDC SSO authentication settings")
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig, description="Built-in email/password authentication settings")
