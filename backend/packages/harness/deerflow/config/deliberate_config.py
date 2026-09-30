from pydantic import BaseModel, Field


class DeliberateConfig(BaseModel):
    """OpenRouter Fusion deliberation panel for big-project planning (queue item e13).

    A deliberation call fans the prompt out independently to every model in
    the selected preset's panel, then an analyst model synthesizes their
    actual answers -- it is never asked to invent opinions it was never
    shown. Uses its own API key rather than the Luna/Muse-restricted default
    model lane, and is off by default until Dillon sets that key. ``cheap``
    and ``quality`` are the two panel presets an agent may pick between;
    every model id is a plain OpenRouter model id.
    """

    enabled: bool = Field(default=False)
    openrouter_api_key: str | None = Field(default=None, description="OpenRouter API key used only for deliberation panel calls.")
    cheap_panel_models: list[str] = Field(default_factory=lambda: ["openrouter/auto"])
    quality_panel_models: list[str] = Field(default_factory=lambda: ["openrouter/auto"])
    analyst_model: str = Field(default="openrouter/auto")
    max_calls_per_turn: int = Field(default=1, ge=1, description="Deliberation is expensive; cap calls per conversational turn.")
