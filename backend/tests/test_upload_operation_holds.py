"""An unfinished upload keeps admission even when its worker lease is uncertain."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from org_isolation_fixtures import USER_A, USER_B, acting_as, org_world_pooled  # noqa: F401
from sqlalchemy.exc import IntegrityError

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.runs.manager import CancelOutcome, ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus, ThreadOperationKind
from deerflow.runtime.runs.store.base import RunStore
from deerflow.runtime.runs.store.memory import MemoryRunStore

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_upload_hold_rejects_generic_retirement_and_releases_only_after_owner_drain(org_world_pooled, backend):  # noqa: F811
    store = RunRepository(org_world_pooled) if backend == "sql" else MemoryRunStore()
    operation, _ = await store.create_thread_operation_atomic(
        "held-upload", thread_id="held-thread", user_id=USER_A, owner_worker_id="original-worker", operation_kind="upload_write", lease_expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat()
    )
    before = deepcopy(operation)
    assert await store.update_status("held-upload", "error") is False
    assert await store.start_run("held-upload") is False
    assert await store.update_run_completion("held-upload", status="success") is False
    assert (await store.finalize_if_not_cancelled("held-upload", status="error")).finalized is False
    assert await store.claim_for_takeover("held-upload", grace_seconds=0, error="Expired") is False
    assert await store.list_inflight_with_expired_lease(grace_seconds=0) == []
    assert await store.list_inflight() == []
    for action in ("interrupt", "rollback"):
        assert await store.request_cancel("held-upload", action=action) is None
    await store.delete("held-upload", user_id=USER_A)
    await store.delete_thread_operation("held-upload", user_id=USER_A)
    assert await store.delete_by_thread("held-thread", user_id=USER_A) == 0
    with pytest.raises(ValueError):
        await store.put("held-upload", thread_id="held-thread", user_id=USER_A, status="success")
    with pytest.raises(ValueError):
        await store.put("fabricated-upload", thread_id="other-thread", user_id=USER_A, operation_kind="upload_write")
    for strategy in ("reject", "interrupt", "rollback"):
        for worker in ("original-worker", "peer-worker"):
            with pytest.raises((ConflictError, IntegrityError)):
                await store.create_thread_operation_atomic("replacement-" + strategy + worker, thread_id="held-thread", user_id=USER_A, owner_worker_id=worker, lease_expires_at=None, multitask_strategy=strategy)
    for user, worker in ((USER_B, "original-worker"), (None, "original-worker"), (USER_A, "peer-worker")):
        assert await store.release_upload_operation("held-upload", user_id=user, owner_worker_id=worker) is False
    assert await store.get("held-upload", user_id=USER_A) == before
    assert await store.release_upload_operation("held-upload", user_id=USER_A, owner_worker_id="original-worker") is True
    assert await store.get("held-upload", user_id=USER_A) is None
    replacement, _ = await store.create_thread_operation_atomic("after-drain", thread_id="held-thread", user_id=USER_A, owner_worker_id="peer-worker", lease_expires_at=None)
    assert replacement["operation_kind"] == "run"


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_upload_cannot_be_cancelled_or_started_by_local_or_peer_manager(org_world_pooled, backend):  # noqa: F811
    store = RunRepository(org_world_pooled) if backend == "sql" else MemoryRunStore()
    policy = RunOwnershipConfig(heartbeat_enabled=True)
    owner = RunManager(store=store, worker_id="original-worker", run_ownership_config=policy)
    peer = RunManager(store=store, worker_id="peer-worker", run_ownership_config=policy)
    with acting_as(USER_A):
        async with owner.reserve_thread_operation("managed-upload", kind=ThreadOperationKind.upload_write, user_id=USER_A) as record:
            before = deepcopy(await store.get(record.run_id, user_id=USER_A))
            for manager in (owner, peer):
                for action in ("interrupt", "rollback"):
                    assert await manager.cancel(record.run_id, action=action) == CancelOutcome.not_cancellable
            await owner.try_start(record.run_id)
            await owner.set_status(record.run_id, RunStatus.success)
            await owner.set_status_if_not_cancelled(record.run_id, RunStatus.error)
            assert record.status == RunStatus.pending
            assert await store.get(record.run_id, user_id=USER_A) == before
        assert await store.get(record.run_id, user_id=USER_A) is None


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_ordinary_artifact_operation_recovery_is_unchanged(org_world_pooled, backend):  # noqa: F811
    store = RunRepository(org_world_pooled) if backend == "sql" else MemoryRunStore()
    await store.create_thread_operation_atomic(
        "ordinary-write", thread_id="ordinary-thread", user_id=USER_A, owner_worker_id="original-worker", operation_kind="artifact_write", lease_expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat()
    )
    assert await store.release_upload_operation("ordinary-write", user_id=USER_A, owner_worker_id="original-worker") is False
    assert await store.claim_for_takeover("ordinary-write", grace_seconds=0, error="Expired") is True
    await store.delete_thread_operation("ordinary-write", user_id=USER_A)
    assert await store.get("ordinary-write", user_id=USER_A) is None


async def test_unsupported_store_does_not_fall_back_to_unqualified_upload_delete():
    assert await RunStore.release_upload_operation(object(), "held-upload", user_id=USER_A, owner_worker_id="original-worker") is False


async def test_unsupported_upload_store_is_rejected_before_admission():
    class LegacyStore(MemoryRunStore):
        release_upload_operation = RunStore.release_upload_operation

    store = LegacyStore()
    manager = RunManager(store=store)
    with pytest.raises(ConflictError):
        async with manager.reserve_thread_operation("unsupported-upload", kind=ThreadOperationKind.upload_write, user_id=USER_A):
            pytest.fail("Upload worker must not start on an unsupported store")
    assert store._runs == {}


@pytest.mark.parametrize("failure", ["unconfirmed", "error"])
async def test_unconfirmed_upload_release_preserves_durable_hold_and_clears_local_record(failure, caplog):
    class UnconfirmedStore(MemoryRunStore):
        async def release_upload_operation(self, run_id, *, user_id, owner_worker_id):
            if failure == "error":
                raise RuntimeError("Synthetic release unavailable")
            return False

    store = UnconfirmedStore()
    manager = RunManager(store=store, worker_id="original-worker")
    async with manager.reserve_thread_operation("uncertain-release", kind=ThreadOperationKind.upload_write, user_id=USER_A) as record:
        pass  # The file worker has drained, but its release cannot be confirmed.
    assert manager._runs == {} and manager._runs_by_thread == {}
    assert (await store.get(record.run_id, user_id=USER_A))["status"] == "pending"
    assert "verify durable state before repair" in caplog.text
    with pytest.raises(ConflictError):
        await manager.create_or_reject("uncertain-release", user_id=USER_A)


async def test_cancelled_unseen_upload_admission_can_release_only_its_own_token():
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="original-worker")
    record = await manager._admit_thread_operation("unseen-upload", operation_kind=ThreadOperationKind.upload_write, user_id=USER_A)
    await manager._close_cancelled_admission(record)
    assert await store.get(record.run_id, user_id=USER_A) is None
    assert manager._runs == {} and manager._runs_by_thread == {}
