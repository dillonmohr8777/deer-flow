"""Operator-only offline factory; no public request grants or activation."""

from pathlib import Path

from deerflow.community.momentum_sdk.bridge import OfflineReviewer, WorkerSpec


def prepare_sdk_reviewer(*, enabled: bool = False, owner_id: str, thread_id: str, run_id: str, client_ids: set[str], canonical_root: Path, worker: WorkerSpec) -> OfflineReviewer | None:
    """Trusted host explicitly opts in and binds this capability into RunContext.

    Not called automatically by Gateway or exposed in HTTP models. A future
    activation path must authenticate identity/scope before constructing it.
    This factory authorizes synthetic local execution only, never paid calls.
    """
    if enabled is not True:
        return None
    if not client_ids or any(not isinstance(c, str) or not c or len(c) > 200 for c in client_ids):
        raise ValueError("Exact host-authorized client identifiers required")
    return OfflineReviewer(owner_id=owner_id, thread_id=thread_id, run_id=run_id, client_ids=frozenset(client_ids), canonical_root=canonical_root, worker=worker)
