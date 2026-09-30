"""Domain logic for the CEO Desk (queue item e14), sibling to the
``app.gateway.routers.ceo_desk`` API -- the same split as ``deerflow.board``
next to its own router.
"""

from deerflow.ceo_desk.digest import DigestWindow, build_digest_window, generate_daily_digest

__all__ = [
    "DigestWindow",
    "build_digest_window",
    "generate_daily_digest",
]
