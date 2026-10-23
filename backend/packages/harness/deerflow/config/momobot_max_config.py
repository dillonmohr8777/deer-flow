"""Settings for the client chat: the MomoBot base subscription and MomoBot Max.

MomoBot Max is the base subscription plus the all-in-one agent. Every client
account chats with the same built-in agent (one memory); a client listed in
``clients`` gets it as MomoBot Max (the all-in-one model, effort and subagent
team), every other client gets the base MomoBot chat.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MomobotMaxEffort = Literal["low", "medium", "high"]


class MomobotMaxConfig(BaseModel):
    """``momobot_max:`` in config.yaml. Off by default: the agent does not exist until enabled."""

    enabled: bool = Field(default=False, description="Expose the built-in momobot-max agent")
    model: str = Field(default="claude-opus-5-5", description="Name of the models: entry the agent runs on")
    default_effort: MomobotMaxEffort = Field(default="high", description="Reasoning effort when the caller has no per-client override")
    client_effort: dict[str, MomobotMaxEffort] = Field(
        default_factory=dict,
        description="Reasoning effort per client, keyed by the client's registry id (or id), e.g. {acme-dental: high}",
    )
    clients: list[str] = Field(
        default_factory=list,
        description="Clients unlocked for MomoBot Max, by registry id (or id). Every other client account gets the base MomoBot chat.",
    )
    client_default_agents: dict[str, str] = Field(
        default_factory=dict,
        description="Default custom workspace agent per authenticated client key, used only when no agent is requested; the existing workspace-agent gate still applies.",
    )
    base_model: str = Field(default="claude-haiku-5-5", description="Name of the models: entry the base MomoBot chat runs on")
    base_effort: MomobotMaxEffort = Field(default="medium", description="Reasoning effort for the base MomoBot chat")
    staff_model: str | None = Field(
        default=None,
        description="Model non-admin staff run MomoBot Max on (e.g. claude-haiku-5-5); unset means `model`. Admins always get `model`.",
    )
    staff_effort: MomobotMaxEffort = Field(default="high", description="Reasoning effort for staff runs on `staff_model`")

    def unlocked_for(self, client_keys: tuple[str, ...] = ()) -> bool:
        """Whether a caller assigned to *client_keys* has MomoBot Max (any one key unlocks it)."""
        return any(key in self.clients for key in client_keys)

    def effort_for(self, client_keys: tuple[str, ...] = ()) -> MomobotMaxEffort:
        """Effort for a caller assigned to *client_keys*: the first with an override, else the default."""
        return next((self.client_effort[key] for key in client_keys if key in self.client_effort), self.default_effort)
