import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from deerflow.scheduler.schedules import next_run_at
from deerflow.scheduler.workflow_templates import plan_seed, validate_template, workflow_templates

_BACKEND = Path(__file__).resolve().parents[1]
_SEED = _BACKEND / "scripts" / "seed_scheduled_workflows.py"
_TEMPLATES = _BACKEND / "packages/harness/deerflow/scheduler/workflow_templates.py"


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_scheduled_workflows", _SEED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.seed


def test_four_templates_validate_and_schedule():
    templates = workflow_templates()
    assert len(templates) == 4
    assert len({t["title"] for t in templates}) == 4
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    for t in templates:
        validate_template(t)
        assert next_run_at(t["schedule_type"], t["schedule_spec"], t["timezone"], now=now) > now


def test_monday_report_fires_monday_0700_et():
    t = next(t for t in workflow_templates() if t["key"] == "monday-report-drafts")
    nxt = next_run_at("cron", t["schedule_spec"], t["timezone"], now=datetime(2026, 10, 5, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 10, 12, 11, 0, tzinfo=UTC)


def test_prompts_carry_required_rules_and_no_client_data():
    for t in workflow_templates():
        p = t["prompt"]
        for needle in ("Drafts only", "No AI footer", "no em dashes", "Never invent numbers", "Missing is not zero", "clients.json"):
            assert needle in p, (t["key"], needle)
        assert "—" not in p
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", p)
        assert "http" not in p


class FakeGateway:
    def __init__(self):
        self.tasks = {}

    def __call__(self, method, path, payload):
        if method == "GET":
            return list(self.tasks.values())
        if path.endswith("/pause"):
            tid = path.split("/")[-2]
            self.tasks[tid]["status"] = "paused"
            return self.tasks[tid]
        tid = f"task-{len(self.tasks)}"
        self.tasks[tid] = {**payload, "id": tid, "status": "enabled"}
        return self.tasks[tid]


def test_seed_is_idempotent_and_creates_paused():
    seed = _load_seed()
    gw = FakeGateway()
    assert len(seed(gw)["created"]) == 4
    assert all(t["status"] == "paused" for t in gw.tasks.values())
    again = seed(gw)
    assert again["created"] == [] and len(again["existing"]) == 4
    assert len(gw.tasks) == 4


def test_dry_run_creates_nothing():
    gw = FakeGateway()
    _load_seed()(gw, dry_run=True)
    assert gw.tasks == {}
    assert len(plan_seed({"Morning brief"})) == 3


def test_nothing_turns_scheduler_on():
    cfg = yaml.safe_load((_BACKEND.parent / "config.example.yaml").read_text(encoding="utf-8"))
    assert cfg["scheduler"]["enabled"] is False
    for path in (_SEED, _TEMPLATES):
        text = path.read_text(encoding="utf-8")
        assert "config.yaml" not in text
        assert "enabled: true" not in text.lower()
