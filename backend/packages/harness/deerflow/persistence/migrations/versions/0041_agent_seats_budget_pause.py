"""agent_seats.paused_at.

Revision ID: 0041_agent_seats_budget_pause
Revises: 0040_agent_seats

Queue item e10 (seat-budgets): a nullable timestamp marking a seat paused for
exceeding its weekly token budget, orthogonal to the claim/ratify/reopen
``status`` state machine (a paused seat is still claimed or ratified; it is
just not allowed to keep running until usage rebalances).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0041_agent_seats_budget_pause"
down_revision: str | Sequence[str] | None = "0040_agent_seats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("agent_seats", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("agent_seats", "paused_at")
