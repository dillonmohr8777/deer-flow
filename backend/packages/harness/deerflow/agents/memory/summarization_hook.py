"""Hooks fired before summarization removes messages from state."""

from __future__ import annotations

from deerflow.agents.memory import get_memory_manager
from deerflow.agents.memory.admission import memory_access_allowed
from deerflow.agents.memory.manager import capture_owner_kwargs
from deerflow.agents.memory.scope import resolve_memory_scope, scoped_capture_messages
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import get_memory_config


def memory_flush_hook(event: SummarizationEvent) -> None:
    """Flush messages about to be summarized into the memory queue.

    Thin, backend-agnostic entry: only the ``enabled`` + ``thread_id`` gate
    and ``user_id`` resolution live here. The backend (via
    ``manager.add_nowait``) does the filtering, human/AI validation, and
    correction/reinforcement detection.
    """
    if not memory_access_allowed(event.runtime) or not get_memory_config().enabled or not event.thread_id:
        return

    scope = resolve_memory_scope(event.runtime, event.agent_name)
    if scope is None:
        return
    if scope.isolated:
        # Partition rescue moves reminders, so select from original chronology
        # first, then intersect the actual removed objects without reordering.
        eligible = scoped_capture_messages(list(event.original_messages), scope, event.runtime)
        removed_ids = {id(message) for message in event.messages_to_summarize}
        messages = [message for message in eligible if id(message) in removed_ids]
    else:
        messages = list(event.messages_to_summarize)
    if not messages:
        return
    manager = get_memory_manager()
    manager.add_nowait(
        event.thread_id,
        messages,
        agent_name=event.agent_name,
        user_id=scope.user_id,
        **capture_owner_kwargs(manager.add_nowait, scope.storage_user_id),
    )
