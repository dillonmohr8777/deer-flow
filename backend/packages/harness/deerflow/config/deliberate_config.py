from pydantic import BaseModel, Field


class DeliberateConfig(BaseModel):
    """OpenRouter Fusion deliberation panel for big-project planning (queue item e13).

    A deliberation call fans the prompt out to several third-party model
    providers behind OpenRouter's ``openrouter:fusion`` server tool, so it
    uses its own API key rather than the Luna/Muse-restricted default model
    lane -- and it is off by default until Dillon sets that key. ``cheap``
    and ``quality`` are the two presets an agent may pick between; both are
    plain OpenRouter model ids.
    """

    enabled: bool = Field(default=False)
    openrouter_api_key: str | None = Field(default=None, description="OpenRouter API key used only for deliberation panel calls.")
    cheap_model: str = Field(default="openrouter/auto")
    quality_model: str = Field(default="openrouter/auto")
    max_calls_per_turn: int = Field(default=1, ge=1, description="Deliberation is expensive; cap calls per conversational turn.")
