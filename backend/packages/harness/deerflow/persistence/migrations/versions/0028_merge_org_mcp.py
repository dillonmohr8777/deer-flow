"""Merge Momentum organization lineage and upstream MCP lease fencing."""

revision = "0028_merge_org_mcp"
down_revision = ("0027_organization_backfill", "0026_mcp_task_lease_tokens")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
