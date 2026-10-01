import asyncio
import concurrent.futures
import json
import time
import types
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


@pytest.mark.parametrize("mutation", [dict(verified_included_only=False), dict(account_used_minutes=None), dict(verified_at_epoch=0), dict(ceiling_minutes=6001), dict(cycle_end_epoch=0), dict(included_minutes=1)])
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


def test_uncertain_create_no_retry(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet, browserbase_qa

    monkeypatch.setattr(browserbase_fleet, "playwright_available", lambda: True)
    monkeypatch.setattr(browserbase_qa, "playwright_available", lambda: True)
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


def test_operator_ceiling_above_old_fixed_cap_admits(tmp_path):
    # Project usage already past 50 minutes must not dead-lock the fleet when the operator attests a higher ceiling.
    ledger = UsageLedger(tmp_path / "ledger.db")
    ledger.reserve("job", "occurrence", {**account(), "account_used_minutes": 87, "ceiling_minutes": 200}, 87)
    assert ledger.status()[0]["state"] == "reserved"
    with pytest.raises(FleetBlocked):
        UsageLedger(tmp_path / "other.db").reserve("job", "occurrence", {**account(), "account_used_minutes": 87, "ceiling_minutes": 88}, 87)


def test_missing_playwright_blocks_before_reservation(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "playwright_available", lambda: False)
    target = fleet(tmp_path)

    class API:
        project_id = "fake-project"
        creates = 0

        async def usage(self):
            return {"browserMinutes": 0}

        async def create(self, policy, **kwargs):
            self.creates += 1
            raise AssertionError("no session may be created")

    api = API()
    with pytest.raises(FleetBlocked, match="Playwright"):
        asyncio.run(target.run("site-qa", "today", api))
    assert api.creates == 0 and target.ledger.status() == []


def test_unknown_named_job_is_blocked_not_keyerror(tmp_path):
    from deerflow.community.browser_automation.browserbase_fleet import run_named_job

    cfg = config()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"clients": [{"id": "client-a"}]}))
    cfg.update(registry_path=str(registry), ledger_path=str(tmp_path / "ledger.db"), output_path=str(tmp_path / "out"), project_id="00000000-0000-4000-8000-000000000000")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    path.chmod(0o600)
    with pytest.raises(FleetBlocked, match="operator-approved"):
        asyncio.run(run_named_job(path, "not-a-job", operator_id="owner"))


AGENT = "00000000-0000-4000-8000-00000000a9e7"
RUN = "00000000-0000-4000-8000-0000000000f1"


def native_fleet(tmp_path, runs_included=15, **job):
    cfg = config()
    cfg["account"]["agent_runs_included"] = runs_included
    cfg["account"]["ceiling_minutes"] = 60
    base = dict(client_id="client-a", workflow="native_agent", url="https://example.com/", allowed_hosts=["example.com"], interval_seconds=86400, agent_id=AGENT, task="Measure the homepage.", max_minutes=8)
    cfg["jobs"] = [{**base, "id": "seo-audit", **job}, {**base, "id": "prospect"}]
    return Fleet(cfg, {"clients": [{"id": "client-a"}]}, UsageLedger(tmp_path / "ledger.db"), tmp_path / "artifacts")


class AgentAPI:
    project_id = "fake-project"

    def __init__(self, statuses, active=()):
        self.statuses = list(statuses)
        self.active = list(active)
        self.tasks, self.stops = [], 0

    async def usage(self):
        return {"browserMinutes": 0}

    async def agent_runs(self, status):
        return {"data": [{"status": status}] if status in self.active else []}

    async def start_agent_run(self, agent_id, task, *, reservation_id=None):
        self.tasks.append(task)
        self.reservation_ids = [*getattr(self, "reservation_ids", []), reservation_id]
        return {"runId": RUN, "status": "PENDING"}

    async def agent_run(self, run_id):
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"runId": run_id, "status": status, "sessionId": "session-1", "result": {"summary": "ok"}}

    stop_errors = ("HTTP 409",)

    async def stop_agent_run(self, run_id):
        self.stops += 1
        error = self.stop_errors[min(self.stops, len(self.stop_errors)) - 1]
        if error:
            raise RuntimeError(f"Browserbase API request failed ({error})")
        return {}

    async def retrieve(self, session):
        return {"status": "COMPLETED", "projectId": self.project_id}

    async def agent_run_messages(self, run_id):
        return {"data": [{"content": [{"type": "file", "mediaType": "image/png", "data": "aGk="}, {"type": "text", "text": "done"}]}]}


