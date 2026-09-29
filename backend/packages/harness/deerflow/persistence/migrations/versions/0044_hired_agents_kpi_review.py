"""hired_agents.missed_kpi_checks, hired_agents.last_kpi_check_at.

Revision ID: 0044_hired_agents_kpi_review
Revises: 0043_hiring

Queue item e12 (agent-hiring): EXECUTIVE.md's Probation rule, "missing its
KPI 2 weeks running" -- the other half of the idle-7-days check
``deerflow.hiring.retirement`` already covers. ``missed_kpi_checks`` counts
consecutive weeks a hire's KPI review came back "missed" (or failed to
generate), reset to 0 on a "met" review; ``last_kpi_check_at`` marks when the
weekly check last ran for this hire, mirroring
``0042_agent_seats_scorecard``'s columns exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0044_hired_agents_kpi_review"
down_revision: str | Sequence[str] | None = "0043_hiring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("hired_agents", sa.Column("missed_kpi_checks", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("hired_agents", sa.Column("last_kpi_check_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("hired_agents", "last_kpi_check_at")
    safe_drop_column("hired_agents", "missed_kpi_checks")
