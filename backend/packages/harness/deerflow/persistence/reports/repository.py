"""Async repository for workspace-scoped Reports & Leads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.reports.model import (
    ReportConnectorBindingRow,
    ReportLeadRecordRow,
    ReportReviewDocRow,
    ReportWorkspaceSettingRow,
)
from deerflow.reports.connectors import (
    DEFAULT_CONNECTOR_REGISTRY,
    ConnectorBindingContext,
    ConnectorHealthSnapshot,
    ConnectorRegistry,
)
from deerflow.reports.schema import (
    DEFAULT_APPOINTMENT_LABEL,
    VALID_CONNECTOR_KEYS,
    VALID_CONNECTOR_STATUSES,
    VALID_MATCH_CONFIDENCES,
    VALID_MATCH_STATUSES,
    VALID_PERIODS,
    VALID_REVIEW_DOC_STATUSES,
    ConnectorKey,
    ConnectorStatus,
    LeadCategory,
    MatchConfidence,
    MatchStatus,
    ReportingPeriod,
    ReviewDocStatus,
    aggregate_lead_kpis,
    resolve_period_window,
    validate_google_doc_url,
    validate_lead_category,
)


def _utc_iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC).isoformat()
    return ts.astimezone(UTC).isoformat()


def _utc_dt(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _lead_to_dict(row: ReportLeadRecordRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "lead_name": row.lead_name,
        "lead_type": row.lead_type,
        "channel": row.channel,
        "source_connector": row.source_connector,
        "campaign_name": row.campaign_name,
        "external_lead_id": row.external_lead_id,
        "match_status": row.match_status,
        "match_confidence": row.match_confidence,
        "occurred_at": _utc_iso(row.occurred_at),
        "notes": row.notes,
        "created_at": _utc_iso(row.created_at),
    }


def _review_doc_to_dict(row: ReportReviewDocRow) -> dict[str, Any]:
    comments = row.comments_json if isinstance(row.comments_json, list) else []
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "doc_url": row.doc_url,
        "period_key": row.period_key,
        "status": row.status,
        "created_by": row.created_by,
        "decided_by": row.decided_by,
        "decided_at": _utc_iso(row.decided_at),
        "comments": list(comments),
        "created_at": _utc_iso(row.created_at),
        "updated_at": _utc_iso(row.updated_at),
    }


class ReportsRepository:
    """Strictly workspace-scoped read/write repository for Reports & Leads."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.connector_registry = connector_registry or DEFAULT_CONNECTOR_REGISTRY

    async def get_appointment_label(self, workspace_id: str) -> str:
        async with self.session_factory() as session:
            row = await session.get(ReportWorkspaceSettingRow, workspace_id)
            if row and row.appointment_label.strip():
                return row.appointment_label.strip()
        return DEFAULT_APPOINTMENT_LABEL

    async def set_appointment_label(self, workspace_id: str, label: str, *, updated_by: str | None = None) -> str:
        cleaned = label.strip()
        if not cleaned or len(cleaned) > 80:
            raise ValueError("appointment_label must be between 1 and 80 characters")
        now = datetime.now(UTC)
        async with self.session_factory() as session, session.begin():
            row = await session.get(ReportWorkspaceSettingRow, workspace_id)
            if row is None:
                row = ReportWorkspaceSettingRow(
                    workspace_id=workspace_id,
                    appointment_label=cleaned,
                    updated_by=updated_by,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.appointment_label = cleaned
                row.updated_by = updated_by
                row.updated_at = now
        return cleaned

    async def upsert_connector_binding(
        self,
        workspace_id: str,
        *,
        connector_key: ConnectorKey,
        status: ConnectorStatus,
        external_account_ref: str | None = None,
        credential_ref: str | None = None,
        last_synced_at: datetime | None = None,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorHealthSnapshot:
        if connector_key not in VALID_CONNECTOR_KEYS:
            raise ValueError(f"Unsupported connector_key: {connector_key}")
        if status not in VALID_CONNECTOR_STATUSES:
            raise ValueError(f"Unsupported connector status: {status}")
        now = datetime.now(UTC)
        synced = _utc_dt(last_synced_at) if last_synced_at is not None else None
        async with self.session_factory() as session, session.begin():
            existing = (
                await session.execute(
                    select(ReportConnectorBindingRow).where(
                        ReportConnectorBindingRow.workspace_id == workspace_id,
                        ReportConnectorBindingRow.connector_key == connector_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = ReportConnectorBindingRow(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    connector_key=connector_key,
                    status=status,
                    external_account_ref=external_account_ref,
                    credential_ref=credential_ref,
                    last_synced_at=synced,
                    detail=detail,
                    metadata_json=dict(metadata or {}),
                    created_at=now,
                    updated_at=now,
                )
                session.add(existing)
            else:
                existing.status = status
                existing.external_account_ref = external_account_ref
                existing.credential_ref = credential_ref
                existing.last_synced_at = synced
                existing.detail = detail
                if metadata is not None:
                    existing.metadata_json = dict(metadata)
                existing.updated_at = now
            binding = ConnectorBindingContext(
                workspace_id=existing.workspace_id,
                connector_key=existing.connector_key,  # type: ignore[arg-type]
                status=existing.status,  # type: ignore[arg-type]
                external_account_ref=existing.external_account_ref,
                credential_ref=existing.credential_ref,
                last_synced_at=existing.last_synced_at,
                detail=existing.detail,
                metadata=dict(existing.metadata_json or {}),
            )
        adapter = self.connector_registry.get(connector_key)
        return await adapter.check_health(workspace_id, binding, now=now)

    async def list_connectors(self, workspace_id: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (await session.scalars(select(ReportConnectorBindingRow).where(ReportConnectorBindingRow.workspace_id == workspace_id))).all()
        by_key: dict[str, ConnectorBindingContext] = {
            row.connector_key: ConnectorBindingContext(
                workspace_id=row.workspace_id,
                connector_key=row.connector_key,  # type: ignore[arg-type]
                status=row.status,  # type: ignore[arg-type]
                external_account_ref=row.external_account_ref,
                credential_ref=row.credential_ref,
                last_synced_at=row.last_synced_at,
                detail=row.detail,
                metadata=dict(row.metadata_json or {}),
            )
            for row in rows
        }
        snapshots: list[dict[str, Any]] = []
        for adapter in self.connector_registry.all():
            snap = await adapter.check_health(workspace_id, by_key.get(adapter.key), now=now)
            snapshots.append(snap.to_dict())
        return snapshots

    async def record_lead(
        self,
        workspace_id: str,
        *,
        lead_name: str,
        lead_type: str,
        channel: str,
        source_connector: ConnectorKey,
        occurred_at: datetime,
        campaign_name: str = "",
        external_lead_id: str | None = None,
        match_status: MatchStatus = "pending_verification",
        match_confidence: MatchConfidence = "unverified",
        notes: str = "",
    ) -> dict[str, Any]:
        category: LeadCategory = validate_lead_category(lead_type)
        if source_connector not in VALID_CONNECTOR_KEYS:
            raise ValueError(f"Unsupported source_connector: {source_connector}")
        if match_status not in VALID_MATCH_STATUSES:
            raise ValueError(f"Unsupported match_status: {match_status}")
        if match_confidence not in VALID_MATCH_CONFIDENCES:
            raise ValueError(f"Unsupported match_confidence: {match_confidence}")
        cleaned_name = lead_name.strip()
        if not cleaned_name:
            raise ValueError("lead_name must be non-empty")
        now = datetime.now(UTC)
        row = ReportLeadRecordRow(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            lead_name=cleaned_name[:255],
            lead_type=category,
            channel=(channel.strip() or "unknown")[:64],
            source_connector=source_connector,
            campaign_name=campaign_name.strip()[:255],
            external_lead_id=external_lead_id.strip()[:128] if external_lead_id else None,
            match_status=match_status,
            match_confidence=match_confidence,
            occurred_at=_utc_dt(occurred_at),
            notes=notes.strip(),
            created_at=now,
            updated_at=now,
        )
        async with self.session_factory() as session, session.begin():
            session.add(row)
        return _lead_to_dict(row)

    async def list_leads(
        self,
        workspace_id: str,
        *,
        period: ReportingPeriod = "last_30d",
        lead_type: LeadCategory | None = None,
        match_status: MatchStatus | None = None,
        channel: str | None = None,
        limit: int = 100,
        offset: int = 0,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if period not in VALID_PERIODS:
            raise ValueError(f"Unsupported reporting period: {period}")
        if lead_type is not None:
            lead_type = validate_lead_category(lead_type)
        if match_status is not None and match_status not in VALID_MATCH_STATUSES:
            raise ValueError(f"Unsupported match_status: {match_status}")
        start_at, end_at = resolve_period_window(period, now=now)
        filters = [
            ReportLeadRecordRow.workspace_id == workspace_id,
            ReportLeadRecordRow.occurred_at >= start_at,
            ReportLeadRecordRow.occurred_at <= end_at,
        ]
        if lead_type is not None:
            filters.append(ReportLeadRecordRow.lead_type == lead_type)
        if match_status is not None:
            filters.append(ReportLeadRecordRow.match_status == match_status)
        if channel is not None and channel.strip():
            filters.append(ReportLeadRecordRow.channel == channel.strip())
        async with self.session_factory() as session:
            total = int((await session.scalar(select(func.count()).select_from(ReportLeadRecordRow).where(*filters))) or 0)
            rows = (await session.scalars(select(ReportLeadRecordRow).where(*filters).order_by(ReportLeadRecordRow.occurred_at.desc(), ReportLeadRecordRow.id.desc()).offset(offset).limit(limit))).all()
        return [_lead_to_dict(row) for row in rows], total

    async def get_summary(
        self,
        workspace_id: str,
        *,
        period: ReportingPeriod = "last_30d",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if period not in VALID_PERIODS:
            raise ValueError(f"Unsupported reporting period: {period}")
        anchor = _utc_dt(now) if now is not None else datetime.now(UTC)
        start_at, end_at = resolve_period_window(period, now=anchor)
        connectors = await self.list_connectors(workspace_id, now=anchor)
        appointment_label = await self.get_appointment_label(workspace_id)
        async with self.session_factory() as session:
            lead_rows = (
                await session.scalars(
                    select(ReportLeadRecordRow).where(
                        ReportLeadRecordRow.workspace_id == workspace_id,
                        ReportLeadRecordRow.occurred_at >= start_at,
                        ReportLeadRecordRow.occurred_at <= end_at,
                    )
                )
            ).all()
            doc_rows = (await session.scalars(select(ReportReviewDocRow).where(ReportReviewDocRow.workspace_id == workspace_id))).all()

        lead_dicts = [_lead_to_dict(row) for row in lead_rows]
        kpi_summary = aggregate_lead_kpis(lead_dicts, connectors, appointment_label=appointment_label)

        matched_count = sum(1 for row in lead_rows if row.match_status == "matched")
        connector_counts = {
            "connected": sum(1 for item in connectors if item["status"] == "connected"),
            "stale": sum(1 for item in connectors if item["status"] == "stale"),
            "pending": sum(1 for item in connectors if item["status"] == "pending"),
            "unavailable": sum(1 for item in connectors if item["status"] == "unavailable"),
        }
        review_counts = {
            "total": len(doc_rows),
            "pending_review": sum(1 for doc in doc_rows if doc.status == "pending_review"),
            "approved": sum(1 for doc in doc_rows if doc.status == "approved"),
            "needs_edits": sum(1 for doc in doc_rows if doc.status == "needs_edits"),
        }
        return {
            "workspace_id": workspace_id,
            "period": period,
            "window_start": start_at.isoformat(),
            "window_end": end_at.isoformat(),
            "kpis": {
                "total_leads": kpi_summary.total_leads,
                "forms": kpi_summary.forms,
                "calls": kpi_summary.calls,
                "appointments": kpi_summary.appointments,
                "appointment_label": kpi_summary.appointment_label,
                "matched_leads": matched_count if kpi_summary.total_leads is not None else None,
                "data_state": kpi_summary.data_state,
                "connected_lead_sources": list(kpi_summary.connected_lead_sources),
                "pending_lead_sources": list(kpi_summary.pending_lead_sources),
                "unavailable_lead_sources": list(kpi_summary.unavailable_lead_sources),
                "excluded_non_lead_signals": list(kpi_summary.excluded_non_lead_signals),
            },
            "connectors_summary": connector_counts,
            "review_docs_summary": review_counts,
        }

    async def list_review_docs(
        self,
        workspace_id: str,
        *,
        period: ReportingPeriod | None = None,
        status: ReviewDocStatus | None = None,
    ) -> list[dict[str, Any]]:
        if period is not None and period not in VALID_PERIODS:
            raise ValueError(f"Unsupported reporting period: {period}")
        if status is not None and status not in VALID_REVIEW_DOC_STATUSES:
            raise ValueError(f"Unsupported review doc status: {status}")
        filters = [ReportReviewDocRow.workspace_id == workspace_id]
        if period is not None:
            filters.append(ReportReviewDocRow.period_key == period)
        if status is not None:
            filters.append(ReportReviewDocRow.status == status)
        async with self.session_factory() as session:
            rows = (await session.scalars(select(ReportReviewDocRow).where(*filters).order_by(ReportReviewDocRow.created_at.desc(), ReportReviewDocRow.id.desc()))).all()
        return [_review_doc_to_dict(row) for row in rows]

    async def get_review_doc(self, workspace_id: str, doc_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ReportReviewDocRow).where(
                        ReportReviewDocRow.id == doc_id,
                        ReportReviewDocRow.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
        return _review_doc_to_dict(row) if row is not None else None

    async def create_review_doc(
        self,
        workspace_id: str,
        *,
        title: str,
        doc_url: str,
        period_key: ReportingPeriod,
        created_by: str,
    ) -> dict[str, Any]:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Review document title is required")
        if len(cleaned_title) > 255:
            raise ValueError("Review document title must be at most 255 characters")
        if period_key not in VALID_PERIODS:
            raise ValueError(f"Unsupported reporting period: {period_key}")
        validated_url = validate_google_doc_url(doc_url)
        now = datetime.now(UTC)
        row = ReportReviewDocRow(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            title=cleaned_title,
            doc_url=validated_url,
            period_key=period_key,
            status="pending_review",
            created_by=created_by,
            decided_by=None,
            decided_at=None,
            comments_json=[],
            created_at=now,
            updated_at=now,
        )
        async with self.session_factory() as session, session.begin():
            session.add(row)
        return _review_doc_to_dict(row)

    async def update_review_doc(
        self,
        workspace_id: str,
        doc_id: str,
        *,
        actor_id: str,
        actor_label: str,
        status: ReviewDocStatus | None = None,
        comment: str | None = None,
    ) -> dict[str, Any] | None:
        cleaned_comment = comment.strip() if comment is not None else ""
        if status is None and not cleaned_comment:
            raise ValueError("Provide a status update or a non-empty comment")
        if status is not None and status not in VALID_REVIEW_DOC_STATUSES:
            raise ValueError(f"Unsupported review doc status: {status}")
        if len(cleaned_comment) > 4000:
            raise ValueError("Comment must be at most 4000 characters")
        now = datetime.now(UTC)
        async with self.session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(ReportReviewDocRow).where(
                        ReportReviewDocRow.id == doc_id,
                        ReportReviewDocRow.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if cleaned_comment:
                existing_comments = list(row.comments_json) if isinstance(row.comments_json, list) else []
                existing_comments.append(
                    {
                        "id": str(uuid.uuid4()),
                        "author_id": actor_id,
                        "author_label": actor_label.strip() or "Team member",
                        "body": cleaned_comment,
                        "created_at": now.isoformat(),
                    }
                )
                row.comments_json = existing_comments
            if status is not None:
                row.status = status
                if status in ("approved", "needs_edits"):
                    row.decided_by = actor_id
                    row.decided_at = now
                else:
                    row.decided_by = None
                    row.decided_at = None
            row.updated_at = now
            return _review_doc_to_dict(row)