def test_native_agent_run_reserves_cap_saves_artifacts(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)
    api = AgentAPI(["RUNNING", "COMPLETED"])
    result = asyncio.run(target.run("seo-audit", "today", api))
    assert result["status"] == "completed" and result["run_id"] == RUN and api.stops == 0
    assert result["model_calls"] == "provider-side, not metered"
    assert asyncio.run(target.run("seo-audit", "x", None, dry_run=True))["model_calls"] != 0
    assert "Never log in" in api.tasks[0] and "https://example.com/" in api.tasks[0]
    row = target.ledger.status()[0]
    assert row["minutes"] == 9 and row["state"] == "finished" and row["session"] == "session-1"
    folder = Path(result["artifact"]).parent
    assert (folder / "screenshot-01.png").read_bytes() == b"hi"
    assert json.loads((folder / "messages.json").read_text())[0]["content"][0]["data"] == "screenshot-01"
    assert (folder / "receipt.json").stat().st_mode & 0o077 == 0


def test_native_agent_refuses_when_account_busy_or_runs_used(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    busy = AgentAPI(["COMPLETED"], active=["RUNNING"])
    with pytest.raises(FleetBlocked, match="active"):
        asyncio.run(native_fleet(tmp_path / "a").run("seo-audit", "today", busy))
    assert busy.tasks == []
    target = native_fleet(tmp_path / "b", runs_included=1)
    asyncio.run(target.run("seo-audit", "today", AgentAPI(["COMPLETED"])))
    second = AgentAPI(["COMPLETED"])
    with pytest.raises(FleetBlocked, match="agent runs"):
        asyncio.run(target.run("prospect", "tomorrow", second))
    assert second.tasks == []
    with pytest.raises(FleetBlocked, match="agent runs"):
        asyncio.run(native_fleet(tmp_path / "c", runs_included=0).run("seo-audit", "today", AgentAPI(["COMPLETED"])))


def test_native_agent_stops_at_cap_and_stays_uncertain_if_stop_never_lands(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    clock = iter(range(0, 100_000, 120))
    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    # Swap only the fleet module's clock; asyncio keeps the real one.
    monkeypatch.setattr(browserbase_fleet, "time", types.SimpleNamespace(time=time.time, monotonic=lambda: next(clock)))
    target = native_fleet(tmp_path, max_minutes=1)
    api = AgentAPI(["RUNNING"])
    result = asyncio.run(target.run("seo-audit", "today", api))
    assert result["status"] == "uncertain" and api.stops == 1
    assert target.ledger.status()[0]["state"] == "uncertain"
    with pytest.raises(FleetBlocked, match="reconciliation"):
        asyncio.run(target.run("prospect", "tomorrow", AgentAPI(["COMPLETED"])))


@pytest.mark.parametrize("bad", [dict(agent_id="not-a-uuid"), dict(task=" "), dict(max_minutes=16), dict(max_minutes=True), dict(url=None)])
def test_native_agent_config_is_validated(tmp_path, bad):
    with pytest.raises((FleetBlocked, ValueError)):
        native_fleet(tmp_path, **bad)


def test_native_agent_survives_poll_and_message_failures(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)

    class Flaky(AgentAPI):
        polls = 0

        async def agent_run(self, run_id):
            self.polls += 1
            if self.polls == 1:
                raise RuntimeError("Browserbase API request failed (HTTP 503)")
            return await super().agent_run(run_id)

        async def agent_run_messages(self, run_id):
            raise RuntimeError("Browserbase API response exceeds QA limit")

    target = native_fleet(tmp_path)
    result = asyncio.run(target.run("seo-audit", "today", Flaky(["COMPLETED"])))
    assert result["status"] == "completed" and "exceeds" in result["messages_error"]
    folder = Path(result["artifact"]).parent
    assert json.loads((folder / "run.json").read_text())["status"] == "COMPLETED"
    assert json.loads((folder / "started.json").read_text())["run_id"] == RUN
    assert (folder / "receipt.json").exists() and target.ledger.status()[0]["state"] == "finished"


def test_native_agent_retries_failed_stop_and_stops_paused_runs(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    api = AgentAPI(["PAUSED", "PAUSED", "PAUSED", "STOPPED"])
    api.stop_errors = ("HTTP 500", None)
    result = asyncio.run(native_fleet(tmp_path).run("seo-audit", "today", api))
    assert result["status"] == "stopped" and result["stop_requested"] is True and api.stops == 2


def test_native_agent_own_failure_stops_run_and_reconcile_repairs(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)
    api = AgentAPI(["RUNNING"])
    api.stop_errors = (None,)

    def lost(*args):
        raise FleetBlocked("Reservation ownership lost")

    monkeypatch.setattr(target.ledger, "running", lost)
    with pytest.raises(FleetBlocked, match="ownership"):
        asyncio.run(target.run("seo-audit", "today", api))
    assert api.stops == 1 and target.ledger.status()[0]["state"] == "uncertain"
    token = target.ledger.status()[0]["id"]
    with pytest.raises(FleetBlocked, match="not terminal"):
        asyncio.run(browserbase_fleet.reconcile_native_run(api, target.ledger, token, RUN))
    api.statuses = ["STOPPED"]
    asyncio.run(browserbase_fleet.reconcile_native_run(api, target.ledger, token, RUN))
    row = target.ledger.status()[0]
    assert row["state"] == "finished" and row["session"] == "session-1" and row["minutes"] == 9


def test_native_agent_start_run_carries_reservation_token(tmp_path, monkeypatch):
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)
    api = AgentAPI(["RUNNING", "COMPLETED"])
    asyncio.run(target.run("seo-audit", "today", api))
    assert api.reservation_ids == [target.ledger.status()[0]["id"]]


def test_native_agent_definite_start_rejection_settles_finished_not_locked(tmp_path, monkeypatch):
    """A confirmed HTTP 400 means no run could exist -- unlike every other start failure, it must not
    leave an uncertain reservation that can never reconcile (no run id will ever exist for it)."""
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)

    class Rejected(AgentAPI):
        async def start_agent_run(self, agent_id, task, *, reservation_id=None):
            raise RuntimeError("Browserbase API request failed (HTTP 400)")

    with pytest.raises(RuntimeError, match="HTTP 400"):
        asyncio.run(target.run("seo-audit", "today", Rejected([])))
    assert target.ledger.status()[0]["state"] == "finished"
    # Dispatch is not locked: a later reservation on a different job succeeds immediately.
    asyncio.run(target.run("prospect", "tomorrow", AgentAPI(["COMPLETED"])))


@pytest.mark.parametrize("code", [401, 404, 409, 422, 429, 500, 503])
def test_native_agent_ambiguous_start_failure_still_stays_uncertain(tmp_path, monkeypatch, code):
    """Every start failure other than a confirmed HTTP 400 -- including every other 4xx -- may still
    have created a billable run and must stay uncertain until an operator reconciles it. The HTTP 400
    carve-out must not widen to any `"HTTP 4"` prefix match."""
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)

    class Ambiguous(AgentAPI):
        async def start_agent_run(self, agent_id, task, *, reservation_id=None):
            raise RuntimeError(f"Browserbase API request failed (HTTP {code})")

    with pytest.raises(RuntimeError, match=f"HTTP {code}"):
        asyncio.run(target.run("seo-audit", "today", Ambiguous([])))
    assert target.ledger.status()[0]["state"] == "uncertain"
    with pytest.raises(FleetBlocked, match="reconciliation"):
        asyncio.run(target.run("prospect", "tomorrow", AgentAPI(["COMPLETED"])))


