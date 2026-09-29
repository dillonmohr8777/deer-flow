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
