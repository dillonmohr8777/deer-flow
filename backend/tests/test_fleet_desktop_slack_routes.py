"""Fleet-work routes the Slack desktop commands rely on: reject and slack_origin."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.routers import fleet_work
from deerflow.config.roster_config import RosterConfig

ROSTER = RosterConfig(users={"UAM1": {"role": "am", "clients": ["client-a"]}})


@pytest.mark.asyncio
async def test_reject_route_is_admin_only_and_maps_states(monkeypatch) -> None:
    repo = SimpleNamespace(reject_fleet_batch=AsyncMock(return_value={"approval_state": "rejected"}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo)))
    monkeypatch.setattr(fleet_work, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="u1")))
    monkeypatch.setattr(fleet_work, "_is_active_org_admin", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as denied:
        await fleet_work.reject_desktop_batch.__wrapped__("ab12cd34", request)
    assert denied.value.status_code == 403
    repo.reject_fleet_batch.assert_not_awaited()

    monkeypatch.setattr(fleet_work, "_is_active_org_admin", AsyncMock(return_value=True))
    assert (await fleet_work.reject_desktop_batch.__wrapped__("ab12cd34", request))["approval_state"] == "rejected"
    for returned, code in ((None, 404), ({"approval_state": "approved"}, 409)):
        repo.reject_fleet_batch.return_value = returned
        with pytest.raises(HTTPException) as err:
            await fleet_work.reject_desktop_batch.__wrapped__("ab12cd34", request)
        assert err.value.status_code == code


@pytest.mark.asyncio
async def test_submit_stores_slack_origin_on_the_spec(monkeypatch) -> None:
    repo = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "fleet-batch-1"}))
    monkeypatch.setattr(fleet_work, "get_current_user", AsyncMock(return_value="owner-1"))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo, subagent_batches_config=None, roster_config=ROSTER)),
        state=SimpleNamespace(user=SimpleNamespace(id="owner-1"), organization_id="org-1", storage_user_id="owner-1"),
    )
    body = fleet_work.FleetBatchSubmit(
        thread_id="t", title="T", lane="desktop", data_class="private", items=[{"key": "k", "prompt": "p"}], submission_key="s", client_id="client-a", requester="UAM1", slack_origin={"channel": "CCLIENTA", "team": "T1"}
    )
    await fleet_work.submit_fleet_batch.__wrapped__(request=request, body=body)
    assert repo.create_batch.await_args.kwargs["execution_spec"]["slack_origin"] == {"channel": "CCLIENTA", "team": "T1"}
    with pytest.raises(ValueError):
        fleet_work.FleetBatchSubmit(thread_id="t", title="T", lane="haiku", data_class="public", items=[{"key": "k", "prompt": "p"}], submission_key="s", slack_origin={"channel": "C1"})
