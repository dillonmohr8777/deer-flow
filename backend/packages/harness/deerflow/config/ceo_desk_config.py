from pydantic import BaseModel, Field


class CeoDeskConfig(BaseModel):
    """Background daily-digest generation for the CEO Desk (queue item e14).

    ``deerflow.ceo_desk.digest`` already knows how to count "what shipped,
    what's stuck, what needs my yes" and draft the 3-line digest text; this
    gate wires a recurring sweep into the Gateway lifespan, off by default,
    mirroring ``ExecSeatsConfig``'s budget/scorecard sweeps. A short interval
    just means a due organization is noticed sooner -- ``digest_hour_et`` plus
    the most recent ``ceo_desk_digests`` row is what actually decides whether
    today's digest has already run (at most one per organization per ET
    calendar day, never before ``digest_hour_et``).
    """

    digest_enabled: bool = Field(default=False)
    digest_check_interval_seconds: int = Field(default=1800, ge=30, le=86400)
    digest_hour_et: int = Field(default=8, ge=0, le=23, description="Earliest Eastern-time hour the daily digest may generate.")
