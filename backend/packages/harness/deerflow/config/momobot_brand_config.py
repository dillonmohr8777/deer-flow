"""``momobot_brand`` section of config.yaml: where the private brand kit lives."""

from pydantic import BaseModel, Field


class MomobotBrandConfig(BaseModel):
    """The kit (agents.json, about.md, icons, videos) is never committed.

    ``content_dir`` points at a server-side folder; unset disables the About
    panel, the Lineup page and the Slack About reply.
    """

    content_dir: str | None = Field(default=None, description="Server-side folder holding the MomoBot brand kit (production mounts ~/momobot-prod/brand).")
