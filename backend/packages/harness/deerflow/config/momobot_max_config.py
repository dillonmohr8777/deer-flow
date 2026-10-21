"""Settings for MomoBot Max, the built-in all-in-one agent for client accounts."""

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
        description="Reasoning effort per client, keyed by the client's registry id (or id), e.g. {vhin-cares: high}",
    )

    def effort_for(self, client_keys: tuple[str, ...] = ()) -> MomobotMaxEffort:
        """Effort for a caller assigned to *client_keys*: the first with an override, else the default."""
        return next((self.client_effort[key] for key in client_keys if key in self.client_effort), self.default_effort)
