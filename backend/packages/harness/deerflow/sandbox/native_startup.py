"""Conservative, assembly-owned proof that an empty skill view is unused."""

import sys
from collections.abc import Sequence

from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool

from deerflow.sandbox.middleware import SandboxMiddleware


def configure_native_lazy_startup(
    middlewares: Sequence[object],
    tools: Sequence[BaseTool],
    *,
    available_skills: set[str] | None,
    deferred_names: frozenset[str],
    has_extension_middlewares: bool,
) -> bool:
    """Derive eligibility only after final tools and middleware composition.

    Unknown tools, clones, deferred catalogs and contributed middleware retain
    the ordinary sandbox path. Tool names and model-visible metadata are not
    capability evidence. No request/config flag may enable this optimization.
    """
    for middleware in middlewares:
        if type(middleware) is SandboxMiddleware:
            middleware.configure_native_tools(None)
    if available_skills is None or available_skills or deferred_names or has_extension_middlewares:
        return False

    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.tools.builtins.agent_room_tool import agent_room_post, agent_room_read
    from deerflow.tools.builtins.approved_agency_tool import approved_agency_phase
    from deerflow.tools.builtins.batch_task_tool import batch_status, cancel_batch
    from deerflow.tools.builtins.present_file_tool import present_file_tool

    native_tools = (agent_room_read, agent_room_post, approved_agency_phase, batch_status, cancel_batch, present_file_tool)
    candidates = list(tools)
    sandboxes: list[SandboxMiddleware] = []
    for middleware in middlewares:
        if not isinstance(middleware, AgentMiddleware):
            return False
        cls = type(middleware)
        # A canonical wrapper can hold arbitrary reflected provider callbacks.
        # Keep its ordinary policy path; do not disable or bypass that guard.
        if isinstance(middleware, GuardrailMiddleware):
            return False
        # Even an empty contributed tool list does not prove unknown hooks are
        # sandbox-free. Require a canonical host middleware implementation.
        if not cls.__module__.startswith(("deerflow.agents.middlewares.", "deerflow.guardrails.", "deerflow.sandbox.")) or getattr(sys.modules.get(cls.__module__), cls.__name__, None) is not cls:
            return False
        contributed_tools = getattr(middleware, "tools", ())
        if not isinstance(contributed_tools, (list, tuple)):
            return False
        candidates.extend(contributed_tools)
        if cls is SandboxMiddleware and isinstance(middleware, SandboxMiddleware):
            sandboxes.append(middleware)
    if not sandboxes or any(not sandbox.native_startup_is_lazy or sandbox.native_startup_has_skills for sandbox in sandboxes):
        return False
    if any(not any(tool is native for native in native_tools) for tool in candidates):
        return False
    for sandbox in sandboxes:
        sandbox.configure_native_tools(tuple(candidates))
    return True
