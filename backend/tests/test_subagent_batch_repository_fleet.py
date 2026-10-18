"""Fleet executor partition on the shared subagent batch item leases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


async def _repo(tmp_path) -> SubagentBatchRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    return SubagentBatchRepository(sf)


async def _create(repo: SubagentBatchRepository, batch_id: str, execution_spec: dict, *, count: int = 2) -> dict:
    return await repo.create_batch(
        batch_id=batch_id,
        user_id="user-1",
        thread_id="thread-1",
        run_id=None,
        tool_call_id=None,
        submission_key=batch_id,
        title=batch_id,
        subagent_type="fleet-test",
        items=[{"key": f"{batch_id}-{i}", "prompt": f"Do {i}"} for i in range(count)],
        max_live_items=10,
        max_running_items=10,
        max_attempts=2,
        execution_spec=execution_spec,
    )


@pytest.mark.asyncio
async def test_native_and_fleet_claims_never_see_each_other(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, "native", {"subagent_config": {"name": "general-purpose"}})
    await _create(repo, "fleet-haiku", {"executor": "fleet", "lane": "haiku", "data_class": "private"})
    await _create(repo, "fleet-spark", {"executor": "fleet", "lane": "spark", "data_class": "public"})
    now = datetime.now(UTC)

    native = await repo.claim_items(now=now, lease_owner="gateway", lease_seconds=60, limit=10)
    assert {item["batch_id"] for item in native} == {"native"}

    haiku = await repo.claim_items(now=now, lease_owner="w-haiku-01", lease_seconds=60, limit=10, executor="fleet", lanes={"haiku"})
    assert {item["batch_id"] for item in haiku} == {"fleet-haiku"}
    assert haiku[0]["batch"]["execution_spec"]["data_class"] == "private"

    rest = await repo.claim_items(now=now, lease_owner="w-spark-01", lease_seconds=60, limit=10, executor="fleet", lanes={"haiku", "spark"})
    assert {item["batch_id"] for item in rest} == {"fleet-spark"}

    assert await repo.claim_items(now=now, lease_owner="w-x", lease_seconds=60, limit=10, executor="fleet", lanes={"sonnet"}) == []


@pytest.mark.asyncio
async def test_fleet_lease_is_fenced_released_and_reclaimed_with_stable_identity(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, "fleet-haiku", {"executor": "fleet", "lane": "haiku", "data_class": "synthetic"}, count=1)
    now = datetime.now(UTC)
    first = (await repo.claim_items(now=now, lease_owner="w-haiku-01", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}))[0]
    assert first["attempt"] == 1

    # Another worker can neither renew nor finalize someone else's lease.
    assert (await repo.renew_item_lease(first["id"], lease_owner="w-haiku-02", lease_seconds=60, now=now))["valid"] is False
    assert not await repo.finalize_item(
        first["id"],
        lease_owner="w-haiku-02",
        succeeded=True,
        result="stolen",
        result_preview="stolen",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage=None,
        model_name=None,
        completed_at=now,
    )
    assert (await repo.renew_item_lease(first["id"], lease_owner="w-haiku-01", lease_seconds=60, now=now))["valid"] is True

    # Interrupted host hands the item back: queued again, attempt restored, same identity.
    assert await repo.requeue_item_after_admission_failure(first["id"], lease_owner="w-haiku-01", error="host stopping", now=now)
    item = (await repo.list_items("fleet-haiku", user_id="user-1"))[0]
    assert (item["status"], item["attempt"]) == ("queued", 0)

    second = (await repo.claim_items(now=now + timedelta(seconds=1), lease_owner="w-haiku-02", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}))[0]
    assert (second["id"], second["item_key"], second["attempt"]) == (first["id"], first["item_key"], 1)
    assert await repo.finalize_item(
        second["id"],
        lease_owner="w-haiku-02",
        succeeded=True,
        result="done",
        result_preview="done",
        result_truncated=False,
        error=None,
        stop_reason="stop",
        token_usage={"cost_usd": 0.001},
        model_name="anthropic/claude-haiku-5.5",
        completed_at=now + timedelta(seconds=2),
    )
    done = (await repo.list_items("fleet-haiku", user_id="user-1", include_result=True))[0]
    assert (done["status"], done["result"], done["model_name"]) == ("succeeded", "done", "anthropic/claude-haiku-5.5")
    assert await repo.claim_items(now=now + timedelta(seconds=3), lease_owner="w-haiku-03", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}) == []
