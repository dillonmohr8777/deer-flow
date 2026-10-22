"""MomoBot Max at the Gateway: who may use it, and the settings every run of it gets.

The agent itself (config, SOUL) lives in ``deerflow.config.builtin_agents``.
This module owns the parts that need a caller:

* visibility: a caller sees it only when ``momobot_max.enabled`` is true and
  their role may ``use`` the agent's model, so teammates whose model list
  excludes it never get it;
* ``apply_run_policy``: client runs are pinned to the agent (any agent or model
  the request names is dropped), and every run of the agent gets the
  config-owned reasoning effort, thinking and delegation settings (including the total subagent cap), whatever
  the request says.

The tier: MomoBot Max is the base subscription plus the all-in-one agent. A
client whose client is listed in ``momobot_max.clients`` gets MomoBot Max (the
all-in-one model, effort and subagent team); every other client gets the base
MomoBot chat on the same agent and memory (``base_model``, ``base_effort``, no
subagents). Staff always get Max.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.gateway.authz import model_use_allowed
from app.gateway.client_boundary import CLIENT_ROLE
from deerflow.config.app_config import AppConfig
from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.runtime.user_context import resolve_organization_id

# Same wording as every other "no such agent" answer, so a run can't probe for it.
_UNRESOLVED_AGENT_DETAIL = "knowledge_scope assistant configuration could not be resolved"


def momobot_max_available_to(user: Any, config: AppConfig, *, is_internal: bool = False, tier: str = "max") -> bool:
    """Whether *user* may chat with the agent at *tier*: it is enabled and their role may use that tier's model."""
    settings = config.momobot_max
    model = settings.model if tier == "max" else settings.base_model
    return settings.enabled and model_use_allowed(user, model, is_internal=is_internal, fail_closed=config.authorization.fail_closed)


async def client_tier(actor_user_id: str | None, config: AppConfig) -> str:
    """``max`` when the client of the caller's workspace is unlocked for MomoBot Max, else ``base`` (no client counts as base)."""
    keys = await client_keys_for_user(actor_user_id, resolve_organization_id()) if actor_user_id else ()
    return "max" if config.momobot_max.unlocked_for(keys) else "base"


def client_side_model(user: Any, requested: str | None) -> str | None:
    """The model a client's side job (follow-up suggestions, manual compaction) runs on.

    Always the base model for a client, whatever the request names or the agent
    is configured with: side jobs never bill MomoBot Max's model. Staff keep their request.
    """
    if getattr(user, "system_role", None) != CLIENT_ROLE:
        return requested
    from deerflow.config.app_config import get_app_config

    return get_app_config().momobot_max.base_model


async def client_keys_for_user(user_id: str, organization_id: str | None = None) -> tuple[str, ...]:
    """Registry ids and ids of the active clients *user_id* is a client contact for, in a stable order.

    With *organization_id*, only the client that workspace is bound to (its
    ``customer_client_id``): a contact for two clients gets the tier of the
    client whose workspace they are chatting in, never the other one's.
    """
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return ()
    stmt = (
        select(ClientRow.registry_id, ClientRow.id)
        .join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id)
        .where(ClientAssignmentRow.user_id == user_id, ClientAssignmentRow.role == "client_contact", ClientRow.status == "active")
        .order_by(ClientRow.id)
    )
    if organization_id is not None:
        stmt = stmt.where(ClientRow.id == select(OrganizationRow.customer_client_id).where(OrganizationRow.id == organization_id).scalar_subquery())
    async with session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return tuple(key for row in rows for key in row if key)


async def apply_run_policy(config: dict[str, Any], *, user: Any, actor_user_id: str | None, app_config: AppConfig, internal: bool = False) -> None:
    """Mutate the run *config* in place; raise when the caller may not run MomoBot Max."""
    if not internal and user is not None:
        from app.gateway.client_workspace import require_client_workspace

        await require_client_workspace(user)
    if getattr(user, "system_role", None) == CLIENT_ROLE:
        if not app_config.momobot_max.enabled:
            raise HTTPException(status_code=503, detail="MomoBot Max is not available yet")
        config.setdefault("context", {})
        config.setdefault("configurable", {})
        for section in _sections(config):
            section["agent_name"] = MOMOBOT_MAX_NAME
            for key in ("model_name", "model", "is_bootstrap"):
                section.pop(key, None)
    sections = _sections(config)
    for section in sections:  # the tier is server-owned: set below for this agent only, never taken from a request
        section.pop("momobot_tier", None)
    agent_name = next((section["agent_name"] for section in sections if isinstance(section.get("agent_name"), str)), "")
    if agent_name.strip().lower().replace("_", "-") != MOMOBOT_MAX_NAME:
        return
    settings = app_config.momobot_max
    is_client = getattr(user, "system_role", None) == CLIENT_ROLE
    # A client's tier and effort come from the client their workspace is bound to; staff keep every assignment.
    client_keys = await client_keys_for_user(actor_user_id, resolve_organization_id() if is_client else None) if actor_user_id else ()
    tier = "base" if is_client and not settings.unlocked_for(client_keys) else "max"
    if not internal and (user is None or not momobot_max_available_to(user, app_config, tier=tier)):
        raise HTTPException(status_code=422, detail=_UNRESOLVED_AGENT_DETAIL)
    if tier == "base":
        for section in sections:
            section.update(model_name=settings.base_model, reasoning_effort=settings.base_effort, thinking_enabled=False, subagent_enabled=False, momobot_tier="base")
        return
    effort = settings.effort_for(client_keys)
    for section in sections:
        section.update(reasoning_effort=effort, thinking_enabled=True, subagent_enabled=True, max_total_subagents=app_config.subagents.max_total_per_run, momobot_tier="max")


def _sections(config: dict[str, Any]) -> list[dict[str, Any]]:
    # ``context`` first: it wins over ``configurable`` when both name an agent.
    return [section for section in (config.get("context"), config.get("configurable")) if isinstance(section, dict)]
