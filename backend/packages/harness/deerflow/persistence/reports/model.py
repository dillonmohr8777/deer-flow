"""ORM models for workspace-scoped Reports & Leads.

Every row is strictly keyed by ``workspace_id`` (the active organization ID).
No raw third-party credentials or client PII secrets are stored here: connector
bindings hold only opaque external account IDs and secret-store reference names.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base
from deerflow.reports.schema import DEFAULT_APPOINTMENT_LABEL


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReportConnectorBindingRow(Base):
    """Per-workspace read connector status and non-secret binding metadata."""

    __tablename__ = "report_connector_bindings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "connector_key", name="uq_report_connector_workspace_key"),
        Index("ix_report_connector_bindings_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    external_account_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class ReportLeadRecordRow(Base):
    """Workspace-scoped verified lead record for named-lead match-back."""

    __tablename__ = "report_lead_records"
    __table_args__ = (
        Index("ix_report_lead_records_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_report_lead_records_workspace_type", "workspace_id", "lead_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_type: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    source_connector: Mapped[str] = mapped_column(String(32), nullable=False, default="google_sheets")
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_lead_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_verification")
    match_confidence: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class ReportReviewDocRow(Base):
    """Attached Google Doc report awaiting review, timestamped comments, and approval."""

    __tablename__ = "report_review_docs"
    __table_args__ = (Index("ix_report_review_docs_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    period_key: Mapped[str] = mapped_column(String(24), nullable=False, default="last_30d")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_review")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comments_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class ReportWorkspaceSettingRow(Base):
    """Workspace-level reporting display settings such as the vertical appointment label."""

    __tablename__ = "report_workspace_settings"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    appointment_label: Mapped[str] = mapped_column(String(80), nullable=False, default=DEFAULT_APPOINTMENT_LABEL)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)
