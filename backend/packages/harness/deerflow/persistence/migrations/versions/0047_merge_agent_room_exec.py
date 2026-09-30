"""Join the shipped private room and executive-seat histories without DDL.

The standby database shipped 0040_agent_room_messages after 0039; the lane
independently shipped 0040_agent_seats and its descendants after the same
parent. Preserve both edges so Alembic executes the missing branch on either
deployment. Never restamp a deployed room database or reparent its revision.
"""

revision = "0047_merge_agent_room_exec"
down_revision = ("0046_organization_entitlements", "0040_agent_room_messages")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
