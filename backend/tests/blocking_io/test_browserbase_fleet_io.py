"""Real private file/SQLite paths must stay off the Gateway event loop."""

import json

import pytest

from deerflow.community.browser_automation.browserbase_fleet import run_named_job, scheduler_tick


@pytest.fixture
def fleet_config(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"clients": [{"id": "client-a"}]}))
    config = {
        "enabled": False,
        "scheduler_enabled": False,
        "operator_id": "owner",
        "registry_path": str(registry),
        "ledger_path": str(tmp_path / "ledger.sqlite"),
        "output_path": str(tmp_path / "artifacts"),
        "jobs": [{"id": "local-draft", "client_id": "client-a", "workflow": "local_draft", "url": None, "allowed_hosts": [], "interval_seconds": 86400, "draft_fields": {"title": "review"}}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_scheduler_real_sqlite_and_config_do_not_block(fleet_config):
    result = await scheduler_tick(fleet_config, dry_run=True)
    assert result[0]["status"] == "dry_run"


@pytest.mark.asyncio
async def test_named_local_draft_real_write_does_not_block(fleet_config):
    result = await run_named_job(fleet_config, "local-draft", operator_id="owner")
    assert result["status"] == "draft_only"
    assert result["cloud_dispatch"] is False
