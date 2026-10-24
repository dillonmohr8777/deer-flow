"""Missing-row data checks retain logical channel principals and legacy holds."""

import pytest
from langgraph.store.memory import InMemoryStore
from test_thread_meta_repo import repo as sql_repo  # noqa: F401

from deerflow.config.paths import Paths
from deerflow.persistence.thread_meta import ThreadOwnershipConflictError
from deerflow.persistence.thread_meta.base import has_unowned_thread_data
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["sql", "memory"])
@pytest.mark.parametrize("legacy_data", [False, True])
async def test_path_invalid_principal_keeps_metadata_access_and_legacy_hold(sql_repo, tmp_path, monkeypatch, backend, legacy_data):  # noqa: F811
    paths = Paths(tmp_path / "thread-data")
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    store = sql_repo if backend == "sql" else MemoryThreadMetaStore(InMemoryStore())
    owner = "feishu:owner-777"
    thread_id = "channel-principal-thread"
    assert await store.check_access(thread_id, owner, require_existing=True) is False
    if legacy_data:
        root = paths.thread_dir(thread_id)
        root.mkdir(parents=True)
        sentinel = root / "unknown.txt"
        sentinel.write_bytes(b"synthetic unknown-owner data")
        assert await store.check_access(thread_id, owner) is False
        with pytest.raises(ThreadOwnershipConflictError):
            await store.create(thread_id, user_id=owner)
        assert await store.get(thread_id, user_id=owner) is None
        assert sentinel.read_bytes() == b"synthetic unknown-owner data"
    else:
        assert await store.check_access(thread_id, owner) is True
        created = await store.create(thread_id, user_id=owner)
        assert created["user_id"] == owner
        assert await store.check_access(thread_id, owner, require_existing=True) is True


@pytest.mark.anyio
@pytest.mark.parametrize("thread_id", ["../invalid-thread", "invalid/thread"])
async def test_path_invalid_principal_does_not_hide_invalid_thread_id(tmp_path, monkeypatch, thread_id):
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(tmp_path / "thread-data"))
    with pytest.raises(ValueError, match="thread_id"):
        await has_unowned_thread_data(thread_id, "feishu:owner-777")
