"""In-memory ThreadMetaStore backed by LangGraph BaseStore.

Used when database.backend=memory. Delegates to the LangGraph Store's
``("threads",)`` namespace — the same namespace used by the Gateway
router for thread records.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.store.base import BaseStore

from deerflow.persistence.json_compat import json_value_matches
from deerflow.persistence.thread_meta.base import (
    PROJECT_FILTER_UNSET,
    THREAD_ARCHIVED_METADATA_KEY,
    THREAD_PINNED_METADATA_KEY,
    THREAD_UPLOAD_RESERVATION_METADATA_KEY,
    ThreadMetaStore,
    ThreadOwnershipConflictError,
    _ProjectFilterUnset,
    has_unowned_thread_data,
    thread_metadata,
)
from deerflow.persistence.thread_meta.sql import _own_private_legacy, _private_actor_storage
from deerflow.runtime.keyed_lock import AsyncKeyedLockTable
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso, now_iso

THREADS_NS: tuple[str, ...] = ("threads",)
SEARCH_PAGE_SIZE = 500


async def _client_actor_id():
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta.sql import _client_actor
    from deerflow.runtime.user_context import get_current_user, get_effective_actor_user_id

    if getattr(get_current_user(), "system_role", None) == "client":
        return get_effective_actor_user_id()
    factory = get_session_factory()
    if factory is None:
        return None
    async with factory() as session:
        return await _client_actor(session)


class MemoryThreadMetaStore(ThreadMetaStore):
    def __init__(self, store: BaseStore) -> None:
        self._store = store
        self._thread_locks = AsyncKeyedLockTable[str]()

    async def _get_owned_record(
        self,
        thread_id: str,
        user_id: str | None | _AutoSentinel,
        method_name: str,
    ) -> dict | None:
        """Fetch a record and verify ownership. Returns a mutable copy, or None."""
        resolved = resolve_user_id(user_id, method_name=method_name)
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return None
        record = dict(item.value)
        if resolved is not None and record.get("user_id") != resolved:
            return None
        client_actor = await _client_actor_id()
        if client_actor is not None and record.get("client_actor_id") != client_actor and not _own_private_legacy(client_actor, record.get("user_id"), record.get("client_actor_id")):
            return None
        return record

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
        preserve_existing: bool = False,
        finalize_upload: bool = False,
    ) -> dict:
        # Memory mode has no projects backend in Phase 1. Fail closed exactly
        # like the SQL store does for a missing/foreign/archived project: a
        # create carrying ``project_id`` raises ``ProjectNotAssignableError``
        # (the router maps it to 404) instead of silently persisting an
        # unassigned thread that a run would then proceed under. Mirrors
        # ``set_project`` below, which already reports rejection.
        if project_id is not None:
            from deerflow.persistence.projects import ProjectNotAssignableError

            raise ProjectNotAssignableError(project_id)
        resolved_user_id = resolve_user_id(user_id, method_name="MemoryThreadMetaStore.create")
        async with self._thread_locks.hold(thread_id):
            existing = await self._store.aget(THREADS_NS, thread_id)
            if existing is not None and resolved_user_id is not None and existing.value.get("user_id") != resolved_user_id:
                raise ThreadOwnershipConflictError(thread_id)
            client_actor = await _client_actor_id()
            if existing is not None and client_actor is not None and existing.value.get("client_actor_id") != client_actor and not _own_private_legacy(client_actor, existing.value.get("user_id"), existing.value.get("client_actor_id")):
                raise ThreadOwnershipConflictError(thread_id)
            if existing is not None and preserve_existing:
                if existing.value.get("user_id") is None:
                    raise ThreadOwnershipConflictError(thread_id)
                return self._public_record(existing.value)
            if existing is None and await has_unowned_thread_data(thread_id, resolved_user_id):
                raise ThreadOwnershipConflictError(thread_id)
            now = now_iso()
            incarnation = (existing.value.get("incarnation") if existing is not None else None) or uuid.uuid4().hex
            clean_metadata = thread_metadata(metadata)
            if preserve_existing:
                clean_metadata[THREAD_UPLOAD_RESERVATION_METADATA_KEY] = incarnation
            finalizing = existing is not None and existing.value.get("incarnation") is not None and (existing.value.get("metadata") or {}).get(THREAD_UPLOAD_RESERVATION_METADATA_KEY) == existing.value["incarnation"]
            if existing is not None and finalize_upload and not finalizing:
                if existing.value.get("user_id") is None:
                    raise ThreadOwnershipConflictError(thread_id)
                return self._public_record(existing.value)
            finalizing = finalizing and finalize_upload
            record: dict[str, Any] = {
                "thread_id": thread_id,
                "client_actor_id": existing.value.get("client_actor_id") if finalizing else client_actor,
                "incarnation": incarnation,
                "assistant_id": assistant_id,
                "user_id": existing.value.get("user_id") if finalizing else resolved_user_id,
                "display_name": existing.value.get("display_name") if finalizing and display_name is None else display_name,
                "status": existing.value.get("status", "idle") if finalizing else "idle",
                "metadata": clean_metadata,
                "values": existing.value.get("values", {}) if finalizing else {},
                "created_at": existing.value.get("created_at", now) if finalizing else now,
                "updated_at": now,
            }
            await self._store.aput(THREADS_NS, thread_id, record)
            return self._public_record(record)

    async def claim_unowned(self, thread_id: str, owner: str) -> bool:
        if await _client_actor_id() is not None:
            return False
        async with self._thread_locks.hold(thread_id):
            item = await self._store.aget(THREADS_NS, thread_id)
            if item is None or item.value.get("user_id") is not None:
                return False
            record = dict(item.value)
            record["user_id"] = owner
            await self._store.aput(THREADS_NS, thread_id, record)
            return True

    async def set_project(self, thread_id: str, project_id: str | None, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        # Memory mode has no projects backend in Phase 1: membership moves
        # are unsupported and always report rejection.
        return False

    async def get(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.get")
        return self._public_record(record) if record is not None else None

    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        archived: bool | None = None,
        project_id: str | None | _ProjectFilterUnset = PROJECT_FILTER_UNSET,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads by materializing matches, then sorting in Python.

        The memory backend loads all matching rows in chunks before slicing so
        it can mirror SQL's pinned-first ordering. Use the SQL store for
        scalable paginated I/O.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="MemoryThreadMetaStore.search")
        if not isinstance(project_id, _ProjectFilterUnset) and project_id is not None:
            # Memory mode has no projects backend: no thread can be a member.
            return []
        filter_dict: dict[str, Any] = {}
        client_actor = await _client_actor_id()
        if client_actor is not None and not _private_actor_storage(client_actor):
            filter_dict["client_actor_id"] = client_actor
        if status:
            filter_dict["status"] = status
        if resolved_user_id is not None:
            filter_dict["user_id"] = resolved_user_id

        items = []
        search_offset = 0
        while True:
            page = await self._store.asearch(
                THREADS_NS,
                filter=filter_dict or None,
                limit=SEARCH_PAGE_SIZE,
                offset=search_offset,
            )
            if not page:
                break
            items.extend(page)
            if len(page) < SEARCH_PAGE_SIZE:
                break
            search_offset += len(page)

        records = [self._item_to_dict(item) for item in items]
        if client_actor is not None:
            records = [record for record in records if record.get("client_actor_id") == client_actor or _own_private_legacy(client_actor, record.get("user_id"), record.get("client_actor_id"))]
        if metadata:
            records = [record for record in records if isinstance(record.get("metadata"), dict) and all(json_value_matches(record["metadata"], key, value) for key, value in metadata.items())]
        if archived is not None:
            records = [record for record in records if ((record.get("metadata") or {}).get(THREAD_ARCHIVED_METADATA_KEY) is True) == archived]
        records.sort(key=self._sort_key, reverse=True)
        return records[offset : offset + limit]

    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return not require_existing and not await has_unowned_thread_data(thread_id, user_id)
        # Ownerless legacy records fail closed for every caller, as in the SQL store.
        record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.check_access")
        return record is not None and record.get("user_id") is not None

    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        remove_metadata_keys: tuple[str, ...] = (),
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_display_name")
            if record is None:
                return
            record["display_name"] = display_name
            metadata = dict(record.get("metadata") or {})
            for key in remove_metadata_keys:
                metadata.pop(key, None)
            record["metadata"] = metadata
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_status(self, thread_id: str, status: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_status")
            if record is None:
                return
            record["status"] = status
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_metadata(self, thread_id: str, metadata: dict, *, touch: bool = True, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_metadata")
            if record is None:
                return
            merged = dict(record.get("metadata") or {})
            merged.update(thread_metadata(metadata))
            record["metadata"] = merged
            if touch:
                record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_owner(self, thread_id: str, owner_user_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_owner")
            if record is None:
                return
            record["user_id"] = owner_user_id
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def delete(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.delete")
            if record is None:
                return
            await self._store.adelete(THREADS_NS, thread_id)

    @staticmethod
    def _public_record(record: dict) -> dict:
        result = dict(record)
        result["upload_reserved"] = record.get("incarnation") is not None and (record.get("metadata") or {}).get(THREAD_UPLOAD_RESERVATION_METADATA_KEY) == record["incarnation"]
        result["metadata"] = thread_metadata(record.get("metadata"))
        return result

    @staticmethod
    def _item_to_dict(item) -> dict[str, Any]:
        """Convert a Store SearchItem to the dict format expected by callers."""
        val = item.value
        return {
            "thread_id": item.key,
            "incarnation": val.get("incarnation"),
            "assistant_id": val.get("assistant_id"),
            "user_id": val.get("user_id"),
            "display_name": val.get("display_name"),
            "status": val.get("status", "idle"),
            "metadata": thread_metadata(val.get("metadata")),
            # ``coerce_iso`` heals legacy unix-second values written by
            # earlier Gateway versions that called ``str(time.time())``.
            "created_at": coerce_iso(val.get("created_at", "")),
            "updated_at": coerce_iso(val.get("updated_at", "")),
        }

    @staticmethod
    def _sort_key(record: dict[str, Any]) -> tuple[bool, str, str]:
        metadata = record.get("metadata")
        pinned = isinstance(metadata, dict) and metadata.get(THREAD_PINNED_METADATA_KEY) is True
        return (pinned, str(record.get("updated_at") or ""), str(record.get("thread_id") or ""))
