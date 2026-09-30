"""agent_seats.missed_scorecards, agent_seats.last_scorecard_at.

Revision ID: 0042_agent_seats_scorecard
Revises: 0041_agent_seats_budget_pause

Queue item e11 (friday-scorecards): EXECUTIVE.md rule 3, "every Friday, each
employee posts a scorecard; two missed weeks and the title reopens".
``missed_scorecards`` counts consecutive weeks with no scorecard, reset to 0
on a successful post; ``last_scorecard_at`` marks when the weekly check last
ran for this seat, so the sweep only evaluates a seat once per week
regardless of how often it's scheduled to run. Both orthogonal to ``status``
and ``paused_at``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0042_agent_seats_scorecard"
down_revision: str | Sequence[str] | None = "0041_agent_seats_budget_pause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("agent_seats", sa.Column("missed_scorecards", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("agent_seats", sa.Column("last_scorecard_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("agent_seats", "last_scorecard_at")
    safe_drop_column("agent_seats", "missed_scorecards")
