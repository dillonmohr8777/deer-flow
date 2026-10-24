"""Host-bound, run-local access to an assigned client's selected project."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from deerflow.runtime.context_keys import CLIENT_PROJECT_ACCESS_CONTEXT_KEY, PROJECT_CONTEXT_KEY


@dataclass(frozen=True)
class ClientProjectReadAccess:
    project_id: str
    client_id: str
    authorize: Callable[[], Awaitable[None]] = field(repr=False)


def matching_client_project_access(context: Mapping) -> ClientProjectReadAccess | None:
    access = context.get(CLIENT_PROJECT_ACCESS_CONTEXT_KEY)
    project = context.get(PROJECT_CONTEXT_KEY)
    if isinstance(access, ClientProjectReadAccess) and isinstance(project, Mapping) and project.get("project_id") == access.project_id and project.get("client_id") == access.client_id:
        return access
    return None
