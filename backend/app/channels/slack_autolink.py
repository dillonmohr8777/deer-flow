"""Bind roster members to MomoBot on their first Slack message, with no /connect code.

Runs only when ``channel_connections.slack.auto_link_roster`` is on, for a sender
that has no active connection, is listed in ``roster.users`` and writes from the
configured Slack team. The account is found (or created as a plain non-admin
user) by email, put in the agency workspace as a member, and bound through the
same ``upsert_connection`` the /connect flow uses. Anything else returns False
and the caller keeps today's "connect first" reply.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from deerflow.config.roster_config import RosterConfig
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow

logger = logging.getLogger(__name__)

# Wait this long before asking users.info again after a miss (missing scope, no email, Slack error).
_SCOPE_RETRY_SECONDS = 600


class SlackRosterAutoLinker:
    def __init__(
        self,
        *,
        repo: Any,
        roster: RosterConfig,
        workspace_id: str,
        organization_slugs: list[str],
        session_factory: Any,
    ) -> None:
        self._repo = repo
        self._roster = roster
        self._workspace_id = workspace_id.strip()
        self._slugs = [s.strip().lower() for s in organization_slugs if isinstance(s, str) and s.strip()]
        self._sf = session_factory
        self._locks: dict[str, asyncio.Lock] = {}
        self._scope_retry_at = 0.0
        self._email_retry_at: dict[str, float] = {}

    def eligible(self, slack_user_id: str, team_id: str) -> bool:
        return bool(self._workspace_id and team_id == self._workspace_id and slack_user_id in self._roster.users)

    async def link(self, *, slack_user_id: str, team_id: str, web_client: Any) -> bool:
        """Return True when the sender now has an active connection."""
        if not self.eligible(slack_user_id, team_id):
            return False
        # One lock per sender: two quick messages link once, the second finds the row.
        lock = self._locks.setdefault(slack_user_id, asyncio.Lock())
        async with lock:
            try:
                if await self._repo.find_connection_by_external_identity(provider="slack", external_account_id=slack_user_id, workspace_id=team_id):
                    return True
                email = await self._email(slack_user_id, web_client)
                if not email:
                    return False
                user = await self._find_or_create_user(email)
                if user is None:
                    return False
                org_id = await self._ensure_membership(str(user.id))
                if org_id is None:
                    return False
                connection = await self._repo.upsert_connection(
                    owner_user_id=str(user.id),
                    provider="slack",
                    external_account_id=slack_user_id,
                    workspace_id=team_id,
                    metadata={"team_id": team_id, "auto_linked": "roster"},
                    status="connected",
                )
                await self._audit(user_id=str(user.id), org_id=org_id, connection_id=connection["id"], slack_user_id=slack_user_id, team_id=team_id)
            except Exception:
                # Any failure keeps today's "connect first" reply instead of dropping the message.
                logger.exception("[Slack] roster auto-link failed for %s", slack_user_id)
                return False
            return True

    async def _email(self, slack_user_id: str, web_client: Any) -> str | None:
        configured = self._roster.users[slack_user_id].email.strip().lower()
        if configured:
            return configured
        now = time.monotonic()
        if web_client is None or now < self._scope_retry_at or now < self._email_retry_at.get(slack_user_id, 0.0):
            return None
        # Any miss below waits _SCOPE_RETRY_SECONDS before this sender is looked up again.
        self._email_retry_at[slack_user_id] = now + _SCOPE_RETRY_SECONDS
        try:
            info = await asyncio.to_thread(web_client.users_info, user=slack_user_id)
        except Exception as exc:
            error = (getattr(exc, "response", None) or {}).get("error")
            if error == "missing_scope":
                self._scope_retry_at = time.monotonic() + _SCOPE_RETRY_SECONDS
                logger.warning("[Slack] roster auto-link needs the users:read.email scope (or an email on the roster entry); falling back to /connect")
            else:
                logger.warning("[Slack] users.info failed during roster auto-link: %s", error or type(exc).__name__)
            return None
        email = ((info.get("user") or {}).get("profile") or {}).get("email") if info else None
        return email.strip().lower() if isinstance(email, str) and email.strip() else None

    async def _find_or_create_user(self, email: str):
        from app.gateway.auth.models import User
        from app.gateway.auth.repositories.sqlite import SQLiteUserRepository

        users = SQLiteUserRepository(self._sf)
        user = await users.get_user_by_email(email)
        if user is None:
            try:
                # system_role is fixed: a roster role never makes a MomoBot admin.
                user = await users.create_user(User(email=email, password_hash=None, system_role="user"))
            except ValueError:
                user = await users.get_user_by_email(email)  # lost a race to another creator
        if user is None or user.disabled_at is not None:
            return None
        if user.system_role != "user":
            # Never hand an admin (or any elevated) account to a Slack sender; they link with /connect.
            logger.warning("[Slack] roster auto-link skipped: the matching account is not a plain user")
            return None
        return user

    async def _ensure_membership(self, user_id: str) -> str | None:
        async with self._sf() as session:
            org_id = None
            for slug in self._slugs:
                org_id = await session.scalar(select(OrganizationRow.id).where(OrganizationRow.slug == slug, OrganizationRow.status == "active"))
                if org_id:
                    break
            if org_id is None:
                logger.warning("[Slack] roster auto-link found no active organization for momentum_internal.organization_slugs")
                return None
            member = await session.get(OrganizationMemberRow, {"organization_id": org_id, "user_id": user_id})
            if member is None:
                now = datetime.now(UTC)
                session.add(OrganizationMemberRow(organization_id=org_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()  # a concurrent link added the same row
            elif member.status != "active":
                logger.warning("[Slack] roster auto-link skipped: workspace membership is %s", member.status)
                return None
            return org_id

    async def _audit(self, **ids: str) -> None:
        from deerflow.persistence.audit_events.sql import AuditEventRepository

        await AuditEventRepository(self._sf).record(
            action="channel_connection.auto_linked",
            outcome="success",
            actor_user_id=ids["user_id"],
            organization_id=ids["org_id"],
            target_type="channel_connection",
            target_id=ids["connection_id"],
            details={"provider": "slack", "slack_user_id": ids["slack_user_id"], "team_id": ids["team_id"], "source": "roster"},
        )
