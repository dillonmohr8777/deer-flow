from pydantic import BaseModel, Field


class ExecSeatsConfig(BaseModel):
    """Background enforcement for Momentum agent-seat weekly token budgets (queue item f95).

    ``deerflow.exec_seats.budget.evaluate_all_seat_budgets`` (e10) already knows
    how to pause and resume a seat; nothing called it on a schedule and nothing
    stopped a paused seat's agent from running, so a budget pause had no real
    effect. This gate wires the periodic sweep into the Gateway lifespan,
    mirroring ``SchedulerConfig``'s off-by-default posture.
    """

    budget_check_enabled: bool = Field(default=False)
    budget_check_interval_seconds: int = Field(default=300, ge=30, le=3600)

    # Weekly scorecard sweep (queue item e11, EXECUTIVE.md rule 3): every
    # ratified seat gets one scorecard check per trailing week regardless of
    # how often this loop actually runs (see
    # ``deerflow.exec_seats.scorecard.evaluate_seat_scorecard``'s
    # ``last_scorecard_at`` gate), so a short interval just means the sweep
    # notices a seat's due week sooner, not more than once.
    scorecard_check_enabled: bool = Field(default=False)
    scorecard_check_interval_seconds: int = Field(default=3600, ge=30, le=86400)
