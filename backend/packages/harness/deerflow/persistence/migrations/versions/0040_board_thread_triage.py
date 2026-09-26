"""board_threads.urgency, board_threads.summary.

Revision ID: 0040_board_thread_triage
Revises: 0039_team_board_academy

Momo Board item e2: persists b3's triage classification (urgency, a
one-sentence summary) on the thread itself instead of discarding it, so
owner alerts (e4) and the concierge loop (e5) have something to read. Both
columns are nullable: a thread created before this migration, or one whose
triage call failed in a way that skipped the patch entirely, simply has no
recorded triage yet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0040_board_thread_triage"
down_revision: str | Sequence[str] | None = "0039_team_board_academy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("board_threads", sa.Column("urgency", sa.String(length=16), nullable=True))
    safe_add_column("board_threads", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("board_threads", "summary")
    safe_drop_column("board_threads", "urgency")
