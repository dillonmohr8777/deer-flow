"""Approvals-gated Buffer publishing adapter for external social channels.

Nothing here runs before a reviewer wins the ``pending -> approved`` CAS in the
web Approvals inbox. Supports Google Business Profile, LinkedIn, Facebook,
Instagram, and X (Twitter) via Buffer's official GraphQL API.

Safety switches (evaluated on every execution):
1. ``BUFFER_ALLOWED_CHANNEL_IDS``: optional comma-separated allowlist. When set,
   unlisted channels fail closed in both live and dry-run modes.
2. ``BUFFER_DRY_RUN`` (env) or ``payload.dry_run=True``: validates and returns
   a dry-run receipt with ``status="approved"`` and ``state="dry_run"`` without
   sending any HTTP request. Env ``BUFFER_DRY_RUN=true`` cannot be disabled by
   a payload.
3. ``BUFFER_API_KEY``: required for live publishing. Unset or blank fails
   closed with zero network calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from deerflow.approvals import AdapterOutcome, InvalidPayloadError
from deerflow.integrations.buffer import (
    ACTION_TYPE,
    BUFFER_API_KEY_ENV,
    BufferAPIError,
    BufferAuthError,
    BufferGraphQLClient,
    BufferGraphQLError,
    BufferMutationError,
    BufferNetworkError,
    BufferNotConfiguredError,
    BufferOutcomeUnknownError,
    BufferRateLimitError,
    build_post_request,
    env_dry_run_enabled,
    parse_allowed_channel_ids,
    parse_workspace_channel_map,
    parse_workspace_org_map,
    sanitize_receipt_value,
    scrub_secret,
)

logger = logging.getLogger(__name__)


class BufferPublishAdapter:
    """Execute an approved ``buffer_post`` action through Buffer's GraphQL API."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], BufferGraphQLClient] | None = None,
        env_getter: Callable[[], Mapping[str, str]] | None = None,
        dry_run: bool | None = None,
        claim_execution: Callable[[str, str | None], Awaitable[dict[str, Any] | None]] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._env_getter = env_getter
        self._dry_run_override = dry_run
        self._claim_execution = claim_execution

    async def _claim_live_execution(self, action_id: str, user_id: str | None) -> dict[str, Any] | None:
        if self._claim_execution is not None:
            return await self._claim_execution(action_id, user_id)
        from deerflow.persistence.approvals import PendingActionRepository
        from deerflow.persistence.engine import get_session_factory

        factory = get_session_factory()
        if factory is None:
            raise RuntimeError("PendingActionRepository session factory is unavailable")
        repo = PendingActionRepository(factory)
        return await repo.claim_buffer_execution(action_id)

    def _env(self) -> Mapping[str, str]:
        return os.environ if self._env_getter is None else self._env_getter()

    def _client(self, env: Mapping[str, str]) -> BufferGraphQLClient:
        if self._client_factory is not None:
            return self._client_factory()
        return BufferGraphQLClient(env=env)

    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        action_id = str(action.get("id") or "")
        env = self._env()
        buffer_key = (env.get(BUFFER_API_KEY_ENV) or "").strip()

        try:
            request = build_post_request(str(action.get("target") or ""), action.get("payload"))
        except InvalidPayloadError as exc:
            err = str(sanitize_receipt_value(str(exc), secret=buffer_key))
            receipt = {
                "provider": "buffer",
                "state": "invalid_payload",
                "action_id": action_id,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning("Buffer approval %s rejected at execution validation: %s", action_id, err)
            return AdapterOutcome("failed", receipt, error=err)

        safe_channel_id = str(sanitize_receipt_value(request.channel_id, secret=buffer_key))
        workspace_id = str(action.get("organization_id") or action.get("workspace_id") or "").strip()
        safe_workspace_id = str(sanitize_receipt_value(workspace_id, secret=buffer_key))
        try:
            workspace_channels = parse_workspace_channel_map(env)
            workspace_orgs = parse_workspace_org_map(env)
        except InvalidPayloadError as exc:
            err = str(sanitize_receipt_value(str(exc), secret=buffer_key))
            receipt = {
                "provider": "buffer",
                "state": "invalid_workspace_binding",
                "action_id": action_id,
                "channel_id": safe_channel_id,
                "service": request.service,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning("Buffer approval %s blocked by invalid workspace binding config: %s", action_id, err)
            return AdapterOutcome("failed", receipt, error=err)

        allowed_channels = parse_allowed_channel_ids(env)
        if allowed_channels is not None and request.channel_id not in allowed_channels:
            err = f"Buffer channel {safe_channel_id!r} is not in BUFFER_ALLOWED_CHANNEL_IDS"
            receipt = {
                "provider": "buffer",
                "state": "channel_not_allowed",
                "action_id": action_id,
                "channel_id": safe_channel_id,
                "service": request.service,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning(
                "Buffer approval %s blocked by channel allowlist (channel=%s service=%s)",
                action_id,
                safe_channel_id,
                request.service,
            )
            return AdapterOutcome("failed", receipt, error=err)

        bound_buffer_org_id: str | None = None
        if workspace_channels is not None:
            ws_allowed = workspace_channels.get(workspace_id) if workspace_id else None
            if not ws_allowed or request.channel_id not in ws_allowed:
                err = f"Buffer channel {safe_channel_id!r} is not bound to workspace {safe_workspace_id or '<unset>'!r}"
                receipt = {
                    "provider": "buffer",
                    "state": "workspace_channel_not_allowed",
                    "action_id": action_id,
                    "channel_id": safe_channel_id,
                    "service": request.service,
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                }
                logger.warning(
                    "Buffer approval %s blocked by workspace channel binding (workspace=%s channel=%s)",
                    action_id,
                    safe_workspace_id or "<unset>",
                    safe_channel_id,
                )
                return AdapterOutcome("failed", receipt, error=err)

        if workspace_orgs is not None:
            bound_buffer_org_id = workspace_orgs.get(workspace_id) if workspace_id else None
            if not bound_buffer_org_id:
                err = f"Workspace {safe_workspace_id or '<unset>'!r} has no bound Buffer organization in BUFFER_WORKSPACE_ORGANIZATIONS"
                receipt = {
                    "provider": "buffer",
                    "state": "workspace_not_bound",
                    "action_id": action_id,
                    "channel_id": safe_channel_id,
                    "service": request.service,
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                }
                logger.warning("Buffer approval %s blocked: workspace=%s has no Buffer org binding", action_id, safe_workspace_id or "<unset>")
                return AdapterOutcome("failed", receipt, error=err)

        # Operator env dry-run switch always wins over payload dry_run=False.
        is_dry_run = bool(self._dry_run_override) or env_dry_run_enabled(env) or request.dry_run
        client = self._client(env)

        if is_dry_run:
            result = await client.create_post(request, dry_run=True, organization_id=bound_buffer_org_id)
            receipt = result.to_receipt(action_id=action_id, secret=buffer_key)
            logger.info(
                "Buffer dry-run receipt: action_id=%s channel_id=%s service=%s mode=%s save_to_draft=%s api_key_configured=%s",
                action_id,
                request.channel_id,
                request.service,
                request.mode,
                request.save_to_draft,
                result.api_key_configured,
            )
            # Status stays "approved" (never "executed") so dry-run is never mistaken for a live publish.
            return AdapterOutcome("approved", receipt)

        if not client.is_configured:
            err = "BUFFER_API_KEY is not configured; refusing to publish to Buffer"
            receipt = {
                "provider": "buffer",
                "state": "unconfigured",
                "action_id": action_id,
                "channel_id": request.channel_id,
                "service": request.service,
                "mode": request.mode,
                "save_to_draft": request.save_to_draft,
                "dry_run": False,
                "api_key_configured": False,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning(
                "Buffer approval %s failed closed (unconfigured): channel_id=%s service=%s",
                action_id,
                request.channel_id,
                request.service,
            )
            return AdapterOutcome("failed", receipt, error=err)

        if not workspace_id:
            err = "Live Buffer publishing requires an approval scoped to a workspace/organization_id"
            receipt = {
                "provider": "buffer",
                "state": "workspace_not_bound",
                "action_id": action_id,
                "channel_id": request.channel_id,
                "service": request.service,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning("Buffer approval %s blocked: live publish missing workspace_id", action_id)
            return AdapterOutcome("failed", receipt, error=err)

        if workspace_channels is None:
            err = (
                f"Workspace {workspace_id!r} has no explicit Buffer channel binding "
                "(configure BUFFER_WORKSPACE_CHANNELS before live publishing)"
            )
            receipt = {
                "provider": "buffer",
                "state": "workspace_not_bound",
                "action_id": action_id,
                "channel_id": request.channel_id,
                "service": request.service,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            logger.warning("Buffer approval %s blocked: live publish requires explicit BUFFER_WORKSPACE_CHANNELS binding", action_id)
            return AdapterOutcome("failed", receipt, error=err)

        base_receipt = {
            "provider": "buffer",
            "action_id": action_id,
            "channel_id": safe_channel_id,
            "service": request.service,
            "mode": request.mode,
            "scheduling_type": request.scheduling_type,
            "save_to_draft": request.save_to_draft,
            "dry_run": False,
            "api_key_configured": True,
            "timestamp_utc": datetime.now(UTC).isoformat(),
        }

        if action.get("status") != "approved":
            err = f"Buffer approval {action_id!r} is not in 'approved' status"
            logger.warning("Buffer approval %s rejected: status=%s", action_id, action.get("status"))
            return AdapterOutcome("failed", {**base_receipt, "state": "not_approved"}, error=err)

        if action.get("execution_result") is not None:
            err = "outcome_unknown: Buffer action already has an execution marker; reconcile Buffer before retrying"
            logger.warning("Buffer approval %s blocked: execution_result already set", action_id)
            return AdapterOutcome("approved", {**base_receipt, "state": "outcome_unknown"}, error=err)

        if not action_id:
            err = "Live Buffer publishing requires a non-empty approval action id for execution fencing"
            logger.warning("Buffer approval blocked: missing action_id for live execution fence")
            return AdapterOutcome("failed", {**base_receipt, "state": "execution_fence_unavailable"}, error=err)

        action_user_id = str(action.get("user_id") or "").strip() or None
        try:
            claimed = await self._claim_live_execution(action_id, action_user_id)
        except Exception as exc:
            err = f"Could not durably claim Buffer approval {action_id!r} before publishing ({type(exc).__name__})"
            logger.warning("Buffer approval %s blocked: execution fence unavailable (%s)", action_id, type(exc).__name__)
            return AdapterOutcome("failed", {**base_receipt, "state": "execution_fence_unavailable"}, error=err)

        if claimed is None:
            err = "outcome_unknown: Buffer approval was already claimed or is no longer eligible; reconcile Buffer before retrying"
            logger.warning("Buffer approval %s blocked: atomic execution claim returned None", action_id)
            return AdapterOutcome("approved", {**base_receipt, "state": "outcome_unknown"}, error=err)

        if (
            ("target" in claimed and claimed["target"] != action.get("target"))
            or ("payload" in claimed and claimed["payload"] != action.get("payload"))
            or ("organization_id" in claimed and str(claimed.get("organization_id") or "").strip() != workspace_id)
        ):
            err = "Claimed Buffer approval record does not match the requested target, payload, or workspace"
            logger.warning("Buffer approval %s blocked: claimed DB row mismatch", action_id)
            return AdapterOutcome("failed", {**base_receipt, "state": "approval_mismatch"}, error=err)

        try:
            result = await client.create_post(request, dry_run=False, organization_id=bound_buffer_org_id)
        except BufferNotConfiguredError:
            err = "BUFFER_API_KEY is not configured; refusing to publish to Buffer"
            logger.warning("Buffer approval %s failed closed (unconfigured)", action_id)
            return AdapterOutcome("failed", {**base_receipt, "state": "unconfigured", "api_key_configured": False}, error=err)
        except BufferOutcomeUnknownError as exc:
            detail = scrub_secret(str(exc), buffer_key)
            err = f"outcome_unknown: {detail}; check Buffer before retrying"
            receipt = {**base_receipt, "state": "outcome_unknown"}
            logger.warning(
                "Buffer approval %s outcome unknown: channel_id=%s service=%s detail=%s",
                action_id,
                request.channel_id,
                request.service,
                detail,
            )
            return AdapterOutcome("approved", receipt, error=err)
        except BufferRateLimitError as exc:
            err = scrub_secret(str(exc), buffer_key)
            receipt = {**base_receipt, "state": "rate_limited", "http_status": 429, "retry_after": exc.retry_after}
            logger.warning("Buffer approval %s rate-limited: channel_id=%s retry_after=%s", action_id, request.channel_id, exc.retry_after)
            return AdapterOutcome("failed", receipt, error=err)
        except BufferAuthError as exc:
            err = scrub_secret(str(exc), buffer_key)
            receipt = {**base_receipt, "state": "auth_failed"}
            logger.warning("Buffer approval %s auth failed: channel_id=%s", action_id, request.channel_id)
            return AdapterOutcome("failed", receipt, error=err)
        except BufferMutationError as exc:
            err = scrub_secret(f"{exc.error_type}: {exc}", buffer_key)
            receipt = {**base_receipt, "state": "mutation_rejected", "error_type": exc.error_type}
            logger.warning(
                "Buffer approval %s rejected by Buffer (%s): channel_id=%s service=%s",
                action_id,
                exc.error_type,
                request.channel_id,
                request.service,
            )
            return AdapterOutcome("failed", receipt, error=err)
        except BufferGraphQLError as exc:
            err = scrub_secret(f"Buffer GraphQL error: {exc}", buffer_key)
            receipt = {**base_receipt, "state": "graphql_error"}
            logger.warning("Buffer approval %s GraphQL error: channel_id=%s", action_id, request.channel_id)
            return AdapterOutcome("failed", receipt, error=err)
        except BufferAPIError as exc:
            err = scrub_secret(str(exc), buffer_key)
            receipt = {**base_receipt, "state": "api_error", "http_status": exc.status_code}
            logger.warning("Buffer approval %s HTTP error: channel_id=%s status=%s", action_id, request.channel_id, exc.status_code)
            return AdapterOutcome("failed", receipt, error=err)
        except BufferNetworkError as exc:
            err = scrub_secret(str(exc), buffer_key)
            receipt = {**base_receipt, "state": "network_error"}
            logger.warning("Buffer approval %s network error: channel_id=%s", action_id, request.channel_id)
            return AdapterOutcome("failed", receipt, error=err)

        receipt = result.to_receipt(action_id=action_id, secret=buffer_key)
        logger.info(
            "Buffer publish receipt: action_id=%s post_id=%s channel_id=%s service=%s mode=%s save_to_draft=%s post_status=%s http_status=%s elapsed_ms=%s",
            action_id,
            result.post_id,
            result.channel_id,
            result.service,
            result.mode,
            result.save_to_draft,
            result.post_status,
            result.http_status,
            result.elapsed_ms,
        )
        return AdapterOutcome("executed", receipt)


__all__ = ["ACTION_TYPE", "BufferPublishAdapter"]
