"""SQL event writes stay visible in their workspace without crossing scopes."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_C, acting_as

from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.user_context import get_current_user, reset_current_user, set_current_user

pytest_plugins = ["org_isolation_fixtures"]


async def _write(store, method):
    event = {
        "thread_id": "scope-thread",
        "run_id": "scope-run",
        "event_type": "llm.ai.response",
        "category": "message",
        "content": {"id": "scope-message", "content": "Workspace response"},
    }
    if method == "put_batch":
        return (await store.put_batch([event]))[0]
    if method == "put_if_absent":
        row, created = await store.put_if_absent(**event)
        assert created
        return row
    return await store.put(**event)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
async def test_shared_event_visible_to_workspace_members_only(org_world, method):
    store = DbRunEventStore(org_world)
    with acting_as(USER_C, ORG_S):
        row = await _write(store, method)
        assert row["user_id"] == STORAGE_S
        assert len(await store.list_messages_by_run("scope-thread", "scope-run")) == 1

    with acting_as(USER_A, ORG_S):
        messages = await store.list_messages_by_run("scope-thread", "scope-run")
        assert messages[0]["content"]["content"] == "Workspace response"

    for actor in (USER_A, USER_C):
        with acting_as(actor):
            assert await store.list_messages_by_run("scope-thread", "scope-run") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
async def test_private_uuid_event_keeps_actor_scope(org_world, method):
    store = DbRunEventStore(org_world)
    actor = UUID("00000000-0000-0000-0000-000000000001")
    token = set_current_user(SimpleNamespace(id=actor))
    try:
        row = await _write(store, method)
        assert row["user_id"] == str(actor)
        assert len(await store.list_messages_by_run("scope-thread", "scope-run")) == 1
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
async def test_background_event_without_user_stays_unstamped(org_world, method):
    token = set_current_user(None)  # type: ignore[arg-type]
    try:
        assert get_current_user() is None
        store = DbRunEventStore(org_world)
        row = await _write(store, method)
        assert row["user_id"] is None
        assert len(await store.list_messages_by_run("scope-thread", "scope-run", user_id=None)) == 1
    finally:
        reset_current_user(token)