def _unbind(tmp_path, monkeypatch):
    """Shared setup: a start failure that leaves a reservation uncertain with no started.json."""
    from deerflow.community.browser_automation import browserbase_fleet

    monkeypatch.setattr(browserbase_fleet, "_AGENT_POLL_SECONDS", 0)
    target = native_fleet(tmp_path)

    class Unbound(AgentAPI):
        async def start_agent_run(self, agent_id, task, *, reservation_id=None):
            raise RuntimeError("Browserbase API request failed (HTTP 503)")

    with pytest.raises(RuntimeError, match="HTTP 503"):
        asyncio.run(target.run("seo-audit", "today", Unbound([])))
    row = target.ledger.status()[0]
    assert row["state"] == "uncertain"
    return target, row["id"], row["created"]


OTHER_AGENT = "00000000-0000-4000-8000-00000000b2e1"


def test_parse_epoch_seconds_rejects_millisecond_scale_numbers():
    """A millisecond epoch (~1000x a real epoch-seconds value) used to be read as raw seconds, landing
    far in the future instead of being refused -- numbers past the ceiling now return None."""
    from deerflow.community.browser_automation.browserbase_fleet import _parse_epoch_seconds

    assert _parse_epoch_seconds(time.time() * 1000) is None
    assert _parse_epoch_seconds(time.time()) is not None


