import asyncio
import concurrent.futures
import json
import time
from pathlib import Path

import pytest

from deerflow.community.browser_automation.browserbase_fleet import Fleet, FleetBlocked, UsageLedger, scheduler_tick


def account():
    now = time.time()
    return dict(verified_included_only=True, cycle_id="test-cycle", cycle_end_epoch=now + 3600, verified_at_epoch=now, account_used_minutes=0, ceiling_minutes=10, included_minutes=6000, project_id="fake-project")


def config():
    return dict(
        enabled=True,
        scheduler_enabled=False,
        operator_id="owner",
        account=account(),
        jobs=[dict(id="site-qa", client_id="client-a", workflow="mobile_qa", url="https://example.com/", allowed_hosts=["example.com"], interval_seconds=86400)],
        verified_client_hosts={"client-a": ["example.com"]},
    )


def fleet(tmp_path):
    return Fleet(config(), {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger.db"), tmp_path / "artifacts")


@pytest.mark.parametrize("mutation", [dict(verified_included_only=False), dict(account_used_minutes=None), dict(verified_at_epoch=0), dict(ceiling_minutes=51), dict(cycle_end_epoch=0), dict(included_minutes=1)])
def test_unknown_account_never_reserves(tmp_path, mutation):
    ledger = UsageLedger(tmp_path / "ledger.db")
    with pytest.raises(FleetBlocked):
        ledger.reserve("job", "occurrence", {**account(), **mutation}, 0)
    assert ledger.status() == []


def test_atomic_multiworker_and_ambiguity(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.db")

    def attempt(index):
        try:
            return ledger.reserve("job", str(index), account(), 0)
        except FleetBlocked:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        tokens = [token for token in pool.map(attempt, range(8)) if token]
    assert len(tokens) == 1
    ledger.finish(tokens[0], False)
    with pytest.raises(FleetBlocked):
        ledger.reserve("job", "later", account(), 0)


def test_concurrency_and_no_refund(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.db")
    first = ledger.reserve("job", "first", account(), 0)
    ledger.running(first, "session1")
    second = ledger.reserve("job", "second", account(), 0)
    ledger.running(second, "session2")
    with pytest.raises(FleetBlocked):
        ledger.reserve("job", "third", account(), 0)
    ledger.finish(first, True)
    ledger.finish(second, True)
    for index in range(3):
        token = ledger.reserve("job", f"next-{index}", account(), 0)
        ledger.finish(token, True)
    with pytest.raises(FleetBlocked):
        ledger.reserve("job", "exhausted", account(), 0)
    assert sum(row["minutes"] for row in ledger.status()) == 10


def test_exact_session_reconciliation(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.db")
    token = ledger.reserve("job", "one", account(), 0)
    ledger.running(token, "owned")
    ledger.finish(token, False)
    with pytest.raises(FleetBlocked):
        ledger.reconcile(token, "else", "COMPLETED")
    with pytest.raises(FleetBlocked):
        ledger.reconcile(token, "owned", "RUNNING")
    ledger.reconcile(token, "owned", "COMPLETED")
    assert ledger.status()[0]["state"] == "finished"
    assert ledger.status()[0]["minutes"] == 2


def test_cloud_receipt_and_release(tmp_path):
    target = fleet(tmp_path)

    class API:
        project_id = "fake-project"
        creates = 0

        async def usage(self):
            return {"browserMinutes": 0}

        async def create(self, policy, **kwargs):
            self.creates += 1
            return {"id": "00000000-0000-4000-8000-000000000001", "connectUrl": "fake"}

        async def release(self, session):
            return {"status": "COMPLETED"}

        async def retrieve(self, session):
            return {"status": "COMPLETED"}

    async def capture(*args):
        return [{"overflow": False}]

    api = API()
    result = asyncio.run(target.run("site-qa", "today", api, capture=capture))
    assert result["status"] == "completed" and result["client_id"] == "client-a"
    assert api.creates == 1 and target.ledger.status()[0]["state"] == "finished"
    receipts = list((tmp_path / "artifacts" / "client-a").glob("*/receipt.json"))
    assert json.loads(receipts[0].read_text())["model_calls"] == 0
    with pytest.raises(FleetBlocked):
        asyncio.run(target.run("site-qa", "today", api, capture=capture))
    assert api.creates == 1


def test_uncertain_create_no_retry(tmp_path):
    target = fleet(tmp_path)

    class API:
        project_id = "fake-project"

        async def usage(self):
            return {"browserMinutes": 0}

        async def create(self, policy, **kwargs):
            raise RuntimeError("ambiguity")

    with pytest.raises(RuntimeError):
        asyncio.run(target.run("site-qa", "today", API()))
    assert target.ledger.status()[0]["state"] == "uncertain"
    with pytest.raises(FleetBlocked):
        asyncio.run(target.run("site-qa", "tomorrow", API()))


def test_dry_run_no_spend(tmp_path):
    target = fleet(tmp_path)
    assert asyncio.run(target.run("site-qa", "today", None, dry_run=True))["cloud_dispatch"] is False
    assert target.ledger.status() == []


def test_draft_and_report_client_binding(tmp_path):
    cfg = config()
    cfg["jobs"] = [
        dict(id="draft", client_id="client-a", workflow="local_draft", url=None, allowed_hosts=[], interval_seconds=86400, draft_fields={"title": "review"}),
        dict(id="report", client_id="client-a", workflow="report_retrieval", url=None, allowed_hosts=[], interval_seconds=86400),
    ]
    target = Fleet(cfg, {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger.db"), tmp_path / "out")
    draft = asyncio.run(target.run("draft", "one", None))
    assert json.loads(Path(draft["artifact"]).read_text())["submitted"] is False
    assert "draft" not in target.due(time.time())
    assert asyncio.run(target.run("report", "two", None))["status"] == "blocked"

    async def wrong(*args):
        return {"client_id": "client-b"}

    with pytest.raises(FleetBlocked):
        asyncio.run(target.run("report", "two", None, report_reader=wrong))

    target = Fleet(cfg, {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger-second.db"), tmp_path / "out-second")

    async def right(*args):
        return {"client_id": "client-a", "source": "existing API", "metrics": {"missing": None}}

    assert asyncio.run(target.run("report", "two", None, report_reader=right))["status"] == "retrieved"


@pytest.mark.parametrize("mutation", [{"client_id": "unknown"}, {"workflow": "submit_form"}, {"allowed_hosts": ["evil.example"]}, {"interval_seconds": 60}, {"id": "../escape"}])
def test_job_routing(tmp_path, mutation):
    cfg = config()
    cfg["jobs"][0].update(mutation)
    with pytest.raises((FleetBlocked, ValueError)):
        Fleet(cfg, {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger.db"), tmp_path / "out")


def test_scheduler_disabled(tmp_path):
    cfg = config()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"clients": [{"id": "client-a"}]}))
    cfg.update(registry_path=str(registry), ledger_path=str(tmp_path / "ledger.db"), output_path=str(tmp_path / "out"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    path.chmod(0o600)
    assert asyncio.run(scheduler_tick(path))[0]["status"] == "dry_run"
    with pytest.raises(FleetBlocked):
        asyncio.run(scheduler_tick(path, dry_run=False))


def test_external_usage_and_outstanding_charge_are_both_counted(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.db")
    settings = {**account(), "ceiling_minutes": 4}
    token = ledger.reserve("first", "one", settings, 0)
    ledger.running(token, "not-reflected-in-provider")
    with pytest.raises(FleetBlocked):
        ledger.reserve("second", "two", settings, 2)


def test_cadence_atomic_across_distinct_occurrences(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.db")
    token = ledger.reserve("daily-job", "manual-one", account(), 0, cadence=86400)
    ledger.finish(token, True)
    with pytest.raises(FleetBlocked):
        ledger.reserve("daily-job", "manual-two", account(), 0, cadence=86400)


def test_private_ancestors_refuse_symlinks(tmp_path):
    destination = tmp_path / "real"
    destination.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)
    with pytest.raises(FleetBlocked):
        UsageLedger(alias / "private" / "ledger.db")


def test_ambiguous_create_provider_ownership_readback(tmp_path):
    from deerflow.community.browser_automation.browserbase_fleet import reconcile_owned_session

    ledger = UsageLedger(tmp_path / "ledger.db")
    token = ledger.reserve("job", "uncertain", account(), 0)
    ledger.finish(token, False)

    class API:
        project_id = "project"
        metadata = "wrong"

        async def retrieve(self, session):
            return {"id": session, "projectId": "project", "userMetadata": {"reservation_id": self.metadata}, "status": "COMPLETED"}

    api = API()
    with pytest.raises(FleetBlocked):
        asyncio.run(reconcile_owned_session(api, ledger, token, "owned-session"))
    assert ledger.status()[0]["state"] == "uncertain"
    api.metadata = token
    asyncio.run(reconcile_owned_session(api, ledger, token, "owned-session"))
    assert ledger.status()[0]["state"] == "finished"
    assert ledger.status()[0]["minutes"] == 2


def test_named_entrypoint_report_reader_binding(tmp_path):
    from deerflow.community.browser_automation.browserbase_fleet import run_named_job

    cfg = config()
    cfg["jobs"] = [dict(id="report", client_id="client-a", workflow="report_retrieval", url=None, allowed_hosts=[], interval_seconds=86400)]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"clients": [{"id": "client-a"}]}))
    cfg.update(registry_path=str(registry), ledger_path=str(tmp_path / "ledger.db"), output_path=str(tmp_path / "out"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    path.chmod(0o600)

    async def reader(client, job):
        return {"client_id": client, "source": "existing_authenticated_connector"}

    result = asyncio.run(run_named_job(path, "report", operator_id="owner", report_reader=reader))
    assert result["status"] == "retrieved" and result["cloud_dispatch"] is False


def test_staff_tool_auth_before_config_and_worker(tmp_path, monkeypatch):
    import deerflow.community.browser_automation.browserbase_fleet_tool as module

    async def deny(runtime):
        return None, "Authenticated owner required"

    monkeypatch.setattr(module, "_owner_repository", deny)
    result = asyncio.run(module.browserbase_fleet_job.coroutine(None, "anything"))
    assert json.loads(result)["status"] == "blocked"
    assert "Authenticated owner" in result


def test_staff_tool_no_arbitrary_url_or_credentials():
    from deerflow.community.browser_automation.browserbase_fleet_tool import browserbase_fleet_job

    properties = browserbase_fleet_job.args
    assert set(properties) == {"job_id", "dry_run"}


def test_report_admission_precedes_connector_and_artifact(tmp_path):
    cfg = config()
    cfg["jobs"] = [dict(id="report", client_id="client-a", workflow="report_retrieval", url=None, allowed_hosts=[], interval_seconds=86400)]
    target = Fleet(cfg, {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger.db"), tmp_path / "out")
    calls = []

    async def reader(client, job):
        calls.append(job)
        return {"client_id": client}

    asyncio.run(target.run("report", "first", None, report_reader=reader))
    with pytest.raises(FleetBlocked):
        asyncio.run(target.run("report", "second", None, report_reader=reader))
    assert calls == ["report"]
    assert len(list((tmp_path / "out").glob("*/*/report.json"))) == 1
