"""Authorize and attach one validated receipt using the existing thread fence."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.gateway.wsl_bridge import MAX_MESSAGE_BYTES, RECEIPT_FIELDS, BridgeError, compact_json


def _attachment_path(store, job_id, thread_id, user_id):
    from app.gateway.path_utils import resolve_outputs_confined_path
    from deerflow.config.paths import get_paths

    resolved = resolve_outputs_confined_path(thread_id, store.artifact_path(job_id), user_id=user_id)
    expected = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id).absolute() / f"wsl-diagnostic-{job_id}.json"
    if resolved != expected:
        raise BridgeError("Diagnostic output path contains a filesystem link")
    return expected


def _attach_fixed_file(path: Path, content: bytes, check_ownership: Callable[[], None] | None = None) -> None:
    """Pin output ancestors and link a flushed temporary file without overwrite."""
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.link not in os.supports_dir_fd:
        raise BridgeError("Secure diagnostic attachment is unavailable", 503)
    if check_ownership is not None:
        check_ownership()
    import secrets

    handles = []
    temporary_created = False
    temporary = ".wsl-receipt-" + secrets.token_hex(16)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        handles.append(os.open(path.anchor, flags))
        for component in path.parts[1:-1]:
            try:
                os.mkdir(component, 0o700, dir_fd=handles[-1])
            except FileExistsError:
                pass
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
        parent = handles[-1]
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        temporary_created = True
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            if check_ownership is not None:
                check_ownership()
            os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.fsync(parent)
        except FileExistsError:
            existing = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(existing, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode) or source.read(MAX_MESSAGE_BYTES + 1) != content:
                    raise BridgeError("Diagnostic artifact conflicts with existing output")
    except OSError:
        raise BridgeError("Diagnostic artifact write is held", 503) from None
    finally:
        if temporary_created:
            try:
                os.unlink(temporary, dir_fd=handles[-1])
            except FileNotFoundError:
                pass
        for handle in reversed(handles):
            os.close(handle)


async def attach_receipt(store, job_id, request):
    from app.gateway.deps import get_run_manager, get_thread_store
    from deerflow.runtime import ConflictError, RunManager, ThreadOperationKind
    from deerflow.utils.file_io import await_drained

    record = await asyncio.to_thread(store.read, job_id)
    if record["receipt"] is None or record["state"] not in {"done", "failed"}:
        return store._view(record)
    _, organization_id, actor_user_id, thread_id, _ = record["binding"]
    auth = request.state.auth
    if (auth.organization_id, auth.actor_user_id, auth.storage_user_id) != (organization_id, actor_user_id, record["storage_user_id"]):
        raise BridgeError("Diagnostic request not found", 404)
    thread_store = get_thread_store(request)
    if not await thread_store.check_access(thread_id, record["storage_user_id"], require_existing=True):
        raise BridgeError("Diagnostic origin thread is unavailable", 404)
    if record["attached"]:
        return store._view(record)
    run_manager = get_run_manager(request)
    caller = asyncio.current_task()
    try:
        async with run_manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.artifact_write, user_id=record["storage_user_id"]) as reservation:

            def check_ownership():
                deadline = RunManager._parse_lease_deadline(reservation.lease_expires_at)
                if caller.cancelling() or reservation.ownership_lost or reservation.abort_event.is_set() or (run_manager.heartbeat_enabled and (deadline is None or deadline <= datetime.now(UTC))):
                    raise ConflictError("Diagnostic attachment reservation is no longer owned")

            if not await thread_store.check_access(thread_id, record["storage_user_id"], require_existing=True):
                raise BridgeError("Diagnostic origin thread is unavailable", 404)
            path = await asyncio.to_thread(_attachment_path, store, job_id, thread_id, record["storage_user_id"])
            content = (compact_json({field: record["receipt"][field] for field in RECEIPT_FIELDS}) + "\n").encode()

            def write_and_mark():
                _attach_fixed_file(path, content, check_ownership)
                return store.mark_attached(job_id, record["receipt_sha256"], check_ownership=check_ownership)

            # Keep renewal and the reservation alive until all worker I/O drains.
            return await await_drained(asyncio.to_thread(write_and_mark))
    except ConflictError:
        raise BridgeError("Origin thread is busy; receipt remains durable", 409) from None


@asynccontextmanager
async def _local_request(record):
    """Open existing persistence only: no migrations, recovery or service startup."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.authz import AuthContext
    from deerflow.config import get_app_config
    from deerflow.persistence.organizations.resolution import active_organization_for_user, storage_user_id_for_organization
    from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.runtime import RunManager
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context
    from deerflow.utils.file_io import await_drained

    config = await asyncio.to_thread(get_app_config)
    database = config.database
    if database.backend not in {"sqlite", "postgres"} or (database.backend == "sqlite" and not Path(database.sqlite_path).is_file()):
        raise BridgeError("Existing durable gateway persistence is required", 503)
    options = {"connect_args": build_asyncpg_connect_args(database.postgres_schema)} if database.backend == "postgres" else {"connect_args": {"timeout": 5}}
    engine = create_async_engine(database.app_sqlalchemy_url, **options)
    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        _, organization_id, actor_user_id, _, _ = record["binding"]
        async with sf() as session:
            organization = await active_organization_for_user(session, actor_user_id, organization_id)
        if organization is None or storage_user_id_for_organization(organization, actor_user_id) != record["storage_user_id"]:
            raise BridgeError("Diagnostic origin authorization is unavailable", 403)
        user = SimpleNamespace(id=actor_user_id)
        auth = AuthContext(user=user, organization_id=organization_id, actor_user_id=actor_user_id, storage_user_id=record["storage_user_id"])
        user_token = set_current_user(user)
        storage_token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor_user_id, organization_id=organization_id, storage_user_id=record["storage_user_id"], role=organization.role))
        run_manager = RunManager(store=RunRepository(sf), run_ownership_config=config.run_ownership, run_config=getattr(config, "run", None))
        try:
            await run_manager.start_heartbeat(reconcile_orphans=False)
            yield SimpleNamespace(
                state=SimpleNamespace(auth=auth),
                app=SimpleNamespace(state=SimpleNamespace(thread_store=ThreadMetaRepository(sf), run_manager=run_manager)),
            )
        finally:
            try:
                await await_drained(run_manager.stop_heartbeat())
            finally:
                reset_storage_context(storage_token)
                reset_current_user(user_token)
    finally:
        await await_drained(engine.dispose())


async def ingest_local_receipt(store, job_id, receipt):
    """The operator CLI and privileged HTTP route share the exact same ingest."""
    record = await asyncio.to_thread(store.read, job_id)
    try:
        async with _local_request(record) as request:
            from app.gateway.deps import get_thread_store

            if not await get_thread_store(request).check_access(record["binding"][3], record["storage_user_id"], require_existing=True):
                raise BridgeError("Diagnostic origin thread is unavailable", 404)
            await asyncio.to_thread(store.ingest, job_id, receipt)
            return await attach_receipt(store, job_id, request)
    except BridgeError:
        raise
    except Exception:
        raise BridgeError("Diagnostic attachment requires reconciliation", 503) from None
