"""MomoBot Max at the Gateway: who may use it, and the settings every run of it gets.

The agent itself (config, SOUL) lives in ``deerflow.config.builtin_agents``.
This module owns the parts that need a caller:

* visibility: a caller sees it only when ``momobot_max.enabled`` is true and
  their role may ``use`` the agent's model, so teammates whose model list
  excludes it never get it;
* ``apply_run_policy``: client runs are pinned to the agent (any agent or model
  the request names is dropped), and every run of the agent gets the
  config-owned reasoning effort, thinking and delegation settings (including the total subagent cap), whatever
  the request says;
* ``client_workspace_agents``: a Max client chatting inside their dedicated
  customer workspace may also see and run the custom agents stored in that
  workspace's own bucket (a tailored all-in-one agent). Those runs get the same
  config-owned Max settings on the agent's own model; everything else about the
  client boundary is unchanged (read-only, no SOUL, no management routes).

The tier: MomoBot Max is the base subscription plus the all-in-one agent. A
client whose client is listed in ``momobot_max.clients`` gets MomoBot Max (the
all-in-one model, effort and subagent team); every other client gets the base
MomoBot chat on the same agent and memory (``base_model``, ``base_effort``, no
subagents). Staff always get Max.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.gateway.authz import model_use_allowed
from app.gateway.client_boundary import CLIENT_ROLE
from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.builtin_agents import CLIENT_WORKSPACE_CEILING_KEY, MOMOBOT_MAX_NAME, is_builtin_agent_name
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.runtime.user_context import get_effective_user_id, resolve_organization_id

logger = logging.getLogger(__name__)

# Same wording as every other "no such agent" answer, so a run can't probe for it.
_UNRESOLVED_AGENT_DETAIL = "knowledge_scope assistant configuration could not be resolved"


_STAFF_ROLES = ("user", "exec")


def staff_runs_cheap(user: Any, settings: Any, *, fail_closed: bool = True) -> bool:
    """Employees (user, exec) run MomoBot Max on ``staff_model`` when one is set and their role may use it
    (Dillon, Oct 22: the team on Haiku 5.5). Admins, clients and internal channel/scheduler runs keep ``model``."""
    if not settings.staff_model or user is None or getattr(user, "system_role", None) not in _STAFF_ROLES:
        return False
    return model_use_allowed(user, settings.staff_model, is_internal=False, fail_closed=fail_closed)


def momobot_max_available_to(user: Any, config: AppConfig, *, is_internal: bool = False, tier: str = "max") -> bool:
    """Whether *user* may chat with the agent at *tier*: it is enabled and their role may use that tier's model."""
    settings = config.momobot_max
    if not settings.enabled:
        return False
    if tier != "max":
        model = settings.base_model
    elif staff_runs_cheap(user, settings, fail_closed=config.authorization.fail_closed):
        model = settings.staff_model
    else:
        model = settings.model
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


async def client_workspace_agents(user: Any, actor_user_id: str | None, app_config: AppConfig) -> dict[str, AgentConfig]:
    """The custom agents a client may see and run, keyed by normalized name: those stored in their dedicated customer workspace's own bucket.

    Empty unless the caller is a ``client`` on the Max tier whose active
    workspace passes ``require_client_workspace``. Never a legacy shared-layout
    agent, another bucket's agent, an agent stamped for another client or a
    built-in. A run of one is capped by ``client_workspace_ceiling``; a bucket
    that can't be read leaves the client with the built-in only.
    """
    if getattr(user, "system_role", None) != CLIENT_ROLE or not app_config.momobot_max.enabled:
        return {}
    from app.gateway.client_workspace import require_client_workspace

    try:
        await require_client_workspace(user)
    except HTTPException:  # not a dedicated customer workspace: the built-in only, as before
        return {}
    keys = await client_keys_for_user(actor_user_id, resolve_organization_id()) if actor_user_id else ()
    if not app_config.momobot_max.unlocked_for(keys):
        return {}
    try:
        agents = await asyncio.to_thread(_bucket_agents, get_effective_user_id())
    except Exception:  # noqa: BLE001 - one unreadable row must not break the client's MomoBot Max chat
        logger.warning("Client workspace agents unavailable; serving the built-in only", exc_info=True)
        return {}
    return {_agent_key(agent.name): agent for agent in agents if not is_builtin_agent_name(_agent_key(agent.name)) and (agent.client_id is None or agent.client_id in {str(key) for key in keys})}


