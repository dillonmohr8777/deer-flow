"""The CLI attachment must retain the real SQL thread-operation fence."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_wsl_bridge import receipt

from app.gateway import wsl_bridge_attachment as attachment
from app.gateway.wsl_bridge import BridgeError, BridgeStore
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime import ConflictError, RunManager, ThreadOperationKind


@asynccontextmanager
async def local_gateway(tmp_path, monkeypatch):
    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0)
    organization_id = private_organization_id("storage")
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: SimpleNamespace(database=database, run_ownership=ownership))
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", str(tmp_path.resolve()))
    monkeypatch.setattr(attachment, "_attachment_path", lambda *args: tmp_path / "receipt.json")
    engine = create_async_engine(database.app_sqlalchemy_url)
    try:
        tables = [model.__table__ for model in (OrganizationRow, OrganizationMemberRow, ThreadMetaRow, RunRow, RunChangeClockRow, UserRow, ClientAssignmentRow)]
        async with engine.begin() as connection:
            await connection.run_sync(lambda connection: Base.metadata.create_all(connection, tables=tables))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            session.add_all(
                [
                    OrganizationRow(id=organization_id, slug="org", name="Test organization", status="active", storage_user_id="storage"),
                    OrganizationMemberRow(organization_id=organization_id, user_id="actor", role="owner", status="active"),
                    ThreadMetaRow(thread_id="thread", user_id="storage", organization_id=organization_id),
                ]
            )
            await session.commit()
        repo = RunRepository(sf)
        peer = RunManager(store=repo, run_ownership_config=ownership, worker_id="peer")
        store = BridgeStore.from_environment()
        job = store.enqueue(organization_id=organization_id, actor_user_id="actor", storage_user_id="storage", thread_id="thread", request_id="request", argv=["/usr/bin/uname", "-s"], timeout=30)["job"]
        store.claim()
        yield SimpleNamespace(repo=repo, peer=peer, store=store, job=job, sf=sf, path=tmp_path / "receipt.json", organization_id=organization_id)
    finally:
        await engine.dispose()


def pause_writer(monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def write(path, content, check_ownership=lambda: None):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(15), "test did not release the filesystem writer"
        check_ownership()
        path.write_bytes(content)

    monkeypatch.setattr(attachment, "_attach_fixed_file", write)
    return started, release


@pytest.mark.asyncio
async def test_cli_attachment_survives_real_sql_peer_sweep_and_renews(tmp_path, monkeypatch):
    async with local_gateway(tmp_path, monkeypatch) as gateway:
        expired = datetime.now(UTC) - timedelta(seconds=60)
        async with gateway.sf() as session:
            session.add(RunRow(run_id="unrelated-orphan", thread_id="other", user_id="storage", organization_id=gateway.organization_id, status="running", owner_worker_id="gone", lease_expires_at=expired))
            await session.commit()
        started, release = pause_writer(monkeypatch)
        task = asyncio.create_task(attachment.ingest_local_receipt(gateway.store, gateway.job["id"], receipt(gateway.job)))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            rows = await gateway.repo.list_inflight()
            reservation = next(row for row in rows if row["thread_id"] == "thread")
            assert reservation["operation_kind"] == ThreadOperationKind.artifact_write
            assert (reservation["user_id"], reservation["organization_id"], reservation["thread_id"]) == ("storage", gateway.organization_id, "thread")
            recovered = await gateway.peer.reconcile_orphaned_inflight_runs(error="peer sweep")
            assert [row.run_id for row in recovered] == ["unrelated-orphan"]
            assert (await gateway.repo.get(reservation["run_id"], user_id="storage"))["status"] == "pending"
            async with gateway.sf() as session:
                session.add(RunRow(run_id="cli-must-not-recover", thread_id="other-2", status="running", lease_expires_at=expired))
                await session.commit()
            initial_deadline = datetime.fromisoformat(reservation["lease_expires_at"])
            await asyncio.sleep(max(0, (initial_deadline - datetime.now(UTC)).total_seconds()) + 0.1)
            current = await gateway.repo.get(reservation["run_id"], user_id="storage")
            assert current["status"] == "pending"
            assert datetime.fromisoformat(current["lease_expires_at"]) > initial_deadline
            assert (await gateway.repo.get("cli-must-not-recover", user_id=None))["status"] == "running"
            assert [row.run_id for row in await gateway.peer.reconcile_orphaned_inflight_runs(error="peer sweep")] == ["cli-must-not-recover"]
            for kind in (ThreadOperationKind.delete, ThreadOperationKind.artifact_write):
                with pytest.raises(ConflictError):
                    async with gateway.peer.reserve_thread_operation("thread", kind=kind, user_id="storage"):
                        pytest.fail("peer entered the live attachment reservation")
            with pytest.raises(ConflictError):
                await gateway.peer.create_or_reject("thread", user_id="storage", multitask_strategy="interrupt")
        finally:
            release.set()
            result = await asyncio.wait_for(task, timeout=3)
        assert result["attached"] is True
        assert gateway.path.is_file()
        assert await gateway.repo.list_inflight() == []


@pytest.mark.asyncio
async def test_cli_cancellation_drains_before_releasing_without_attaching(tmp_path, monkeypatch):
    async with local_gateway(tmp_path, monkeypatch) as gateway:
        started, release = pause_writer(monkeypatch)
        task = asyncio.create_task(attachment.ingest_local_receipt(gateway.store, gateway.job["id"], receipt(gateway.job)))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            task.cancel()
            await asyncio.sleep(0)
            assert task.done() is False
            reservation = (await gateway.repo.list_inflight())[0]
            assert await gateway.peer.reconcile_orphaned_inflight_runs(error="peer sweep") == []
            assert (await gateway.repo.get(reservation["run_id"], user_id="storage"))["status"] == "pending"
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        assert gateway.store.read(gateway.job["id"])["attached"] is False
        assert gateway.path.exists() is False
        assert await gateway.repo.list_inflight() == []
        assert not any(task.get_name() == "deerflow-run-lease-heartbeat" for task in asyncio.all_tasks() if not task.done())


@pytest.mark.asyncio
async def test_expired_cli_reservation_is_recoverable_and_writer_cannot_commit(tmp_path, monkeypatch):
    async with local_gateway(tmp_path, monkeypatch) as gateway:
        started, release = pause_writer(monkeypatch)
        record = gateway.store.read(gateway.job["id"])
        async with attachment._local_request(record) as request:
            gateway.store.ingest(gateway.job["id"], receipt(gateway.job))
            task = asyncio.create_task(attachment.attach_receipt(gateway.store, gateway.job["id"], request))
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                reservation = (await gateway.repo.list_inflight())[0]
                await request.app.state.run_manager.stop_heartbeat()
                deadline = datetime.fromisoformat(reservation["lease_expires_at"])
                await asyncio.sleep(max(0, (deadline - datetime.now(UTC)).total_seconds()) + 0.1)
                await gateway.peer.reconcile_orphaned_inflight_runs(error="expired owner")
                assert (await gateway.repo.get(reservation["run_id"], user_id="storage"))["status"] == "error"
            finally:
                release.set()
                with pytest.raises(BridgeError) as error:
                    await asyncio.wait_for(task, timeout=3)
                assert error.value.status_code == 409
        assert gateway.store.read(gateway.job["id"])["attached"] is False
        assert gateway.path.exists() is False
        assert await gateway.repo.list_inflight() == []


@pytest.mark.asyncio
async def test_blocked_spool_marker_rechecks_ownership_after_lock_wait(tmp_path, monkeypatch):
    async with local_gateway(tmp_path, monkeypatch) as gateway:
        started, release = pause_writer(monkeypatch)
        marking = asyncio.Event()
        loop = asyncio.get_running_loop()
        original_mark = gateway.store.mark_attached

        def mark(*args, **kwargs):
            loop.call_soon_threadsafe(marking.set)
            return original_mark(*args, **kwargs)

        monkeypatch.setattr(gateway.store, "mark_attached", mark)
        task = asyncio.create_task(attachment.ingest_local_receipt(gateway.store, gateway.job["id"], receipt(gateway.job)))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            with gateway.store._connect(write=True):
                release.set()
                await asyncio.wait_for(marking.wait(), timeout=3)
                task.cancel()
                await asyncio.sleep(0)
                assert task.done() is False
                assert len(await gateway.repo.list_inflight()) == 1
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        assert gateway.path.is_file()
        assert gateway.store.read(gateway.job["id"])["attached"] is False
        assert await gateway.repo.list_inflight() == []
