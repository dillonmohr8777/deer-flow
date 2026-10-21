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

MOMOBOT_MAX_NAME = "momobot-max"

# The most a MomoBot Max run can ever call, whoever runs it and however the
# role policy is configured. Role policy can narrow this further, never widen it.
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

_SOUL_PATH = Path(__file__).with_name("momobot_max.md")


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


def get_builtin_agent_soul(name: str | None) -> str | None:
    if get_builtin_agent_config(name) is None:
        return None
    return _SOUL_PATH.read_text(encoding="utf-8").strip()
