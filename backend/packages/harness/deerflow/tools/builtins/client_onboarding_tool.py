"""One atomic action per client: create/update project, brief, memory, schedule.

Momentum's welcome skill (``skills/public/welcome``) fans out one ``batch_task``
item per confirmed client; each item calls this single tool once. Bundling the
four steps into one call keeps a batch item's acceptance criteria checkable
against one tool result, and reuses the same repositories/helpers the
projects, project-document, memory, and scheduled-task HTTP routes already
use -- no new persistence logic.

Registered as a core builtin tool (``deerflow.tools.tools.BUILTIN_TOOLS``),
the same tier as ``ask_clarification``/``memory_add``: every write is scoped
to the calling identity's own organization/workspace, so it grants no
authority beyond what that identity's normal HTTP session already has through
the equivalent ``/api/projects``, ``/api/projects/{id}/documents``, and
``/api/scheduled-tasks`` routes.

Identity/organization scoping note: tool execution -- including durable
batch-task items, this tool's primary caller -- never sets the ambient
``_storage_context`` ContextVar the way an HTTP request does; only
``runtime.context["user_id"]`` is threaded through (see
``subagents/executor.py``'s ``context`` construction). So this tool looks up
the calling identity's active organization itself, via
``private_organization_for_user`` (the same resolver
``ProjectRepository.create``/``ScheduledTaskRepository.create`` already use),
and reconstructs ``WorkspaceStorageContext`` for its own duration instead of
leaving ``resolve_organization_id()`` unset. Without that,
``ClientRepository`` (no ``user_id`` column; organization-owned) would apply
no scope at all and could read across every tenant.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from langchain.tools import tool

from deerflow.config.paths import get_paths
from deerflow.projects.documents import add_staged_document, stage_document_bytes
from deerflow.runtime.user_context import (
    WorkspaceStorageContext,
    reset_storage_context,
    resolve_runtime_actor_user_id,
    resolve_runtime_user_id,
    set_storage_context,
)
from deerflow.scheduler.schedules import next_run_at as compute_next_run_at
from deerflow.scheduler.schedules import normalize_cron_expression, validate_timezone
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

_BRIEF_DOCUMENT_NAME = "Client Brief.md"
_BRIEF_MAX_BYTES = 262_144  # 256 KiB: generous for a one-pager, never approached
_WEEKLY_REPORT_CRON = "0 9 * * 1"  # Monday 09:00
_DEFAULT_TIMEZONE = "UTC"
_MIN_FACTS = 1
_MAX_FACTS = 8


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


@tool("onboard_client_workspace", parse_docstring=True)
async def onboard_client_workspace(
    runtime: Runtime,
    client_id: str,
    project_name: str,
    brief_markdown: str,
    memory_facts: list[str],
    scheduled_task_prompt: str,
    project_instructions: str | None = None,
) -> str:
    """Set up one client's Momentum workspace in a single atomic action.

    Creates the project linked to ``client_id`` if none exists yet, else
    updates the existing one (name, and instructions when given); writes
    ``brief_markdown`` to that project's document shelf as "Client Brief.md";
    stores each of ``memory_facts`` as a memory fact; and creates a paused
    weekly (Monday morning UTC) scheduled task running
    ``scheduled_task_prompt``, left paused for the person to review and
    resume from Scheduled Tasks. Every step is scoped to the caller's active
    organization; an unknown or foreign ``client_id`` is a tool error and
    nothing is created.

    Args:
        client_id: The client's id, from list_clients or the client roster -- must belong to the caller's active organization.
        project_name: Display name for the client's project (set on create, renamed on update).
        brief_markdown: One-page client brief in Markdown, written to the project's document shelf.
        memory_facts: 3 to 5 short, specific facts worth remembering about this client (1 to 8 accepted).
        scheduled_task_prompt: The prompt the paused weekly-report scheduled task will run once resumed.
        project_instructions: Optional project instructions/context. Omitted (default) keeps the existing value when updating.

    Returns:
        JSON with "status": "ok", "client_id", "project_id", "project_created"
        (bool), "document_id", "fact_ids" (one entry per requested fact; null
        for any the memory backend could not store), and "scheduled_task_id".
        On failure, JSON with "error" and nothing created.
    """
    if not client_id.strip():
        return _error("client_id must not be empty.")
    if not project_name.strip():
        return _error("project_name must not be empty.")
    if not brief_markdown.strip():
        return _error("brief_markdown must not be empty.")
    if not scheduled_task_prompt.strip():
        return _error("scheduled_task_prompt must not be empty.")
    facts = [fact.strip() for fact in memory_facts if fact and fact.strip()]
    if not (_MIN_FACTS <= len(facts) <= _MAX_FACTS):
        return _error(f"memory_facts must have {_MIN_FACTS} to {_MAX_FACTS} non-empty entries (got {len(facts)}).")

    # Local imports (mirrors deerflow.projects.tools._resolve_pin_and_repo):
    # resolve the session factory and its repositories fresh on every call
    # instead of binding them at module import time, so engine
    # init/close/monkeypatch across the process lifetime (and between tests)
    # is always honored.
    from deerflow.agents.memory.manager import get_memory_manager
    from deerflow.persistence import get_session_factory
    from deerflow.persistence.clients import ClientRepository
    from deerflow.persistence.organizations.resolution import private_organization_for_user
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

    session_factory = get_session_factory()
    if session_factory is None:
        return _error("Workspace storage is unavailable.")

    storage_user_id = resolve_runtime_user_id(runtime)
    actor_user_id = resolve_runtime_actor_user_id(runtime)
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    agent_name = str(context["agent_name"]) if context.get("agent_name") else None

    # organization_id is private_organization_id(storage_user_id) ONLY once an
    # active `organizations` row for it exists (private_organization_for_user
    # is the same resolver ProjectRepository.create/ScheduledTaskRepository.create
    # use) -- the id alone is not enough proof, so it is looked up rather than
    # assumed, and a workspace with none is a clean failure, not an unscoped write.
    async with session_factory() as session:
        organization_id = await private_organization_for_user(session, storage_user_id)
    if organization_id is None:
        return _error(f"No active organization for workspace {storage_user_id!r}.")

    token = set_storage_context(
        WorkspaceStorageContext(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            storage_user_id=storage_user_id,
        )
    )
    try:
        client_repo = ClientRepository(session_factory)
        if await client_repo.get(client_id) is None:
            return _error(f"Unknown client_id {client_id!r}.")

        project_repo = ProjectRepository(session_factory)
        existing = await project_repo.find_by_client_id(client_id, user_id=storage_user_id)
        if existing is None:
            project = await project_repo.create(name=project_name, instructions=project_instructions or "", client_id=client_id, user_id=storage_user_id)
            project_created = True
        else:
            project = await project_repo.patch(existing["id"], name=project_name, instructions=project_instructions, user_id=storage_user_id)
            project_created = False
        if project is None:
            return _error("Project write failed: it became missing or foreign mid-flight.")
        project_id = project["id"]

        paths = get_paths()
        staged = await stage_document_bytes(paths, user_id=storage_user_id, project_id=project_id, chunks=[brief_markdown.encode("utf-8")], max_bytes=_BRIEF_MAX_BYTES)
        added = await add_staged_document(
            ProjectDocumentRepository(session_factory),
            paths,
            user_id=storage_user_id,
            project_id=project_id,
            name=_BRIEF_DOCUMENT_NAME,
            staged=staged,
            source_kind="agent",
        )
        if added is None:
            return _error("Project shelf write failed: the project became missing, foreign, or archived.")
        document_row, _created = added

        manager = get_memory_manager()
        fact_ids: list[str | None] = []
        for fact in facts:
            try:
                _memory_data, fact_id = manager.create_fact(fact, category="client", confidence=0.8, agent_name=agent_name, user_id=storage_user_id)
            except NotImplementedError:
                # Backend does not support create_fact at all (e.g. noop).
                fact_id = None
            except Exception:
                # Best-effort per fact: a duplicate (ValueError) or any other
                # single-fact failure should not abort the shelf write and
                # scheduled task already/still to come.
                logger.warning("onboard_client_workspace: could not store memory fact for client_id=%s", client_id, exc_info=True)
                fact_id = None
            fact_ids.append(fact_id)

        cron = normalize_cron_expression(_WEEKLY_REPORT_CRON)
        timezone = validate_timezone(_DEFAULT_TIMEZONE)
        schedule_spec = {"cron": cron}
        next_run_at = compute_next_run_at("cron", schedule_spec, timezone, now=datetime.now(UTC))

        scheduled_task_repo = ScheduledTaskRepository(session_factory)
        # ponytail: no idempotency guard against a duplicate weekly-report task
        # on a retried item (unlike the project lookup and the shelf's content
        # dedup, both naturally idempotent). Add a client-linked-task lookup,
        # mirroring find_by_client_id, if retries turn out to double these up.
        task = await scheduled_task_repo.create(
            task_id=f"task-{uuid.uuid4().hex}",
            user_id=storage_user_id,
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title=f"Weekly report: {project_name}",
            prompt=scheduled_task_prompt,
            schedule_type="cron",
            schedule_spec=schedule_spec,
            timezone=timezone,
            next_run_at=next_run_at,
            delegation_owner_user_id=actor_user_id,
        )
        await scheduled_task_repo.pause_with_queue_cancellation(
            task["id"],
            user_id=storage_user_id,
            error="paused for approval after client onboarding",
            now=datetime.now(UTC),
        )
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        logger.exception("onboard_client_workspace failed for client_id=%s", client_id)
        return _error(str(exc))
    finally:
        reset_storage_context(token)

    return json.dumps(
        {
            "status": "ok",
            "client_id": client_id,
            "project_id": project_id,
            "project_created": project_created,
            "document_id": document_row["id"],
            "fact_ids": fact_ids,
            "scheduled_task_id": task["id"],
        },
        ensure_ascii=False,
    )
