from pydantic import BaseModel, Field


class HiringConfig(BaseModel):
    """Owner-set caps for EXECUTIVE.md's autonomous hiring (queue item e12).

    Any titled employee (a ratified agent-seat holder) or one of its own
    active hires may hire and retire its own reports with no approval needed
    -- these two caps are the only owner-controlled brakes on that: how many
    active hires the organization may carry at once, and how many manager
    levels deep a hire chain may go ("Caps. Headcount cap and org depth
    (3 levels) are Dillon's settings.").
    """

    headcount_cap: int = Field(default=20, ge=0, description="Org-wide cap on active hires. 0 = unlimited.")
    max_org_depth: int = Field(default=3, ge=1, le=10, description="Deepest a hire chain may go below a titled employee (depth 1).")

    # Idle-probation sweep (EXECUTIVE.md Hiring rule: "A hire idle 7 days ...
    # is retired automatically"). Off by default, mirroring
    # ``ExecSeatsConfig``'s budget/scorecard sweeps.
    retirement_check_enabled: bool = Field(default=False)
    retirement_check_interval_seconds: int = Field(default=3600, ge=30, le=86400)
    idle_days_before_retirement: int = Field(default=7, ge=1, description="A hire with no run activity for this many days is retired automatically.")

    # KPI-review sweep, the other half of the same Probation rule ("missing
    # its KPI 2 weeks running is retired automatically"). Off by default,
    # same posture as the idle-probation sweep above.
    kpi_check_enabled: bool = Field(default=False)
    kpi_check_interval_seconds: int = Field(default=3600, ge=30, le=86400)
