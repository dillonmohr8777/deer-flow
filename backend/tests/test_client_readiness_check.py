"""Read-only recurring drill admission: stale, missing and oversized sources fail."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("readiness_check", Path(__file__).resolve().parents[2] / "deploy/momentum/ec2/readiness_check.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
NOW = datetime(2026, 10, 23, tzinfo=UTC)


def backup(age=1, size=100):
    return {"Key": "nightly/momobot-synthetic.tgz", "Size": size, "LastModified": (NOW - timedelta(hours=age)).isoformat()}


def test_selects_latest_with_bounded_freshness_and_size():
    latest = backup()
    assert module.latest_backup([backup(12), latest], NOW) == latest


@pytest.mark.parametrize("objects", [[], [backup(37)], [backup(-1)], [backup(size=0)], [backup(size=3 * 1024**3)]])
def test_refuses_missing_stale_future_or_oversized_backup(objects):
    with pytest.raises(ValueError):
        module.latest_backup(objects, NOW)


def test_generated_jobs_are_background_checks_without_hosting_or_run_at_load(tmp_path):
    import plistlib

    spec = importlib.util.spec_from_file_location("readiness_launchd", Path(module.ROOT) / "deploy/momentum/ec2/readiness_launchd.py")
    launchd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launchd)
    checkout = tmp_path / "checkout"
    script = checkout / "deploy/momentum/ec2/readiness_check.py"
    script.parent.mkdir(parents=True)
    script.touch()
    python, pnpm = tmp_path / "python", tmp_path / "pnpm"
    python.touch()
    pnpm.touch()
    output, receipts = tmp_path / "plists", tmp_path / "receipts"
    launchd.write_plists(checkout, python, pnpm, output, receipts)
    jobs = [plistlib.loads(p.read_bytes()) for p in output.iterdir()]
    assert len(jobs) == 2
    assert sorted(job["StartCalendarInterval"]["Hour"] for job in jobs) == [5, 13]
    for job in jobs:
        assert job["ProcessType"] == "Background"
        assert "RunAtLoad" not in job and "KeepAlive" not in job
        assert job["ProgramArguments"][2] in ("tenant", "restore")
