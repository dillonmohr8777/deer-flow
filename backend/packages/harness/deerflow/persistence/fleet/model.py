"""ORM model for fleet template-to-client agent bindings (fleet foundation item 3).

One row per ``(client_id, template_id)``: the organization-scoped record of
"this client already has an agent stamped from this template", so
``POST /api/clients/{client_id}/agents`` can answer idempotently without ever
scanning every owner's agents (``AgentStore.list_all()`` is reserved for the
GitHub registry and must never be called from an org-scoped route; see
``persistence/agents/sql.py``). The actual agent definition (name, model,
skills, SOUL.md) lives in the personal ``agents`` table, owned by whichever
user stamped it; this table is the org-shared index pointing at it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FleetAgentBindingRow(Base):
    __tablename__ = "fleet_agent_bindings"
    __table_args__ = (UniqueConstraint("client_id", "template_id", name="uq_fleet_agent_bindings_client_template"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    template_id: Mapped[str] = mapped_column(String(128))
    template_version: Mapped[str] = mapped_column(String(32))
    agent_name: Mapped[str] = mapped_column(String(128))
    agent_owner_user_id: Mapped[str] = mapped_column(String(64))
    scheduled_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
