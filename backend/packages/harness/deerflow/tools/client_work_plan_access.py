"""Host-only access to one authenticated portal request's internal record."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from deerflow.runtime.context_keys import CLIENT_WORK_PLAN_ACCESS_CONTEXT_KEY

CLIENT_WORK_PLAN_TOOL_NAMES = ("read_client_work_plan", "update_client_work_plan")


@dataclass(frozen=True)
class ClientWorkPlanAccess:
    actor_id: str
    organization_id: str
    storage_user_id: str
    client_id: str
    request_id: str
    chat_id: str
    run_id: str
    authorize: Callable[[], Awaitable[None]] = field(repr=False)
    read: Callable[[], Awaitable[dict[str, Any]]] = field(repr=False)
    update: Callable[[int, dict], Awaitable[dict[str, Any]]] = field(repr=False)


def matching_client_work_plan_access(context: Mapping) -> ClientWorkPlanAccess | None:
    access = context.get(CLIENT_WORK_PLAN_ACCESS_CONTEXT_KEY)
    if not isinstance(access, ClientWorkPlanAccess):
        return None
    if context.get("agent_name") != "momobot-max" or context.get("user_role") not in {"user", "exec", "admin"} or context.get("is_subagent") or context.get("is_bootstrap") or context.get("channel_name"):
        return None
    expected = {"actor_user_id": access.actor_id, "organization_id": access.organization_id, "storage_user_id": access.storage_user_id, "thread_id": access.chat_id, "run_id": access.run_id}
    return access if all(context.get(key) == value for key, value in expected.items()) else None
