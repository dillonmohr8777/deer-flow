"""Built-in agents: global (not per-user), read-only, defined in code.

Today that is ``momobot-max``, the all-in-one agent client accounts chat with.
It exists only while ``momobot_max.enabled`` is true, so an instance that never
mentions it behaves exactly as before. ``agents_config.load_agent_config`` and
``load_agent_soul`` consult this registry first, ahead of any per-user or legacy
agent of the same name, so nobody can shadow it.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.config.agents_config import AgentConfig
from deerflow.knowledge_scope import KnowledgeScope

MOMOBOT_MAX_NAME = "momobot-max"

# The ordinary ceiling, including every client/staff run. Role policy can narrow it.
MOMOBOT_MAX_TOOL_NAMES = [
    "web_search",
    "web_fetch",
    "read_file",
    "write_file",
    "present_files",
    "ask_clarification",
    "view_image",
    "task",
    "tool_search",
]

# Only lead assembly with the authenticated host capability may add these names.
MOMOBOT_MAX_ADMIN_DIAGNOSTIC_TOOL_NAMES = ["wsl_diagnostic"]

_SOUL_PATH = Path(__file__).with_name("momobot_max.md")

# What a client on the base subscription sees of the same agent (MomoBot Max is base plus the all-in-one agent).
MOMOBOT_BASE_DISPLAY_NAME = "MomoBot"
MOMOBOT_BASE_DESCRIPTION = "Your marketing teammate: ask about your business, your results and what to do next."


def _momobot_max_model() -> str | None:
    """The configured model name, or ``None`` while the agent is off (or no config exists)."""
    from deerflow.config.app_config import get_app_config

    try:
        settings = get_app_config().momobot_max
    except FileNotFoundError:  # lightweight contexts (CLI, tests) have no config.yaml
        return None
    return settings.model if settings.enabled else None


def is_builtin_agent_name(name: str | None) -> bool:
    return name == MOMOBOT_MAX_NAME


def get_builtin_agent_config(name: str | None) -> AgentConfig | None:
    """The built-in agent called *name*, or ``None`` if there is none (or it is disabled)."""
    if not is_builtin_agent_name(name):
        return None
    model = _momobot_max_model()
    if model is None:
        return None
    return AgentConfig(
        name=MOMOBOT_MAX_NAME,
        display_name="MomoBot Max",
        description="Your all-in-one marketing teammate: ads, content, search, reviews, your website, email, leads and reporting.",
        model=model,
        skills=[],
        mcp_plugins=[],
        tool_names=list(MOMOBOT_MAX_TOOL_NAMES),
        self_update_enabled=False,
    )


# Run-config key the Gateway sets (never a request) when a client runs one of their workspace's agents.
CLIENT_WORKSPACE_CEILING_KEY = "client_workspace_ceiling"


def client_workspace_ceiling(agent: AgentConfig) -> AgentConfig:
    """*agent* as a client may run it: never more than MomoBot Max's own ceiling.

    A workspace agent is staff-authored, so a client run keeps its model, SOUL and
    tool choice only within MomoBot Max's tools, with no skills, MCP servers,
    self-editing, shared memory (it may hold staff conversations) or knowledge search.
    """
    tools = agent.tool_names if agent.tool_names is not None else MOMOBOT_MAX_TOOL_NAMES
    return agent.model_copy(
        update={
            "tool_names": [name for name in tools if name in MOMOBOT_MAX_TOOL_NAMES],
            "skills": [],
            "mcp_plugins": [],
            "self_update_enabled": False,
            "memory_enabled": False,
            "knowledge_scope": KnowledgeScope(version=1, mode="disabled"),
        }
    )


def get_builtin_agent_soul(name: str | None) -> str | None:
    if get_builtin_agent_config(name) is None:
        return None
    return _SOUL_PATH.read_text(encoding="utf-8").strip()
