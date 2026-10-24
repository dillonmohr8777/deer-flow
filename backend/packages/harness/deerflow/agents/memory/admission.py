"""Admission to workspace memory shared by staff runs."""

from collections.abc import Mapping

from deerflow.runtime.user_context import get_current_user


def memory_access_allowed(runtime: object | None = None) -> bool:
    """Client accounts may neither recall nor contribute to shared memory.

    Gateway stamps ``user_role`` from the authenticated account before its
    embedded worker constructs Runtime.context; organization membership and
    request memory switches cannot grant access. The request user also covers
    calls made before that runtime exists.
    """
    if getattr(get_current_user(), "system_role", None) == "client":
        return False
    context = getattr(runtime, "context", None)
    return not isinstance(context, Mapping) or context.get("user_role") != "client"
