"""Shared-workspace invitation endpoints.

Invitation tokens are bearer credentials until they are consumed.  The raw
token is returned only when an owner/admin creates an invitation and is never
written to the database or logs.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.gateway.auth import create_access_token
from app.gateway.auth.password import hash_password_async, verify_password_async
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME, set_session_cookie
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.csrf_middleware import is_secure_request
from app.gateway.deps import get_current_user_from_request, record_audit_event
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/invitations", tags=["auth"])

_INVITATION_TTL = timedelta(hours=48)
_SHARED_MEMBER_ROLES = ("owner", "admin")


class CreateInvitationRequest(BaseModel):
    """``role`` is the membership the invitation grants. "member" is least
    privilege (no member management, no org settings -- see the
    _SHARED_MEMBER_ROLES / _EDIT_ROLES allowlists elsewhere) and is the
    default; "admin" stays available when the inviter explicitly chooses it.
    """

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(min_length=1, max_length=64)
    email: EmailStr
    role: Literal["member", "admin"] = "member"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class InvitationTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


class AcceptInvitationRequest(InvitationTokenRequest):
    password: str = Field(min_length=1, max_length=1024)


class CreateInvitationResponse(BaseModel):
    id: str
    token: str
    expires_at: datetime
    email: str
    workspace_name: str


class InspectInvitationResponse(BaseModel):
    email: str
    workspace_name: str
    expires_at: datetime
    requires_login: bool


class AcceptInvitationResponse(BaseModel):
    ok: bool = True
    workspace_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_factory():
    session_factory = get_session_factory()
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Workspace invitation persistence is unavailable")
    return session_factory


def _forbidden(detail: str = "Invitation is invalid or no longer available") -> HTTPException:
    # Keep invalid, expired, consumed, and revoked invitations indistinguishable
    # to callers holding a token.  The raw token is intentionally absent from
    # this detail and from all log records.
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def _active_shared_workspace_member(session, organization_id: str, user_id: str):
    organization = await session.scalar(
        select(OrganizationRow).where(
            OrganizationRow.id == organization_id,
            OrganizationRow.status == "active",
            OrganizationRow.storage_user_id.is_not(None),
        )
    )
    if organization is None:
        return None, None
    member = await session.scalar(
        select(OrganizationMemberRow).where(
            OrganizationMemberRow.organization_id == organization_id,
            OrganizationMemberRow.user_id == user_id,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_(_SHARED_MEMBER_ROLES),
        )
    )
    return organization, member


async def _invitation_issuer_is_active(session, invitation: InvitationRow) -> bool:
    _organization, member = await _active_shared_workspace_member(session, invitation.organization_id, invitation.created_by)
    return member is not None


async def _authenticated_session_user_id(request: Request) -> str | None:
    """Return a verified browser-session user id, never a PAT/internal actor."""
    source = getattr(request.state, "auth_source", None)
    state_user = getattr(request.state, "user", None)
    if source == AUTH_SOURCE_SESSION and state_user is not None:
        return str(state_user.id)
    if source in {AUTH_SOURCE_PAT, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_AUTH_DISABLED}:
        return None

    # Decorator-only/unit-test stacks may not install AuthMiddleware.  A
    # present access cookie is still verified through the normal JWT pipeline;
    # arbitrary request.state.user values are never trusted in that mode.
    if not request.cookies.get(ACCESS_TOKEN_COOKIE_NAME):
        return None
    try:
        user = await get_current_user_from_request(request)
    except HTTPException:
        return None
    return str(user.id)


def _validate_new_password(password: str) -> None:
    if len(password) < 12:
        raise HTTPException(status_code=422, detail="New workspace passwords must be at least 12 characters")
    from app.gateway.routers.auth import _password_is_common

    if _password_is_common(password):
        raise HTTPException(status_code=422, detail="Password is too common; choose a stronger password")


async def _find_user_by_email(session, email: str) -> UserRow | None:
    return await session.scalar(select(UserRow).where(func.lower(UserRow.email) == email.lower()).order_by(UserRow.created_at, UserRow.id).limit(1))


def _set_workspace_session(response: Response, request: Request, user_id: str, token_version: int, organization_id: str) -> None:
    token = create_access_token(user_id, token_version=token_version)
    policy = set_session_cookie(response, request, token)
    response.set_cookie(
        key="deerflow_workspace",
        value=organization_id,
        httponly=True,
        secure=policy.secure if policy is not None else is_secure_request(request),
        samesite="lax",
        max_age=policy.max_age if policy is not None else None,
    )


_INVITATIONS_FROZEN_DETAIL = "Workspace invitations are paused while workspace isolation is upgraded. Existing members keep their access."


def _refuse_if_frozen() -> None:
    """Decision 1: no new invitations and no acceptance of existing tokens."""
    from app.gateway.authz import _get_route_authorization_config

    if _get_route_authorization_config().invitations_frozen:
        raise HTTPException(status_code=403, detail=_INVITATIONS_FROZEN_DETAIL)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("", response_model=CreateInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(body: CreateInvitationRequest, request: Request, response: Response) -> CreateInvitationResponse:
    _no_store(response)
    _refuse_if_frozen()
    actor = await get_current_user_from_request(request)
    actor_id = str(actor.id)
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + _INVITATION_TTL
    invitation_id = str(uuid4())

    async with _session_factory()() as session:
        async with session.begin():
            organization, member = await _active_shared_workspace_member(session, body.organization_id, actor_id)
            if organization is None or member is None:
                raise HTTPException(status_code=403, detail="Only an active workspace owner or admin can invite members")
            session.add(
                InvitationRow(
                    id=invitation_id,
                    token_hash=_token_hash(token),
                    organization_id=organization.id,
                    email=str(body.email).lower(),
                    role=body.role,
                    created_by=actor_id,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )

    await record_audit_event(
        request, action="invitation.created", outcome="success", actor_user_id=actor_id, organization_id=organization.id, target_type="invitation", target_id=invitation_id, details={"email": str(body.email).lower(), "role": body.role}
    )
    return CreateInvitationResponse(
        id=invitation_id,
        token=token,
        expires_at=expires_at,
        email=str(body.email).lower(),
        workspace_name=organization.name,
    )


@router.post("/inspect", response_model=InspectInvitationResponse)
async def inspect_invitation(body: InvitationTokenRequest, response: Response) -> InspectInvitationResponse:
    _no_store(response)
    _refuse_if_frozen()
    now = _now()
    async with _session_factory()() as session:
        invitation = await session.scalar(select(InvitationRow).where(InvitationRow.token_hash == _token_hash(body.token)))
        if invitation is None or invitation.consumed_at is not None or _as_utc(invitation.expires_at) <= now:
            raise _forbidden()
        organization = await session.scalar(
            select(OrganizationRow).where(
                OrganizationRow.id == invitation.organization_id,
                OrganizationRow.status == "active",
                OrganizationRow.storage_user_id.is_not(None),
            )
        )
        if organization is None or not await _invitation_issuer_is_active(session, invitation):
            raise _forbidden()
        existing = await _find_user_by_email(session, invitation.email)

    return InspectInvitationResponse(
        email=invitation.email,
        workspace_name=organization.name,
        expires_at=_as_utc(invitation.expires_at),
        requires_login=existing is not None,
    )


@router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(body: AcceptInvitationRequest, request: Request, response: Response) -> AcceptInvitationResponse:
    _no_store(response)
    _refuse_if_frozen()
    from app.gateway.routers.auth import _check_rate_limit, _get_client_ip, _record_login_failure, _record_login_success

    client_ip = _get_client_ip(request)
    await _check_rate_limit(client_ip)
    now = _now()
    token_digest = _token_hash(body.token)
    session_factory = _session_factory()
    user_id: str | None = None
    token_version = 0
    organization_id: str | None = None
    invitation_id: str | None = None
    granted_role: str | None = None

    try:
        async with session_factory() as session:
            async with session.begin():
                invitation = await session.scalar(select(InvitationRow).where(InvitationRow.token_hash == token_digest))
                if invitation is None or invitation.consumed_at is not None or _as_utc(invitation.expires_at) <= now:
                    raise _forbidden()

                # Reserve the single-use token before password work.  The
                # conditional update is the cross-worker fence; a concurrent
                # accept sees rowcount=0 and cannot create a second member.
                reserved = await session.execute(
                    update(InvitationRow)
                    .execution_options(synchronize_session=False)
                    .where(
                        InvitationRow.id == invitation.id,
                        InvitationRow.token_hash == token_digest,
                        InvitationRow.consumed_at.is_(None),
                        InvitationRow.expires_at > now,
                    )
                    .values(consumed_at=now, updated_at=now)
                )
                if reserved.rowcount != 1:
                    raise _forbidden()

                organization = await session.scalar(
                    select(OrganizationRow).where(
                        OrganizationRow.id == invitation.organization_id,
                        OrganizationRow.status == "active",
                        OrganizationRow.storage_user_id.is_not(None),
                    )
                )
                # Recheck the inviter at consumption time.  A pending token
                # does not survive removal/demotion of its issuer.
                if organization is None or not await _invitation_issuer_is_active(session, invitation):
                    raise _forbidden()
                organization_id = organization.id
                invitation_id = invitation.id

                existing = await _find_user_by_email(session, invitation.email)
                if existing is not None:
                    user_id = existing.id
                    token_version = existing.token_version
                    if existing.oauth_provider is not None or existing.password_hash is None:
                        session_user_id = await _authenticated_session_user_id(request)
                        if session_user_id != existing.id:
                            raise HTTPException(
                                status_code=403,
                                detail="Sign in with the invited email's existing account before accepting this invitation",
                            )
                    elif not await verify_password_async(body.password, existing.password_hash):
                        await _record_login_failure(client_ip)
                        raise _forbidden("The current account password is incorrect")
                else:
                    _validate_new_password(body.password)
                    user_id = str(uuid4())
                    token_version = 0
                    password_hash = await hash_password_async(body.password)
                    private_id = private_organization_id(user_id)
                    session.add(
                        UserRow(
                            id=user_id,
                            email=invitation.email,
                            password_hash=password_hash,
                            system_role="user",
                            needs_setup=False,
                            token_version=0,
                            created_at=now,
                        )
                    )
                    session.add(
                        OrganizationRow(
                            id=private_id,
                            slug=private_organization_slug(user_id),
                            name="Private organization",
                            status="active",
                            storage_user_id=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    session.add(
                        OrganizationMemberRow(
                            organization_id=private_id,
                            user_id=user_id,
                            role="owner",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )

                workspace_member = await session.get(
                    OrganizationMemberRow,
                    {"organization_id": organization_id, "user_id": user_id},
                )
                if workspace_member is None:
                    granted_role = invitation.role or "member"
                    session.add(
                        OrganizationMemberRow(
                            organization_id=organization_id,
                            user_id=user_id,
                            role=granted_role,
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                elif workspace_member.role != "owner":
                    granted_role = invitation.role or "member"
                    workspace_member.role = granted_role
                    workspace_member.status = "active"
                    workspace_member.updated_at = now
                else:
                    granted_role = "owner"
    except IntegrityError:
        logger.info("Workspace invitation acceptance conflicted with an existing account or membership")
        raise HTTPException(status_code=409, detail="This invitation could not be accepted; retry from the invitation page") from None

    assert user_id is not None and organization_id is not None
    _record_login_success(client_ip)
    _set_workspace_session(response, request, user_id, token_version, organization_id)
    await record_audit_event(request, action="invitation.accepted", outcome="success", actor_user_id=user_id, organization_id=organization_id, target_type="invitation", target_id=invitation_id, details={"role": granted_role})
    return AcceptInvitationResponse(workspace_id=organization_id)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def revoke_invitation(invitation_id: str, request: Request) -> Response:
    actor = await get_current_user_from_request(request)
    actor_id = str(actor.id)
    now = _now()
    revoked_organization_id: str | None = None
    async with _session_factory()() as session:
        async with session.begin():
            invitation = await session.get(InvitationRow, invitation_id)
            if invitation is None or invitation.consumed_at is not None:
                raise HTTPException(status_code=404, detail="Pending invitation not found")
            organization, member = await _active_shared_workspace_member(session, invitation.organization_id, actor_id)
            if organization is None or member is None:
                raise HTTPException(status_code=403, detail="Only an active workspace owner or admin can revoke invitations")
            invitation.consumed_at = now
            invitation.updated_at = now
            revoked_organization_id = organization.id
    await record_audit_event(request, action="invitation.revoked", outcome="success", actor_user_id=actor_id, organization_id=revoked_organization_id, target_type="invitation", target_id=invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
