"""Show the drafting agent the last few reviewer edits for its client.

The block is rendered into the model request only (never written to graph state),
placed before the current user message, and removed and re-added on every call so
it cannot pile up. Failure to read the ledger never blocks a run.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

from deerflow.runtime.user_context import resolve_runtime_user_id

logger = logging.getLogger(__name__)

_MARKER = "client_corrections"
_LIMIT = 10


def _is_ours(message: object) -> bool:
    return bool((getattr(message, "additional_kwargs", None) or {}).get(_MARKER))


class ClientCorrectionsMiddleware(AgentMiddleware):
    def __init__(self, agent_name: str | None) -> None:
        super().__init__()
        self._agent_name = agent_name

    async def _block(self, runtime: object) -> str:
        from deerflow.persistence.approvals.corrections import ClientCorrectionRepository, render_corrections
        from deerflow.persistence.engine import get_session_factory

        session_factory = get_session_factory()
        if session_factory is None or not self._agent_name:
            return ""
        repo = ClientCorrectionRepository(session_factory)
        user_id = resolve_runtime_user_id(runtime)
        key = await repo.client_key_for(user_id, self._agent_name)
        return render_corrections(await repo.recent(user_id, key, _LIMIT)) if key else ""

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
        # The ledger is async-only; a sync run (stream()/invoke()) simply goes without it.
        return handler(request)

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        try:
            block = await self._block(getattr(request, "runtime", None))
        except Exception:
            logger.warning("client corrections unavailable", exc_info=True)
            block = ""
        messages = [m for m in request.messages if not _is_ours(m)]
        if block:
            last_human = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), len(messages))
            note = HumanMessage(content=block, additional_kwargs={_MARKER: True, **provenance_kwargs(ContentKind.MEMORY, _MARKER)})
            messages = [*messages[:last_human], note, *messages[last_human:]]
        if len(messages) != len(request.messages) or block:
            request = request.override(messages=messages)
        return await handler(request)
