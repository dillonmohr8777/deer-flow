"""M3 lane G: memory isolation across organizations.

Owned files exercised here: app/gateway/routers/memory.py and
deerflow/agents/memory/backends/deermem/deermem/core/paths.py.

The memory router has no dedicated HTTP search endpoint (only get/export,
facts create/patch/delete, clear, reload, import); GET /api/memory and
/api/memory/export are the read/search surface tested below.

Covers, through the real memory router mounted behind the real
AuthMiddleware (real membership checks, real organization resolution):

- org A cannot read, write, delete, or clear org B's memory.
- a shared workspace's memory is shared by its active co-members and hidden
  from outsiders (fails closed, not empty-but-200).
- a revoked member loses access on their next request.

Plus two lower-level locks on the files this lane owns:

- deermem/core/paths.py: the legacy shared-bucket fallback (no user_id)
  only fires when a caller explicitly opts out of strict_user_scope; the
  deer-flow factory (agents/memory/manager.py, s09b) forces strict_user_scope
  on production's shared manager, so this path stays unreachable from
  request code without an explicit override.
- routers/memory.py: _resolve_memory_user_id always resolves a concrete,
  organization-correct storage principal, for every fixture organization.

And one documented gap (not this lane's to fix): the internal owner-header
override in _resolve_memory_user_id (mirroring AuthMiddleware's own
resolution for internal callers) accepts any owner id with no delegation or
membership check. See the REQUIREMENT FOR LANE 0 note on the xfail test at
the bottom of this file.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import (  # noqa: F401 -- org_world is a fixture
    ORG_A,
    ORG_B,
    ORG_S,
    STORAGE_S,
    USER_A,
    USER_B,
    USER_C,
    acting_as,
    auth_headers,
    org_world,
)

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import memory
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.paths import memory_file_path
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import get_effective_user_id


@asynccontextmanager
async def _memory_client(monkeypatch, tmp_path):
    """A real DeerMem-backed manager plus the real AuthMiddleware, mounted at /api/memory*."""
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    monkeypatch.setattr(memory, "get_memory_manager", lambda: manager)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(memory.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _create_fact(client, actor, organization_id, content):
    response = await client.post(
        "/api/memory/facts",
        headers=auth_headers(actor, organization_id),
        json={"content": content, "category": "context", "confidence": 0.8},
    )
    assert response.status_code == 200, response.text
    matches = [fact["id"] for fact in response.json()["facts"] if fact["content"] == content]
    assert matches, f"created fact missing from its own response: {response.json()}"
    return matches[0]


async def _facts_by_id(client, actor, organization_id):
    response = await client.get("/api/memory", headers=auth_headers(actor, organization_id))
    assert response.status_code == 200, response.text
    return {fact["id"]: fact["content"] for fact in response.json()["facts"]}


# -- org A cannot read, write, or delete org B's memory ---------------------


@pytest.mark.asyncio
async def test_private_orgs_do_not_share_memory_facts(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        fact_a = await _create_fact(client, USER_A, ORG_A, "A's private preference")

        assert fact_a not in await _facts_by_id(client, USER_B, ORG_B)
        export_b = await client.get("/api/memory/export", headers=auth_headers(USER_B, ORG_B))
        assert export_b.status_code == 200
        assert export_b.json()["facts"] == []

        # A still sees its own fact.
        assert (await _facts_by_id(client, USER_A, ORG_A))[fact_a] == "A's private preference"


@pytest.mark.asyncio
async def test_org_b_cannot_delete_or_update_org_a_fact_by_guessing_id(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        fact_a = await _create_fact(client, USER_A, ORG_A, "A's fact to protect")

        delete_response = await client.delete(f"/api/memory/facts/{fact_a}", headers=auth_headers(USER_B, ORG_B))
        assert delete_response.status_code == 404

        patch_response = await client.patch(
            f"/api/memory/facts/{fact_a}",
            headers=auth_headers(USER_B, ORG_B),
            json={"content": "overwritten by B"},
        )
        assert patch_response.status_code == 404

        # A's fact survives both cross-org attempts, unmodified.
        assert (await _facts_by_id(client, USER_A, ORG_A))[fact_a] == "A's fact to protect"


@pytest.mark.asyncio
async def test_org_b_clear_does_not_touch_org_a_memory(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        fact_a = await _create_fact(client, USER_A, ORG_A, "A's fact survives B's clear")
        await _create_fact(client, USER_B, ORG_B, "B's own fact")

        clear_response = await client.delete("/api/memory", headers=auth_headers(USER_B, ORG_B))
        assert clear_response.status_code == 200
        assert clear_response.json()["facts"] == []

        assert fact_a in await _facts_by_id(client, USER_A, ORG_A)


# -- shared workspace S: shared by co-members, hidden from outsiders --------


@pytest.mark.asyncio
async def test_shared_workspace_memory_visible_to_comembers_hidden_from_outsiders(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        # a (owner) and c (admin) are both active members of shared workspace S.
        fact_s = await _create_fact(client, USER_A, ORG_S, "shared workspace context")
        assert fact_s in await _facts_by_id(client, USER_C, ORG_S)

        # b is not a member of S: selecting S must fail closed, never return data.
        outsider_response = await client.get("/api/memory", headers=auth_headers(USER_B, ORG_S))
        assert outsider_response.status_code == 403

        # S's shared fact must not leak into b's own private organization either.
        assert fact_s not in await _facts_by_id(client, USER_B, ORG_B)


@pytest.mark.asyncio
async def test_revoked_member_loses_memory_access(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        await _create_fact(client, USER_A, ORG_S, "shared before revocation")
        assert (await client.get("/api/memory", headers=auth_headers(USER_C, ORG_S))).status_code == 200

        async with org_world() as session, session.begin():
            member = await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_C})
            member.status = "revoked"

        revoked_response = await client.get("/api/memory", headers=auth_headers(USER_C, ORG_S))
        assert revoked_response.status_code == 403


# -- queued (debounced) writes keep their enqueue-time scope -----------------


def test_queued_write_scope_survives_org_switch():
    """DeerMem's debounce queue never re-resolves user_id at flush time; it
    stores exactly the value passed to add(). A write enqueued while acting
    in org A must stay attributed to org A even after the caller switches to
    a different organization before the debounce timer fires."""
    queue = MemoryUpdateQueue(DeerMemConfig(), MagicMock())
    with acting_as(USER_A):
        storage_before_switch = get_effective_user_id()
    with acting_as(USER_C, ORG_S):
        storage_after_switch = get_effective_user_id()
    assert storage_before_switch == USER_A
    assert storage_after_switch == STORAGE_S

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(queue, "_reset_timer", lambda: None)
        queue.add(thread_id="t1", messages=["note while in org A"], user_id=storage_before_switch)
        # The org switch happens here, between the two enqueue calls.
        queue.add(thread_id="t1", messages=["note while in org S"], user_id=storage_after_switch)

    assert [context.user_id for context in queue._items] == [USER_A, STORAGE_S]
    assert [context.messages for context in queue._items] == [["note while in org A"], ["note while in org S"]]


# -- paths.py: the shared fallback bucket stays unreachable from strict callers --


def test_deermem_shared_fallback_unreachable_when_strict_user_scope(tmp_path):
    """Locks the s09b fix (agents/memory/manager.py's get_memory_manager forces
    strict_user_scope=True for the shared production manager): a caller that
    reaches DeerMem storage with user_id=None fails loudly instead of silently
    landing on the legacy shared bucket."""
    strict_config = DeerMemConfig(storage_path=str(tmp_path), strict_user_scope=True)
    with pytest.raises(ValueError, match="user_id is required"):
        memory_file_path(strict_config, user_id=None)

    # deermem's own package default stays permissive (documented, for embedders
    # outside the deer-flow factory); the shared bucket only exists there.
    permissive_config = DeerMemConfig(storage_path=str(tmp_path))
    assert memory_file_path(permissive_config, user_id=None) == tmp_path / "memory.json"


# -- routers/memory.py: the resolver never hands the manager an empty scope --


class _FakeRequest:
    """Minimal stand-in for the bits _resolve_memory_user_id reads."""

    def __init__(self) -> None:
        self.state = SimpleNamespace(user=SimpleNamespace(system_role="user"))
        self.headers: dict[str, str] = {}


@pytest.mark.parametrize(
    ("actor", "organization_id", "expected_storage_user"),
    [
        (USER_A, ORG_A, USER_A),
        (USER_B, ORG_B, USER_B),
        (USER_A, ORG_S, STORAGE_S),
        (USER_C, ORG_S, STORAGE_S),
    ],
)
def test_router_resolves_concrete_storage_principal_per_organization(actor, organization_id, expected_storage_user):
    with acting_as(actor, organization_id):
        resolved = memory._resolve_memory_user_id(_FakeRequest())
    assert resolved == expected_storage_user


# -- REQUIREMENT FOR LANE 0 ---------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "REQUIREMENT FOR LANE 0 phase 2: a valid internal token plus "
        "X-DeerFlow-Owner-User-Id must require an active OrganizationDelegation "
        "for that owner (plan section 7, F1) before it is honored. Today "
        "AuthMiddleware (auth_middleware.py:185-187,268-269) stamps the raw "
        "header value as storage_user_id with no membership or delegation "
        "check, and routers/memory.py's own internal-owner branch "
        "(_resolve_memory_user_id, mirroring that same resolution) inherits "
        "the gap. Once lane 0 rejects an undelegated header-only call, delete "
        "this xfail."
    ),
)
@pytest.mark.asyncio
async def test_internal_owner_header_cannot_impersonate_another_org_without_delegation(org_world, tmp_path, monkeypatch):  # noqa: F811 (pytest fixture imported above)
    async with _memory_client(monkeypatch, tmp_path) as client:
        fact_b = await _create_fact(client, USER_B, ORG_B, "B's private fact")

        response = await client.get("/api/memory", headers=create_internal_auth_headers(owner_user_id=USER_B))
        facts = {fact["id"] for fact in response.json().get("facts", [])} if response.status_code == 200 else set()
        assert response.status_code == 403 and fact_b not in facts
