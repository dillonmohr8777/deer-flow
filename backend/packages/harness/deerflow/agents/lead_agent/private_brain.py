"""Run-local Brain reads for the existing Max agent; never a global permission."""

from deerflow.capabilities.runtime import ambiguous_installation_ids, installation_id
from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.private_scope import current_private_mcp_context, private_mcp_allowed

_BRAIN_READ_TOOLS = ("brain_now", "brain_client", "brain_open_items", "brain_systems")


def private_brain_for_max(agent_name: str | None) -> tuple[ExtensionsConfig, McpServerConfig, str, list[str]] | None:
    """Select only an enabled, explicitly private, scope-authorized Brain server."""
    if agent_name != MOMOBOT_MAX_NAME or current_private_mcp_context() is None:
        return None
    try:
        config = ExtensionsConfig.from_file()
        server = config.get_enabled_mcp_servers().get("brain")
        if server is None or server.private_scope is None or not private_mcp_allowed(server):
            return None
        identity = installation_id("brain", server.model_dump())
        if identity in ambiguous_installation_ids({name: entry.model_dump() for name, entry in config.mcp_servers.items()}):
            return None
        names = [f"brain_{name}" if server.tool_name_prefix else name for name in _BRAIN_READ_TOOLS]
        return config, server, identity, names
    except Exception:
        # Unavailable configuration cannot add private access to the base agent.
        return None
