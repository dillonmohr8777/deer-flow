"""ORM model registration entry point.

Importing this module ensures all ORM models are registered with
``Base.metadata`` so Alembic autogenerate detects every table.

The actual ORM classes have moved to entity-specific subpackages:
- ``deerflow.persistence.thread_meta``
- ``deerflow.persistence.run``
- ``deerflow.persistence.feedback``
- ``deerflow.persistence.user``

``RunEventRow`` remains in ``deerflow.persistence.models.run_event`` because
its storage implementation lives in ``deerflow.runtime.events.store.db`` and
there is no matching entity directory.
"""

from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.board.model import BoardMessageRow, BoardThreadRow
from deerflow.persistence.channel_connections.model import (
    ChannelConnectionRow,
    ChannelConversationRow,
    ChannelCredentialRow,
    ChannelOAuthStateRow,
)
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.fleet.model import FleetAgentBindingRow
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.organizations.branding import OrganizationBrandingRow
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationDelegationRow, OrganizationMemberRow, OrganizationRow
from deerflow.persistence.personal_access_tokens.model import PersonalAccessTokenRow
from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow, SubagentBatchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserPreferenceRow, UserRow
from deerflow.persistence.user_mfa.model import UserMfaRow
from deerflow.persistence.webhook_delivery.model import WebhookDeliveryRow

__all__ = [
    "AgentRow",
    "BoardMessageRow",
    "BoardThreadRow",
    "ChannelConnectionRow",
    "ChannelConversationRow",
    "ChannelCredentialRow",
    "ChannelOAuthStateRow",
    "ClientAssignmentRow",
    "ClientRow",
    "FeedbackRow",
    "FleetAgentBindingRow",
    "InvitationRow",
    "McpTaskRow",
    "ManagedSubagentRow",
    "OrganizationBrandingRow",
    "OrganizationDelegationRow",
    "OrganizationMemberRow",
    "OrganizationRow",
    "PersonalAccessTokenRow",
    "ProjectDocumentRow",
    "ProjectRow",
    "RunEventRow",
    "RunChangeClockRow",
    "RunRow",
    "ScheduledTaskRow",
    "ScheduledTaskRunRow",
    "SubagentBatchRow",
    "SubagentBatchItemRow",
    "ThreadMetaRow",
    "UserMfaRow",
    "UserPreferenceRow",
    "UserRow",
    "WebhookDeliveryRow",
]
