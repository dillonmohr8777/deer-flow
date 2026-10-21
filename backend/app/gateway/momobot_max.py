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

# Same wording as every other "no such agent" answer, so a run can't probe for it.
_UNRESOLVED_AGENT_DETAIL = "knowledge_scope assistant configuration could not be resolved"


def momobot_max_available_to(user: Any, config: AppConfig, *, is_internal: bool = False) -> bool:
    settings = config.momobot_max
    return settings.enabled and model_use_allowed(user, settings.model, is_internal=is_internal, fail_closed=config.authorization.fail_closed)


async def client_keys_for_user(user_id: str) -> tuple[str, ...]:
    """Registry ids and ids of the clients *user_id* is a client contact for, in a stable order."""
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return ()
    stmt = (
        select(ClientRow.registry_id, ClientRow.id).join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id).where(ClientAssignmentRow.user_id == user_id, ClientAssignmentRow.role == "client_contact").order_by(ClientRow.id)
    )
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
    agent_name = next((section["agent_name"] for section in sections if isinstance(section.get("agent_name"), str)), "")
    if agent_name.strip().lower().replace("_", "-") != MOMOBOT_MAX_NAME:
        return
    if not internal and (user is None or not momobot_max_available_to(user, app_config)):
        raise HTTPException(status_code=422, detail=_UNRESOLVED_AGENT_DETAIL)
    effort = app_config.momobot_max.effort_for(await client_keys_for_user(actor_user_id) if actor_user_id else ())
    for section in sections:
        section.update(reasoning_effort=effort, thinking_enabled=True, subagent_enabled=True, max_total_subagents=app_config.subagents.max_total_per_run)


def _sections(config: dict[str, Any]) -> list[dict[str, Any]]:
    # ``context`` first: it wins over ``configurable`` when both name an agent.
    return [section for section in (config.get("context"), config.get("configurable")) if isinstance(section, dict)]
