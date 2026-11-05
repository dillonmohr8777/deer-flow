"""User provisioning for OIDC logins.

Handles the logic of finding existing users, auto-creating new ones, and
enforcing email domain restrictions. An email collision with a pre-existing
local account blocks the SSO login with a 409, unless the provider opts in
with ``link_existing_accounts`` and every condition in
``_link_refusal_reason`` holds; then the identity is linked onto that one
account. Every link and every refusal is audited by the OAuth callback.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.authz import role_has_policy
from deerflow.config.auth_config import OIDCProviderConfig
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.invitation_policy import pending_invitation_roles
from deerflow.persistence.user.model import UserRow

logger = logging.getLogger(__name__)

_AUTO_CREATE_DISABLED_DETAIL = "Automatic account creation is disabled. Contact your administrator."
_EXISTING_ACCOUNT_DETAIL = "An account with this email already exists. Contact your administrator to link it to your SSO account."


class ExistingAccountConflict(HTTPException):
    """The 409 for an SSO login whose email belongs to an account it may not link to.

    Every refusal carries the same public ``detail``, so a login attempt
    cannot probe an account's state; ``reason`` and ``user_id`` are for the
    audit log only.
    """

    def __init__(self, reason: str, user_id: str | None) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=_EXISTING_ACCOUNT_DETAIL)
        self.reason = reason
        self.user_id = user_id


async def _identity_pending_invitation_roles(identity: OIDCIdentity, email: str) -> set[str]:
    """Roles of the pending invitations the identity's provider-verified email holds.

    Fails closed: an unverified email, or no database to check, holds none.
    """
    if not identity.email_verified:
        return set()
    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("SSO auto-create cannot check pending invitations: no database is configured")
        return set()
    async with session_factory() as session:
        return await pending_invitation_roles(session, email, now=datetime.now(UTC))


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; every stored value is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _created_by_non_admin_invitation(local_user: User, email: str) -> bool:
    """Whether ``local_user`` was created by accepting an invitation a non-global-admin issued.

    Invitation acceptance creates a password account for the invited address
    whatever ``auth.local.allow_registration`` says, and the token goes to the
    inviter, so the person who set the password may not own the email. Accept
    stamps the new user's ``created_at`` with the same ``now`` as the
    invitation's ``consumed_at``, which is what ties the two together.

    Fails closed: with no database to check, or an issuer that cannot be
    found, the account counts as invitation-created.
    """
    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("SSO account linking cannot check invitation-created accounts: no database is configured")
        return True
    created_at = _as_utc(local_user.created_at)
    async with session_factory() as session:
        invitations = (
            await session.scalars(
                select(InvitationRow).where(
                    func.lower(InvitationRow.email) == email.strip().lower(),
                    InvitationRow.consumed_at.is_not(None),
                )
            )
        ).all()
        for invitation in invitations:
            if invitation.consumed_at is None or _as_utc(invitation.consumed_at) != created_at:
                continue
            issuer = await session.get(UserRow, invitation.created_by)
            if issuer is None or issuer.system_role != "admin":
                return True
    return False


async def _link_refusal_reason(
    provider_config: OIDCProviderConfig,
    identity: OIDCIdentity,
    email: str,
    local_user: User,
    local_provider: LocalAuthProvider,
    *,
    local_registration_open: Callable[[], bool] | None,
    mfa_enabled: Callable[[str], Awaitable[bool]] | None,
) -> str | None:
    """Why this SSO identity may not be linked onto ``local_user``, or None.

    Fails closed: each check that cannot be answered refuses.
    """
    if not provider_config.link_existing_accounts:
        return "linking_off"
    if not identity.email_verified:
        return "email_unverified"
    if not identity.email.isascii():
        # Python's lower() folds some non-ASCII letters (e.g. the Kelvin sign)
        # onto ASCII ones, so two different addresses could normalise alike.
        return "non_ascii_email"
    if local_registration_open is None or local_registration_open():
        # Anyone can self-register a password account for an email they do
        # not own; linking the real owner's SSO identity onto it would hand
        # the squatter a shared account.
        return "self_registration_open"
    if local_user.oauth_provider is not None or local_user.oauth_id is not None:
        return "already_linked"
    if local_user.disabled_at is not None:
        return "disabled"
    if await local_provider.count_users_by_email(email) != 1:
        # Counts disabled rows too: with two rows for one email, which one the
        # person owns is not ours to guess.
        return "multiple_accounts"
    if await _created_by_non_admin_invitation(local_user, email):
        # Accepting a workspace invitation creates a password account for the
        # invited email even with registration closed; the inviter holds the
        # token and can set the password, so the email was never proven.
        return "invitation_account"
    if mfa_enabled is None or await mfa_enabled(str(local_user.id)):
        # An SSO login skips the TOTP step, so linking would downgrade the
        # account's sign-in. An admin can still link it explicitly.
        return "mfa_enabled"
    return None


async def _link_existing_account(
    provider_id: str,
    provider_config: OIDCProviderConfig,
    identity: OIDCIdentity,
    email: str,
    local_user: User,
    local_provider: LocalAuthProvider,
    *,
    local_registration_open: Callable[[], bool] | None,
    mfa_enabled: Callable[[str], Awaitable[bool]] | None,
) -> User:
    """Link the SSO identity onto ``local_user`` or raise ExistingAccountConflict."""
    user_id = str(local_user.id)
    reason = await _link_refusal_reason(
        provider_config,
        identity,
        email,
        local_user,
        local_provider,
        local_registration_open=local_registration_open,
        mfa_enabled=mfa_enabled,
    )
    if reason is not None:
        raise ExistingAccountConflict(reason, user_id)
    try:
        linked = await local_provider.link_oauth_identity_if_unlinked(user_id, provider_id, identity.subject)
    except ValueError:
        # A concurrent callback linked this identity to some account first.
        raise ExistingAccountConflict("identity_linked_elsewhere", user_id) from None
    if linked is None:
        # The row gained an identity or was disabled after the checks above.
        raise ExistingAccountConflict("account_changed", user_id)
    logger.info("Linked OIDC identity to existing account %s (provider=%s)", user_id, provider_id)
    return linked


async def get_or_provision_oidc_user(
    provider_id: str,
    provider_config: OIDCProviderConfig,
    identity: OIDCIdentity,
    local_provider: LocalAuthProvider,
    *,
    local_registration_open: Callable[[], bool] | None = None,
    mfa_enabled: Callable[[str], Awaitable[bool]] | None = None,
) -> dict:
    """Resolve an OIDC identity to a DeerFlow user.

    Flow:
    1. Look up existing user by (provider, subject)
    2. If not found, enforce domain/email-verified rules
    3. If a local account already owns the email, link to it only when
       ``_link_refusal_reason`` finds nothing; otherwise 409
    4. Auto-create if enabled (and, with ``auto_create_requires_invitation``,
       only for a verified email holding a pending workspace invitation)

    ``local_registration_open`` and ``mfa_enabled`` are the link checks' lazy
    lookups (read only when an account matches); leaving either out refuses
    every link, so a caller that does not pass them keeps the never-link
    behaviour.

    Returns a dict with ``user`` (the User model instance) and ``created``
    (bool), plus ``linked: True`` when step 3 linked an existing account.
    """
    # 1. Existing OAuth link
    existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
    if existing:
        return {"user": existing, "created": False}

    # 2. Verified email requirement
    if provider_config.require_verified_email and not identity.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Your email could not be verified by the identity provider. Please contact your administrator."),
        )

    if not identity.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The identity provider did not provide an email address.",
        )

    email = identity.email.lower()

    # 3. Domain restriction
    if provider_config.allowed_email_domains:
        domain = email.rsplit("@", 1)[-1]
        if domain not in {d.lower().lstrip("@") for d in provider_config.allowed_email_domains}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your email domain is not allowed. Please use an approved email address.",
            )

    # 4. A local account already owns this email. Linking an SSO identity onto
    # it could let an SSO login take over a password account that merely shares
    # the email, so it happens only when every link check passes; anything else
    # is the same 409 as before.
    local_user = await local_provider.get_user_by_email(email)

    if local_user:
        linked = await _link_existing_account(
            provider_id,
            provider_config,
            identity,
            email,
            local_user,
            local_provider,
            local_registration_open=local_registration_open,
            mfa_enabled=mfa_enabled,
        )
        return {"user": linked, "created": False, "linked": True}

    # 5. Auto-create
    if not provider_config.auto_create_users:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_AUTO_CREATE_DISABLED_DETAIL)

    # Invite-gated deployments create accounts only for people someone asked
    # in. The refusal is the same 403 as auto-create being off, so a login
    # attempt cannot probe which emails hold an invitation.
    pending_roles = await _identity_pending_invitation_roles(identity, email)
    if "client" in pending_roles and not role_has_policy("client"):
        # /accept refuses a client invitation while RBAC has no client block; so does sign-up.
        pending_roles = pending_roles - {"client"}
    if provider_config.auto_create_requires_invitation and not pending_roles:
        logger.info("Refused SSO auto-create for %s (provider=%s): no pending workspace invitation", email, provider_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_AUTO_CREATE_DISABLED_DETAIL)

    role = _resolve_role(email, provider_config.admin_emails)
    # Someone invited only as a client gets the client tier from day one, the
    # same as a password sign-up through that invitation; accepting it later
    # keeps an existing account's role, so this is the only point to set it.
    if role == "user" and pending_roles == {"client"}:
        role = "client"
    try:
        user = await local_provider.create_oauth_user(
            email=email,
            oauth_provider=provider_id,
            oauth_id=identity.subject,
            system_role=role,
        )
    except ValueError:
        # Lost a race: a concurrent callback (double-click, replayed code) already
        # inserted a row that collides on the unique index. Re-resolve instead of
        # bubbling a raw 500. If the winner created this same identity, return it;
        # otherwise the email now belongs to a different account → 409.
        existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
        if existing:
            return {"user": existing, "created": False}
        raise ExistingAccountConflict("email_taken_during_create", None) from None
    logger.info("Auto-created OIDC user %s (provider=%s, role=%s)", email, provider_id, role)
    return {"user": user, "created": True}


def _resolve_role(email: str, admin_emails: list[str]) -> str:
    """Return ``admin`` if the email is in the admin list, otherwise ``user``."""
    email_lower = email.lower()
    return "admin" if any(e.lower() == email_lower for e in admin_emails) else "user"