def test_parse_epoch_seconds_rejects_naive_datetime_strings():
    """A naive ISO 8601 string (no `Z`, no UTC offset) used to parse to a real timestamp via the host's
    own local timezone; it now returns None regardless of the host's timezone."""
    from deerflow.community.browser_automation.browserbase_fleet import _parse_epoch_seconds

    assert _parse_epoch_seconds("2026-10-01T12:00:00") is None
    assert _parse_epoch_seconds("2026-10-01T12:00:00Z") is not None
    assert _parse_epoch_seconds("2026-10-01T12:00:00+00:00") is not None


def test_reconcile_unbound_native_run_derives_agent_from_job_not_a_caller_argument(tmp_path, monkeypatch):
    """The expected agent comes from the reservation's own job config, never a caller-supplied
    argument (there is none to spoof): a run genuinely belonging to a different job's real,
    provisioned agent is never accepted for this reservation regardless of anything else it reports."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, _created = _unbind(tmp_path, monkeypatch)
    assert target.jobs["seo-audit"].agent_id == AGENT

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": OTHER_AGENT, "createdAt": time.time() + 1}

    with pytest.raises(FleetBlocked, match="identity"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_rejects_run_created_before_reservation(tmp_path, monkeypatch):
    """With no `variables` echo, a run that predates this reservation's own `created` time cannot be
    the one it started -- `reserve()` and `_agent_run_active` together make a same-agent run inside the
    window unambiguous, but a run from before that window proves nothing."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": created - 1000}

    with pytest.raises(FleetBlocked, match="ownership"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_rejects_run_created_well_after_the_start_window(tmp_path, monkeypatch):
    """No upper bound used to exist on `createdAt`, so a run from a day later -- long after
    `start_agent_run`'s own http client could still have been in flight -- was wrongly accepted as
    proof. The window is now bounded by the request timeout plus clock skew."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": created + 86400}

    with pytest.raises(FleetBlocked, match="ownership"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_rejects_a_mismatched_variables_echo_even_inside_the_window(tmp_path, monkeypatch):
    """A `variables.reservation_id` that names a different reservation is affirmative proof the run
    belongs to someone else's token -- it must be refused outright, never papered over by a `createdAt`
    that happens to land inside the start window (previously: a mismatched echo was silently treated as
    no echo at all, falling through to the time check alone)."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": created + 1, "variables": {"reservation_id": "some-other-reservation"}}

    with pytest.raises(FleetBlocked, match="different reservation"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_claims_by_agent_and_window(tmp_path, monkeypatch):
    """No started.json was ever written (start_agent_run failed before a run id could be recorded), so
    the operator-supplied run id is proven from documented AgentRun fields: matching the job's own
    `agentId` plus a `createdAt` inside the start window -- never a bare elapsed-time guess, and never
    the undocumented `metadata` field the old proof relied on."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        status = "COMPLETED"
        created_at: float = created + 1

        async def agent_run(self, run_id):
            return {"runId": run_id, "status": self.status, "sessionId": "session-1", "agentId": AGENT, "createdAt": self.created_at}

    api = Readback([])
    asyncio.run(browserbase_fleet.reconcile_unbound_native_run(api, target, token, RUN))
    row = target.ledger.status()[0]
    assert row["state"] == "finished" and row["session"] == "session-1"

    # Already bound and finished: a second call finds no matching uncertain row left to claim.
    with pytest.raises(FleetBlocked, match="unbound"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(api, target, token, RUN))


def test_reconcile_unbound_native_run_accepts_echoed_variables_without_window(tmp_path, monkeypatch):
    """A `variables` echo matching this token is accepted as proof on its own, even with no usable
    `createdAt` -- `variables` is a documented request field, unlike `metadata`, so an echo of it (if
    the provider gives one) is trusted the same way session `userMetadata` already is."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, _created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": "not-a-timestamp", "variables": {"reservation_id": token}}

    asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    row = target.ledger.status()[0]
    assert row["state"] == "finished" and row["session"] == "session-1"


