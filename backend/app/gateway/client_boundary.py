"""Default-deny route boundary for the ``client`` system role.

A client is an external customer. All they get is chat with MomoBot Max, so
instead of denying the internal surfaces one by one (Gateway permissions only
exist for some of them, and a new route would be open by default) this module
lists the few routes a client may reach and ``AuthMiddleware`` answers 403 to
everything else. It is the same shape as the PAT policy in ``auth/pat.py``.

The table is independent of ``authorization.*`` config: it holds even when RBAC
is disabled or the role block is missing. RBAC still decides *within* the
allowed routes (models, tools, skills), and ``tests/test_client_route_boundary.py``
pins the exact list of registered routes this table admits.

When the client chat needs a new endpoint, add it here deliberately.
"""

from __future__ import annotations

import re

from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME

CLIENT_ROLE = "client"

_ID = r"[^/]+"
_GET = frozenset({"GET"})
_POST = frozenset({"POST"})

_RULES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = tuple(
    (methods, re.compile(pattern))
    for methods, pattern in (
        # Identity, account security, preferences, feature flags, model list,
        # the MomoBot kit behind "About" and "MomoBot Agents".
        (_GET, r"^/api/v1/auth/me$"),
        (_POST, r"^/api/v1/auth/(change-password|mfa/enroll/start|mfa/enroll/confirm|mfa/disable)$"),
        (frozenset({"GET", "PATCH"}), r"^/api/v1/auth/preferences$"),
        (_GET, r"^/api/features$"),
        (_GET, rf"^/api/models(/{_ID})?$"),
        (_GET, r"^/api/momobot-brand/(kit|about|assets/.+)$"),
        (_GET, r"^/api/suggestions/config$"),
        # The agents API, read-only. The router narrows it to MomoBot Max.
        (_GET, r"^/api/agents$"),
        (_GET, rf"^/api/agents/{MOMOBOT_MAX_NAME}$"),
        # Chat: threads, runs, files, follow-ups, feedback.
        (_POST, r"^/api/threads$"),
        (_POST, r"^/api/threads/search$"),
        (frozenset({"GET", "PATCH", "DELETE"}), rf"^/api/threads/{_ID}$"),
        (frozenset({"GET", "PUT", "DELETE"}), rf"^/api/threads/{_ID}/goal$"),
        (frozenset({"GET", "POST"}), rf"^/api/threads/{_ID}/state$"),
        (_POST, rf"^/api/threads/{_ID}/(compact|history|branches)$"),
        (_GET, rf"^/api/threads/{_ID}/(token-usage|messages|messages/page)$"),
        (frozenset({"GET", "POST"}), rf"^/api/threads/{_ID}/runs$"),
        (_POST, rf"^/api/threads/{_ID}/runs/(stream|wait|regenerate/prepare|edit-regenerate/prepare)$"),
        (_GET, rf"^/api/threads/{_ID}/runs/(?!stream$|wait$|regenerate$|edit-regenerate$){_ID}$"),
        (_POST, rf"^/api/threads/{_ID}/runs/{_ID}/cancel$"),
        (_GET, rf"^/api/threads/{_ID}/runs/{_ID}/(join|messages|events|workspace-changes)$"),
        (frozenset({"GET", "POST"}), rf"^/api/threads/{_ID}/runs/{_ID}/(artifacts/archive|stream)$"),
        (frozenset({"GET", "POST", "PUT", "DELETE"}), rf"^/api/threads/{_ID}/runs/{_ID}/feedback(/{_ID})?$"),
        (_POST, r"^/api/runs/(stream|wait)$"),
        (_GET, rf"^/api/runs/{_ID}/(messages|feedback)$"),
        (_POST, rf"^/api/threads/{_ID}/uploads$"),
        (_GET, rf"^/api/threads/{_ID}/uploads/(limits|list)$"),
        (frozenset({"DELETE"}), rf"^/api/threads/{_ID}/uploads/{_ID}$"),
        (_GET, rf"^/api/threads/{_ID}/artifacts/.+$"),
        (_POST, rf"^/api/threads/{_ID}/suggestions$"),
    )
)


def is_client_allowed_route(method: str, path: str) -> bool:
    """Whether a ``client`` may call *method* *path*. Trailing slashes are ignored."""
    normalized = path.rstrip("/") or "/"
    return any(method.upper() in methods and pattern.match(normalized) for methods, pattern in _RULES)
