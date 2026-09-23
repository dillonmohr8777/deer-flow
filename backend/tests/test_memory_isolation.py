"""Pin the CURRENT verified behaviour of memory.json path resolution.

W-B3 audit (see backend/MEMORY-SCOPING-AUDIT-20260921.md) traced every reader
and writer of memory.json / the deermem buckets. Unlike USER.md before
7001a7b2, memory.json is ALREADY per-user: ``Paths.memory_file`` (the
process-global ``{base_dir}/memory.json`` property) has no production
caller — only ``Paths.user_memory_file(user_id)`` and deermem's own
``memory_file_path(config, user_id=...)`` are used on the write/read paths
reachable from the Gateway API, the memory middleware, and the memory tools.

These tests pin that verified-scoped state at the ``Paths`` layer and at
deermem's own ``memory_file_path`` resolver, so a future change that
reintroduces a process-global write path fails a test instead of shipping
silently. They document CURRENT (good) behaviour -- they are not a
regression test for a bug, because the audit found none to pin.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deerflow.config.paths import Paths

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem"))

from deermem.config import DeerMemConfig  # noqa: E402
from deermem.core.paths import memory_file_path  # noqa: E402


def _make_paths(tmp_path) -> Paths:
    return Paths(base_dir=tmp_path)


def test_two_users_get_different_memory_files(tmp_path):
    """Different users must resolve to different memory.json buckets."""
    paths = _make_paths(tmp_path)

    alice = paths.user_memory_file("alice")
    bob = paths.user_memory_file("bob")

    assert alice != bob
    assert alice == tmp_path / "users" / "alice" / "memory.json"
    assert bob == tmp_path / "users" / "bob" / "memory.json"


def test_per_user_memory_file_is_not_the_legacy_shared_file(tmp_path):
    """The per-user path must never collide with the process-global path.

    ``Paths.memory_file`` still exists (kept for the pre-migration on-disk
    layout documented at the top of paths.py) but has no production caller;
    this test only pins that the two paths remain distinct.
    """
    paths = _make_paths(tmp_path)

    assert paths.memory_file == tmp_path / "memory.json"
    assert paths.user_memory_file("alice") != paths.memory_file


def test_a_write_by_one_user_is_invisible_to_another(tmp_path):
    """The contamination scenario memory.json does NOT have, verified end to end."""
    paths = _make_paths(tmp_path)

    alice = paths.user_memory_file("alice")
    alice.parent.mkdir(parents=True, exist_ok=True)
    alice.write_text('{"facts": [{"content": "Alice only"}]}', encoding="utf-8")

    bob = paths.user_memory_file("bob")
    assert not bob.exists()
    assert not paths.memory_file.exists()


def test_user_agent_memory_file_is_scoped_by_both_user_and_agent(tmp_path):
    """Per-agent memory must be bucketed under the OWNING user, not shared globally."""
    paths = _make_paths(tmp_path)

    alice_agent = paths.user_agent_memory_file("alice", "code-reviewer")
    bob_agent = paths.user_agent_memory_file("bob", "code-reviewer")

    assert alice_agent != bob_agent
    assert alice_agent == tmp_path / "users" / "alice" / "agents" / "code-reviewer" / "memory.json"
    assert bob_agent == tmp_path / "users" / "bob" / "agents" / "code-reviewer" / "memory.json"
    # Also distinct from the legacy (unscoped) per-agent path.
    assert alice_agent != paths.agent_memory_file("code-reviewer")


def test_user_id_is_validated_not_interpolated(tmp_path):
    """Path traversal through the user id must not escape the bucket root.

    ``user_memory_file`` routes through ``user_dir()``, which runs
    ``_validate_user_id``.
    """
    paths = _make_paths(tmp_path)
    users_root = (tmp_path / "users").resolve()

    for candidate in ("../../etc", "..\\..\\windows", "a/../../b"):
        try:
            resolved = paths.user_memory_file(candidate).resolve()
        except Exception:
            continue  # rejecting outright is a valid answer
        assert users_root in resolved.parents, f"{candidate} escaped to {resolved}"


def test_deermem_memory_file_path_scopes_by_user_id(tmp_path):
    """deermem's own resolver (independent of deer-flow's Paths) is also scoped.

    This is the resolver actually invoked by MemoryManager/FileMemoryStorage
    on every read and write (deermem/core/storage.py::_get_memory_file_path).
    """
    config = DeerMemConfig(storage_path=str(tmp_path))

    alice = memory_file_path(config, user_id="alice")
    bob = memory_file_path(config, user_id="bob")

    assert alice == tmp_path / "users" / "alice" / "memory.json"
    assert bob == tmp_path / "users" / "bob" / "memory.json"
    assert alice != bob


def test_deermem_memory_file_path_user_id_none_falls_back_to_legacy_shared_path(tmp_path):
    """Documented CURRENT behaviour: omitting user_id resolves to the legacy
    shared root path, exactly the process-global shape USER.md had pre-fix.

    The audit found no production caller that omits user_id (every Gateway
    router, memory middleware, and memory tool call site resolves a concrete
    user_id via get_effective_user_id()/resolve_runtime_user_id() before
    calling into deermem). This test constructs a bare ``DeerMemConfig``
    directly (deermem's OWN default, unchanged by the W-B3 follow-up below):
    ``strict_user_scope`` defaults to False there so an embedder that
    imports deermem standalone, without the deer-flow factory, is not broken.
    The deer-flow factory (``manager.py::get_memory_manager``) now overrides
    this default to True at its own call site -- see
    ``test_factory_defaults_to_strict_user_scope`` below -- which is where
    the hardening this test motivated actually landed.
    """
    config = DeerMemConfig(storage_path=str(tmp_path))

    shared = memory_file_path(config, user_id=None)

    assert shared == tmp_path / "memory.json"


def test_factory_defaults_to_strict_user_scope(tmp_path):
    """W-B3 follow-up, item 2 (authorized): the deer-flow factory call site
    (manager.py::get_memory_manager) sets strict_user_scope=True by default,
    so a caller that reaches deermem storage with user_id=None now fails
    loudly instead of silently landing on the legacy shared bucket verified
    above. Re-verified before applying: every production call site found in
    the Part A audit (8 memory router endpoints, MemoryMiddleware,
    summarization_hook, 4 memory tools, lead_agent prompt injection, 7
    client.py accessors, the agent-delete cancel path) resolves a concrete
    user_id before reaching the manager, so this cannot break any of them.

    deermem's own ``DeerMemConfig.strict_user_scope`` default stays False
    (see the test above) -- only the factory's ``backend_config`` sets it,
    and only when the host config does not already set it explicitly.
    """
    from deerflow.agents.memory.manager import get_memory_manager, reset_memory_manager
    from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config

    orig_config = get_memory_config()
    try:
        set_memory_config(MemoryConfig(manager_class="deermem", backend_config={"storage_path": str(tmp_path)}))
        reset_memory_manager()
        manager = get_memory_manager()

        with pytest.raises(ValueError):
            manager.get_memory(user_id=None)

        # A concrete user_id is unaffected by the flip.
        result = manager.get_memory(user_id="alice")
        assert isinstance(result, dict)
    finally:
        set_memory_config(orig_config)
        reset_memory_manager()


def test_factory_honors_explicit_strict_user_scope_override(tmp_path):
    """An explicit host config value still wins over the factory default,
    matching the existing storage_path precedent in the same function.
    """
    from deerflow.agents.memory.manager import get_memory_manager, reset_memory_manager
    from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config

    orig_config = get_memory_config()
    try:
        set_memory_config(
            MemoryConfig(
                manager_class="deermem",
                backend_config={"storage_path": str(tmp_path), "strict_user_scope": False},
            )
        )
        reset_memory_manager()
        manager = get_memory_manager()

        # Explicit False was preserved: no raise for user_id=None.
        result = manager.get_memory(user_id=None)
        assert isinstance(result, dict)
    finally:
        set_memory_config(orig_config)
        reset_memory_manager()


if __name__ == "__main__":  # pragma: no cover
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for fn in (
            test_two_users_get_different_memory_files,
            test_per_user_memory_file_is_not_the_legacy_shared_file,
            test_a_write_by_one_user_is_invisible_to_another,
            test_user_agent_memory_file_is_scoped_by_both_user_and_agent,
            test_user_id_is_validated_not_interpolated,
            test_deermem_memory_file_path_scopes_by_user_id,
            test_deermem_memory_file_path_user_id_none_falls_back_to_legacy_shared_path,
        ):
            sub = Path(d) / fn.__name__
            sub.mkdir()
            fn(sub)
            print(f"  ok  {fn.__name__}")
    print("memory.json isolation: all checks pass")
