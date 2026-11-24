"""Workspace-scoped Reports & Leads tables.

Revision ID: 0055_reports_leads
Revises: 0054_no_phi_flag

Adds additive, workspace-isolated tables for:
- ``report_connector_bindings`` (Plane 0 read connector health and opaque refs)
- ``report_lead_records`` (verified form, call, and appointment lead match-back)
- ``report_review_docs`` (attached Google Docs with timestamped comments and approval states)
- ``report_workspace_settings`` (configurable vertical appointment label)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_reports_leads"
down_revision: str | Sequence[str] | None = "0054_no_phi_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("report_connector_bindings"):
        op.create_table(
            "report_connector_bindings",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("connector_key", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("external_account_ref", sa.String(length=256), nullable=True),
            sa.Column("credential_ref", sa.String(length=128), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "connector_key", name="uq_report_connector_workspace_key"),
        )
        op.create_index("ix_report_connector_bindings_workspace_id", "report_connector_bindings", ["workspace_id"])

    if not inspector.has_table("report_lead_records"):
        op.create_table(
            "report_lead_records",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("lead_name", sa.String(length=255), nullable=False),
            sa.Column("lead_type", sa.String(length=24), nullable=False),
            sa.Column("channel", sa.String(length=64), nullable=False),
            sa.Column("source_connector", sa.String(length=32), nullable=False),
            sa.Column("campaign_name", sa.String(length=255), nullable=False),
            sa.Column("external_lead_id", sa.String(length=128), nullable=True),
            sa.Column("match_status", sa.String(length=32), nullable=False),
            sa.Column("match_confidence", sa.String(length=24), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_report_lead_records_workspace_occurred", "report_lead_records", ["workspace_id", "occurred_at"])
        op.create_index("ix_report_lead_records_workspace_type", "report_lead_records", ["workspace_id", "lead_type"])

    if not inspector.has_table("report_review_docs"):
        op.create_table(
            "report_review_docs",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("doc_url", sa.String(length=1024), nullable=False),
            sa.Column("period_key", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("decided_by", sa.String(length=64), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("comments_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_report_review_docs_workspace_created", "report_review_docs", ["workspace_id", "created_at"])

    if not inspector.has_table("report_workspace_settings"):
        op.create_table(
            "report_workspace_settings",
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("appointment_label", sa.String(length=80), nullable=False),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("workspace_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if inspector.has_table("report_workspace_settings"):
        op.drop_table("report_workspace_settings")

    if inspector.has_table("report_review_docs"):
        op.drop_index("ix_report_review_docs_workspace_created", table_name="report_review_docs")
        op.drop_table("report_review_docs")

    if inspector.has_table("report_lead_records"):
        op.drop_index("ix_report_lead_records_workspace_type", table_name="report_lead_records")
        op.drop_index("ix_report_lead_records_workspace_occurred", table_name="report_lead_records")
        op.drop_table("report_lead_records")

    if inspector.has_table("report_connector_bindings"):
        op.drop_index("ix_report_connector_bindings_workspace_id", table_name="report_connector_bindings")
        op.drop_table("report_connector_bindings")
