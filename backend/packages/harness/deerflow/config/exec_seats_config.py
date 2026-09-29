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