def test_reconcile_unbound_native_run_rejects_millisecond_epoch_timestamp(tmp_path, monkeypatch):
    """A real event a day before the reservation, expressed as a millisecond epoch, used to be
    misread as raw seconds -- a number so large it was wrongly accepted as proof of a run far in the
    future rather than rejected for having no upper bound. Numbers above the epoch-seconds ceiling are
    now refused outright rather than guessed at."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)
    day_earlier_in_ms = (created - 86400) * 1000

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": day_earlier_in_ms}

    with pytest.raises(FleetBlocked, match="ownership"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_rejects_naive_datetime_string(tmp_path, monkeypatch):
    """A naive ISO 8601 string (no `Z`, no UTC offset) carries no timezone, so `datetime.fromisoformat`
    would read it in the host's own local timezone -- on a host set to, say, America/Los_Angeles, a
    string that is actually 6 hours before the reservation's `created` time would be misread as hours
    later and wrongly land inside the window. Naive strings are refused outright instead."""
    from datetime import datetime, timedelta

    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)
    naive = (datetime.fromtimestamp(created) - timedelta(hours=6)).replace(tzinfo=None).isoformat()
    assert "+" not in naive and "Z" not in naive

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "COMPLETED", "sessionId": "session-1", "agentId": AGENT, "createdAt": naive}

    with pytest.raises(FleetBlocked, match="ownership"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_reconcile_unbound_native_run_refuses_non_terminal_instead_of_silently_doing_nothing(tmp_path, monkeypatch):
    """A proven-owned run that is not yet terminal must raise, not silently return with nothing
    persisted -- the same contract `reconcile_native_run` already gives a started.json-backed run."""
    from deerflow.community.browser_automation import browserbase_fleet

    target, token, created = _unbind(tmp_path, monkeypatch)

    class Readback(AgentAPI):
        async def agent_run(self, run_id):
            return {"runId": run_id, "status": "RUNNING", "sessionId": "session-1", "agentId": AGENT, "createdAt": created + 1}

    with pytest.raises(FleetBlocked, match="not terminal"):
        asyncio.run(browserbase_fleet.reconcile_unbound_native_run(Readback([]), target, token, RUN))
    assert target.ledger.status()[0]["state"] == "uncertain"


def test_native_agent_fails_closed_on_unreadable_run_list(tmp_path):
    class Odd(AgentAPI):
        async def agent_runs(self, status):
            return {"items": []}

    api = Odd(["COMPLETED"])
    with pytest.raises(FleetBlocked, match="unreadable"):
        asyncio.run(native_fleet(tmp_path).run("seo-audit", "today", api))
    assert api.tasks == []
