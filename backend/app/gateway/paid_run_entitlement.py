"""Bridge paid admissions to the existing integration-lane entitlement policy.

The verified 943fc338 base has no entitlement subsystem. Only that complete
absence permits a transparent fallback; partially installed or malformed policy
fails startup. On modern lanes the real authz decorator owns configuration,
organization lookup, missing/suspended grants and runtime failure semantics.
"""

from __future__ import annotations

import importlib.util
import inspect
from collections.abc import Callable
from typing import cast

from app.gateway import authz

_ABSENT = object()
_ENTITLEMENT_MODULES = (
    "deerflow.config.entitlement_config",
    "deerflow.authz.entitlements",
    "deerflow.persistence.entitlements",
)


def require_paid_run_entitlement[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Apply below ``require_permission`` so its trusted AuthContext exists first."""
    factory = getattr(authz, "require_entitlement", _ABSENT)
    if factory is _ABSENT:
        if any(importlib.util.find_spec(name) is not None for name in _ENTITLEMENT_MODULES):
            raise RuntimeError("An installed entitlement subsystem requires authz.require_entitlement")
        return func
    if not callable(factory):
        raise TypeError("authz.require_entitlement must be callable")
    decorator = factory("runs.create")
    if not callable(decorator):
        raise TypeError("The entitlement factory must return a decorator")
    gated = decorator(func)
    if not callable(gated) or not inspect.iscoroutinefunction(gated):
        raise TypeError("The entitlement decorator must return an async callable")
    return cast(Callable[P, T], gated)