def _bucket_agents(user_id: str) -> list[AgentConfig]:
    """Agents stored in *user_id*'s own bucket, each resolvable by its config name there (never the legacy layout)."""
    from deerflow.config.paths import get_paths
    from deerflow.persistence.agents import get_agent_store
    from deerflow.persistence.agents.file import FileAgentStore

    store = get_agent_store()
    agents = store.list(user_id=user_id, include_legacy=False)
    if isinstance(store, FileAgentStore):
        # A folder whose config.yaml names another agent would load that name from the legacy layout.
        agents = [agent for agent in agents if (get_paths().user_agent_dir(user_id, _agent_key(agent.name)) / "config.yaml").exists()]
    return agents


def _agent_key(name: str) -> str:
    return name.strip().lower().replace("_", "-")


async def apply_run_policy(config: dict[str, Any], *, user: Any, actor_user_id: str | None, app_config: AppConfig, internal: bool = False) -> None:
    """Mutate the run *config* in place; raise when the caller may not run MomoBot Max."""
    if not internal and user is not None:
        from app.gateway.client_workspace import require_client_workspace

        await require_client_workspace(user)
    workspace_agents: dict[str, AgentConfig] = {}
    if getattr(user, "system_role", None) == CLIENT_ROLE:
        if not app_config.momobot_max.enabled:
            raise HTTPException(status_code=503, detail="MomoBot Max is not available yet")
        config.setdefault("context", {})
        config.setdefault("configurable", {})
        # A client runs MomoBot Max, or one of their own workspace's agents; any other name is dropped.
        requested = _normalized_agent_name(config)
        defaults = app_config.momobot_max.client_default_agents
        if defaults and not any(section.get("agent_name") is not None for section in _sections(config)):
            keys = await client_keys_for_user(actor_user_id, resolve_organization_id()) if actor_user_id else ()
            requested = _agent_key(next((defaults[key] for key in keys if key in defaults), ""))
        if requested not in ("", MOMOBOT_MAX_NAME):
            workspace_agents = await client_workspace_agents(user, actor_user_id, app_config)
        pinned = requested if requested in workspace_agents else MOMOBOT_MAX_NAME
        for section in _sections(config):
            section["agent_name"] = pinned
            for key in ("model_name", "model", "is_bootstrap"):
                section.pop(key, None)
    sections = _sections(config)
    for section in sections:  # tier and ceiling are server-owned: set below for this agent only, never taken from a request
        section.pop("momobot_tier", None)
        section.pop(CLIENT_WORKSPACE_CEILING_KEY, None)
    agent_name = _normalized_agent_name(config)
    if agent_name != MOMOBOT_MAX_NAME and agent_name not in workspace_agents:
        return
    settings = app_config.momobot_max
    is_client = getattr(user, "system_role", None) == CLIENT_ROLE
    # A client's tier and effort come from the client their workspace is bound to; staff keep every assignment.
    client_keys = await client_keys_for_user(actor_user_id, resolve_organization_id() if is_client else None) if actor_user_id else ()
    tier = "base" if is_client and not settings.unlocked_for(client_keys) else "max"
    workspace_agent = workspace_agents.get(agent_name)
    if workspace_agent is not None:
        # A client's own workspace agent runs on its own model, capped at MomoBot Max's ceiling.
        model = workspace_agent.model or settings.model
        if user is None or not model_use_allowed(user, model, is_internal=False, fail_closed=app_config.authorization.fail_closed):
            raise HTTPException(status_code=422, detail=_UNRESOLVED_AGENT_DETAIL)
        for section in sections:
            section[CLIENT_WORKSPACE_CEILING_KEY] = True
            if not workspace_agent.model:  # run on the model just checked, never the global default
                section["model_name"] = model
    elif not internal and (user is None or not momobot_max_available_to(user, app_config, tier=tier)):
        raise HTTPException(status_code=422, detail=_UNRESOLVED_AGENT_DETAIL)
    if tier == "base":
        for section in sections:
            section.update(model_name=settings.base_model, reasoning_effort=settings.base_effort, thinking_enabled=False, subagent_enabled=False, momobot_tier="base")
        return
    effort = settings.effort_for(client_keys)
    if staff_runs_cheap(user, settings, fail_closed=app_config.authorization.fail_closed):
        effort = settings.staff_effort
        for section in sections:
            section["model_name"] = settings.staff_model
    for section in sections:
        section.update(reasoning_effort=effort, thinking_enabled=True, subagent_enabled=True, max_total_subagents=app_config.subagents.max_total_per_run, momobot_tier="max")


def _sections(config: dict[str, Any]) -> list[dict[str, Any]]:
    # ``context`` first: it wins over ``configurable`` when both name an agent.
    return [section for section in (config.get("context"), config.get("configurable")) if isinstance(section, dict)]


def _normalized_agent_name(config: dict[str, Any]) -> str:
    """The agent the run names, normalized the way the loaders match names (``""`` when none)."""
    agent_name = next((section["agent_name"] for section in _sections(config) if isinstance(section.get("agent_name"), str)), "")
    return agent_name.strip().lower().replace("_", "-")
