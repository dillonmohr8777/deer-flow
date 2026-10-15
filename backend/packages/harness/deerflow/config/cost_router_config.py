"""Config for the cost router: task class to model routes, spend caps and prices."""

from fnmatch import fnmatchcase

from pydantic import BaseModel, ConfigDict, Field


class ModelPrice(BaseModel):
    """USD per one million tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)


class RouteConfig(BaseModel):
    """One route: the model a task class runs on, plus optional USD caps."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(min_length=1, description="Name of an entry in `models:`.")
    daily_cap_usd: float | None = Field(default=None, gt=0)
    monthly_cap_usd: float | None = Field(default=None, gt=0)


class CostRouterConfig(BaseModel):
    """Cost router. Off by default except the denylist, which always applies."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(default=False, description="Turn on routing and spend caps.")
    default_route: str | None = Field(default=None, description="Route used when a run names no task class and no model.")
    routes: dict[str, RouteConfig] = Field(default_factory=dict, description="Task class to route.")
    prices: dict[str, ModelPrice] = Field(default_factory=dict, description="Price per model name (config name or provider model id).")
    denylist: list[str] = Field(default_factory=lambda: ["meta/muse-*"], description="fnmatch patterns that are always refused. Meta restricted Muse on this account.")

    def is_denied(self, *names: str | None) -> bool:
        return any(fnmatchcase(n.lower(), p.lower()) for n in names if n for p in self.denylist)
