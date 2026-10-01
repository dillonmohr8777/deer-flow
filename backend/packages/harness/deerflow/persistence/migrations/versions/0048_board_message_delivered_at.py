"""board_messages.delivered_at.

Revision ID: 0048_board_message_delivered_at
Revises: 0047_merge_agent_room_exec

Momo Board item f157/f172 (queue): a non-admin's visibility into a board
thread and its messages must never be inferred from ``author_kind ==
"owner"`` alone -- ``add_board_message`` lets any org admin post an
``owner``-authored internal note on a thread with ``POST
/threads/{id}/messages`` (e.g. review feedback on a still-unapproved draft),
which is not the same thing as ``send_board_reply`` actually delivering
content to the client. ``delivered_at`` is stamped only by
``send_board_reply``'s own write, so it is the one tamper-proof signal for
"this thread has genuinely shipped something to the client" that
``BoardRepository.thread_ids_with_delivered_message`` and
``list_board_messages`` rely on. Nullable: every existing message, and any
owner note that isn't a reply, is simply never delivered.

f174 (queue): this branch's own head was originally ``0046_organization_
entitlements`` (unmerged into ``lane/momo-week`` all week), so the first cut
of this migration chained off it directly -- colliding with lane's own
``0047_merge_agent_room_exec`` (also on 0046) once this branch finally merges
in. Renumbered to 0048 and rechained onto that merge revision after pulling
the lane in, per the review's own fix.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0048_board_message_delivered_at"
down_revision: str | Sequence[str] | None = "0047_merge_agent_room_exec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("board_messages", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("board_messages", "delivered_at")
