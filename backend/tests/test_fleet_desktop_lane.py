"""Desktop lane: roster-gated submit, claim refused until approved, idempotent resubmit."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.gateway.routers import fleet_work
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.roster_config import RosterConfig
from deerflow.persistence.engine import get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository

ROSTER = RosterConfig(users={"UAM1": {"role": "am", "clients": ["client-a"]}, "UADMIN": {"role": "admin"}})


def _body(**overrides):
    base = dict(thread_id="t", title="Desktop job", lane="desktop", data_class="private", items=[{"key": "k1", "prompt": "Summarize the folder"}], submission_key="s1", client_id="client-a", requester="UAM1")
    return fleet_work.FleetBatchSubmit(**{**base, **overrides})


def _request(repo, roster=ROSTER):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo, subagent_batches_config=None, roster_config=roster)),
        state=SimpleNamespace(user=SimpleNamespace(id="owner-1"), organization_id="org-1", storage_user_id="owner-1"),
    )


async def _real_repo(tmp_path) -> SubagentBatchRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    return SubagentBatchRepository(get_session_factory())


def test_desktop_requires_client_and_requester_and_no_project() -> None:
    with pytest.raises(ValidationError):
        _body(requester=None)
    with pytest.raises(ValidationError):
        _body(client_id=None)
    with pytest.raises(ValidationError):
        fleet_work.FleetBatchSubmit(thread_id="t", title="T", lane="haiku", data_class="public", items=[{"key": "k", "prompt": "p"}], submission_key="s", requester="UAM1")


@pytest.mark.asyncio
async def test_submit_stores_requester_client_pending_and_single_attempt(monkeypatch) -> None:
    repo = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "fleet-batch-1"}))
    monkeypatch.setattr(fleet_work, "get_current_user", AsyncMock(return_value="owner-1"))

    await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo), body=_body())

    kwargs = repo.create_batch.await_args.kwargs
    assert kwargs["max_attempts"] == 1
    spec = kwargs["execution_spec"]
    assert (spec["lane"], spec["data_class"], spec["client_id"], spec["requester"], spec["approval_state"], spec["executor"]) == ("desktop", "private", "client-a", "UAM1", "pending", "fleet")


@pytest.mark.asyncio
async def test_submit_refused_for_unrostered_requester_or_other_clients_and_retries(monkeypatch) -> None:
    repo = SimpleNamespace(create_batch=AsyncMock())
    monkeypatch.setattr(fleet_work, "get_current_user", AsyncMock(return_value="owner-1"))
    for body, roster in ((_body(requester="UNOBODY"), ROSTER), (_body(client_id="client-b"), ROSTER), (_body(), RosterConfig())):
        with pytest.raises(HTTPException) as denied:
            await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo, roster), body=body)
        assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as retries:
        await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo), body=_body(max_attempts=2))
    assert retries.value.status_code == 422
    repo.create_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_refused_while_pending_then_allowed_after_approve(tmp_path) -> None:
    repo = await _real_repo(tmp_path)
    spec = {"executor": "fleet", "lane": "desktop", "data_class": "private", "client_id": "client-a", "requester": "UAM1", "approval_state": "pending"}
    created = await repo.create_batch(
        batch_id="b1", user_id="owner-1", thread_id="thread-1", run_id=None, tool_call_id=None, submission_key="b1", title="b1", subagent_type="fleet-desktop",
        items=[{"key": "k1", "prompt": "Do it"}], max_live_items=5, max_running_items=1, max_attempts=1, execution_spec=spec,
    )  # fmt: skip
    now = datetime.now(UTC)
    claim = dict(lease_owner="mac:desktop", lease_seconds=60, limit=5, executor="fleet", lanes={"desktop"})

    assert await repo.claim_items(now=now, **claim) == []
    assert await repo.approve_fleet_batch("missing", approver_id="UADMIN", now=now) is None

    approved = await repo.approve_fleet_batch(created["id"], approver_id="admin-1", now=now)
    assert approved["approval_state"] == "approved"
    assert (await repo.approve_fleet_batch(created["id"], approver_id="someone-else", now=now))["approved_by"] == "admin-1"  # idempotent

    items = await repo.claim_items(now=now, **claim)
    assert len(items) == 1
    view = fleet_work.claimed_view(items[0], lease_expires_at="x")
    assert (view["lane"], view["client_id"], view["requester"], view["approval_state"], view["max_attempts"]) == ("desktop", "client-a", "UAM1", "approved", 1)


@pytest.mark.asyncio
async def test_resubmit_is_idempotent_on_submission_key(tmp_path, monkeypatch) -> None:
    repo = await _real_repo(tmp_path)
    monkeypatch.setattr(fleet_work, "get_current_user", AsyncMock(return_value="owner-1"))
    monkeypatch.setattr(repo, "create_batch", _create_with_thread(repo))
    first = await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo), body=_body())
    second = await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo), body=_body())
    assert first["id"] == second["id"]
    other = await fleet_work.submit_fleet_batch.__wrapped__(request=_request(repo), body=_body(submission_key="s2"))
    assert other["id"] != first["id"]


def _create_with_thread(repo):
    """Seed the owning thread row create_batch requires, then delegate to the real method."""
    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    real = SubagentBatchRepository.create_batch
    seeded = False

    async def create(**kwargs):
        nonlocal seeded
        if not seeded:
            async with get_session_factory()() as session:
                session.add(ThreadMetaRow(thread_id=kwargs["thread_id"], user_id=kwargs["user_id"], organization_id=None))
                await session.commit()
            seeded = True
        return await real(repo, **kwargs)

    return create
