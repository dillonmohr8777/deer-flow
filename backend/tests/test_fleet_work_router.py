"""Fleet work router: host-facing claim, lease and submit surface over batch items."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.app import create_app
from app.gateway.authz import Permissions
from app.gateway.routers import fleet_work
from deerflow.config.subagent_batches_config import SubagentBatchesConfig


def _request(repo, config=None):
    if not hasattr(repo, "owns_fleet_item_lease"):
        repo.owns_fleet_item_lease = AsyncMock(return_value=True)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo, subagent_batches_config=config)),
        state=SimpleNamespace(
            user=SimpleNamespace(id="owner-1", system_role="internal"),
            delegation_id="synthetic-delegation",
            storage_user_id="owner-1",
            organization_id="synthetic-org",
        ),
    )


def _claimed_item(**overrides):
    return {
        "id": "item-1",
        "batch_id": "batch-1",
        "item_key": "k-1",
        "attempt": 1,
        "prompt": "Summarize the public page",
        "acceptance_criteria": None,
        "batch": {"id": "batch-1", "max_attempts": 2, "execution_spec": {"executor": "fleet", "lane": "spark", "data_class": "public", "effort": "high", "max_tokens": 16000}},
        **overrides,
    }


def test_gateway_mounts_fleet_work_routes_and_permission() -> None:
    paths = {route.path for route in create_app().routes}
    assert {"/api/fleet/work/batches", "/api/fleet/work/claim", "/api/fleet/work/{item_id}/renew", "/api/fleet/work/{item_id}/finalize", "/api/fleet/work/{item_id}/release"} <= paths
    assert Permissions.FLEET_WORK == "fleet:work"


@pytest.mark.asyncio
async def test_claim_partitions_on_fleet_executor_and_lanes() -> None:
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[_claimed_item()]))
    config = SubagentBatchesConfig(lease_seconds=90)
    body = fleet_work.ClaimRequest(lease_owner="w-spark-01", lanes=["spark"], limit=1)

    response = await fleet_work.claim_work.__wrapped__(request=_request(repo, config), body=body)

    kwargs = repo.claim_items.await_args.kwargs
    assert (kwargs["executor"], kwargs["lanes"], kwargs["lease_owner"], kwargs["lease_seconds"], kwargs["limit"]) == ("fleet", {"spark"}, "w-spark-01", 90, 1)
    assert response["lease_seconds"] == 90
    item = response["items"][0]
    assert (item["id"], item["item_key"], item["lane"], item["data_class"], item["prompt"], item["max_tokens"], item["max_attempts"]) == ("item-1", "k-1", "spark", "public", "Summarize the public page", 16000, 2)
    assert item["lease_expires_at"]


@pytest.mark.asyncio
async def test_submit_refuses_private_data_on_spark_and_duplicate_keys(monkeypatch) -> None:
    repo = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "fleet-batch-1"}))
    monkeypatch.setattr(fleet_work, "get_current_user", AsyncMock(return_value="owner-1"))
    items = [{"key": "a", "prompt": "x"}, {"key": "b", "prompt": "y"}]

    with pytest.raises(HTTPException) as private_on_spark:
        await fleet_work.submit_fleet_batch.__wrapped__(
            request=_request(repo),
            body=fleet_work.FleetBatchSubmit(thread_id="t", title="T", lane="spark", data_class="private", items=items, submission_key="s1"),
        )
    assert private_on_spark.value.status_code == 422

    with pytest.raises(HTTPException) as duplicate:
        await fleet_work.submit_fleet_batch.__wrapped__(
            request=_request(repo),
            body=fleet_work.FleetBatchSubmit(thread_id="t", title="T", lane="haiku", data_class="private", items=[items[0], items[0]], submission_key="s2"),
        )
    assert duplicate.value.status_code == 422
    repo.create_batch.assert_not_awaited()

    created = await fleet_work.submit_fleet_batch.__wrapped__(
        request=_request(repo),
        body=fleet_work.FleetBatchSubmit(thread_id="t", title="T", lane="haiku", data_class="private", items=items, submission_key="s3", max_tokens=4096),
    )
    assert created == {"id": "fleet-batch-1"}
    kwargs = repo.create_batch.await_args.kwargs
    assert kwargs["user_id"] == "owner-1"
    assert kwargs["subagent_type"] == "fleet-haiku"
    assert kwargs["execution_spec"] == {"executor": "fleet", "lane": "haiku", "data_class": "private", "effort": "high", "max_tokens": 4096}
    assert kwargs["items"] == items
    assert kwargs["max_running_items"] == SubagentBatchesConfig().default_max_running_items
    assert kwargs["max_attempts"] == SubagentBatchesConfig().max_attempts


@pytest.mark.asyncio
async def test_finalize_bounds_result_and_rejects_lost_lease() -> None:
    repo = SimpleNamespace(finalize_item=AsyncMock(return_value=True))
    config = SubagentBatchesConfig(max_result_chars=1_000, result_preview_max_chars=64)
    body = fleet_work.FinalizeRequest(lease_owner="w-haiku-01", succeeded=True, result="x" * 1_500, model_name="m", token_usage={"cost_usd": 0.01})

    response = await fleet_work.finalize_work.__wrapped__(item_id="item-1", request=_request(repo, config), body=body)

    kwargs = repo.finalize_item.await_args.kwargs
    assert (len(kwargs["result"]), len(kwargs["result_preview"]), kwargs["result_truncated"], kwargs["lease_owner"], kwargs["succeeded"]) == (1_000, 64, True, "w-haiku-01", True)
    assert response == {"ok": True, "result_truncated": True}

    repo.finalize_item.return_value = False
    with pytest.raises(HTTPException) as lost:
        await fleet_work.finalize_work.__wrapped__(item_id="item-1", request=_request(repo, config), body=body)
    assert lost.value.status_code == 409

    failed = fleet_work.FinalizeRequest(lease_owner="w-haiku-01", succeeded=False, result="partial", error="e" * 5_000)
    repo.finalize_item.return_value = True
    await fleet_work.finalize_work.__wrapped__(item_id="item-1", request=_request(repo, config), body=failed)
    kwargs = repo.finalize_item.await_args.kwargs
    assert (kwargs["result"], kwargs["result_truncated"], len(kwargs["error"])) == (None, False, 4_000)


@pytest.mark.asyncio
async def test_renew_running_and_release_pass_the_lease_owner_through() -> None:
    repo = SimpleNamespace(
        renew_item_lease=AsyncMock(return_value={"valid": True, "cancel_requested": False}),
        mark_item_running=AsyncMock(return_value=False),
        requeue_item_after_admission_failure=AsyncMock(return_value=True),
    )
    request = _request(repo, SubagentBatchesConfig(lease_seconds=45))
    lease = fleet_work.LeaseRequest(lease_owner="w-sonnet-03")

    renewed = await fleet_work.renew_work.__wrapped__(item_id="item-1", request=request, body=lease)
    assert renewed == {"valid": True, "cancel_requested": False, "lease_seconds": 45}
    assert repo.renew_item_lease.await_args.kwargs["lease_seconds"] == 45

    with pytest.raises(HTTPException) as not_running:
        await fleet_work.mark_work_running.__wrapped__(item_id="item-1", request=request, body=lease)
    assert not_running.value.status_code == 409

    released = await fleet_work.release_work.__wrapped__(item_id="item-1", request=request, body=fleet_work.ReleaseRequest(lease_owner="w-sonnet-03", error="host stopping"))
    assert released == {"ok": True}
    assert repo.requeue_item_after_admission_failure.await_args.kwargs == {"lease_owner": "w-sonnet-03", "error": "host stopping", "now": repo.requeue_item_after_admission_failure.await_args.kwargs["now"]}
