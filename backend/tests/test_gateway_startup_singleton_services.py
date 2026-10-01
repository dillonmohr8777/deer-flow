"""Regression tests for the Browserbase/Workflow singleton-service startup helpers.

These pin the exact gaps a review (PR #127, review 5377659715) found in the
first cut of `_start_singleton_service`/`_startup_browserbase_service`/
`_startup_workflow_service` in `app.gateway.app`:

1. Browserbase and Workflow take *separate* exclusive leases, so a worker can
   lose the Browserbase race and still win the Workflow one -- handing
   `WorkflowService` a `browser_service` that is not actually running on this
   process. Gateway startup must skip starting Workflow there too.
2. `_start_singleton_service` must swallow only `service_already_running`,
   never any other startup error -- and this must be pinned for the Workflow
   path specifically, not just Browserbase (the lifespan integration test in
   `test_managed_provider_startup.py` never enables `MOMOBOT_WORKFLOWS_ENABLED`).
3. `BrowserbaseResearchService.lock_contended` must reset to `False` once a
   later `start()` call actually succeeds (e.g. after the winning worker exits
   and releases the lease).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from app.gateway.app import _start_singleton_service, _startup_workflow_service
from app.gateway.browserbase_service import BrowserbaseError, BrowserbaseResearchService


class _FakeStartupError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@pytest.mark.asyncio
async def test_start_singleton_service_swallows_only_service_already_running():
    """Any other startup error (or error type) must still propagate."""

    class _LockedService:
        async def start(self):
            raise _FakeStartupError("service_already_running")

    class _BrokenService:
        async def start(self):
            raise _FakeStartupError("process_lock_unavailable")

    class _CrashingService:
        async def start(self):
            raise RuntimeError("unrelated bug")

    await _start_singleton_service(_LockedService(), error_cls=_FakeStartupError, label="fake")

    with pytest.raises(_FakeStartupError, match="process_lock_unavailable"):
        await _start_singleton_service(_BrokenService(), error_cls=_FakeStartupError, label="fake")

    with pytest.raises(RuntimeError, match="unrelated bug"):
        await _start_singleton_service(_CrashingService(), error_cls=_FakeStartupError, label="fake")


@pytest.mark.asyncio
async def test_browserbase_lock_contended_resets_once_a_later_start_succeeds(monkeypatch, tmp_path):
    """A worker that lost the race once must stop reporting unavailable after it wins a retry."""
    monkeypatch.setenv("MOMOBOT_BROWSERBASE_ENABLED", "true")
    path = tmp_path / "browserbase-research.sqlite"
    winner = BrowserbaseResearchService(path)
    await winner.start()

    loser = BrowserbaseResearchService(path)
    with pytest.raises(BrowserbaseError, match="service_already_running"):
        await loser.start()
    assert loser.lock_contended is True
    assert (await loser.status())["reason"] == "service_unavailable"

    await winner.aclose()
    await loser.start()
    assert loser.started is True
    assert loser.lock_contended is False

    await loser.aclose()


def _workflow_app(tmp_path, *, browserbase_service=None) -> FastAPI:
    app = FastAPI()
    app.state.checkpointer = MagicMock()
    app.state.run_manager = MagicMock()
    app.state.thread_store = MagicMock()
    app.state.run_event_store = MagicMock()
    if browserbase_service is not None:
        app.state.browserbase_service = browserbase_service
    return app


@pytest.mark.asyncio
async def test_workflow_service_survives_lock_contention_without_browserbase(monkeypatch, tmp_path):
    """Reverting the service_already_running guard around workflow start must fail this."""
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    monkeypatch.delenv("MOMOBOT_BROWSERBASE_ENABLED", raising=False)
    paths = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)

    winner, loser = _workflow_app(tmp_path), _workflow_app(tmp_path)
    await _startup_workflow_service(winner)
    await _startup_workflow_service(loser)  # must not raise

    assert winner.state.workflow_service.started is True
    assert loser.state.workflow_service.started is False

    await winner.state.workflow_service.aclose()
    await loser.state.workflow_service.aclose()


@pytest.mark.asyncio
async def test_workflow_service_skipped_when_this_workers_browserbase_lease_was_lost(monkeypatch, tmp_path):
    """A worker that lost Browserbase must not start Workflow even if it would win that lease."""
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    monkeypatch.setenv("MOMOBOT_BROWSERBASE_ENABLED", "true")
    paths = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)

    lost_browserbase = BrowserbaseResearchService(tmp_path / "browserbase-research.sqlite")
    lost_browserbase.lock_contended = True
    assert lost_browserbase.started is False

    app = _workflow_app(tmp_path, browserbase_service=lost_browserbase)
    await _startup_workflow_service(app)

    assert getattr(app.state, "workflow_service", None) is None


@pytest.mark.asyncio
async def test_workflow_service_starts_when_this_workers_browserbase_lease_was_won(monkeypatch, tmp_path):
    """The positive case: owning Browserbase on this worker still lets Workflow start normally."""
    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true")
    monkeypatch.setenv("MOMOBOT_BROWSERBASE_ENABLED", "true")
    paths = SimpleNamespace(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)

    browserbase_service = BrowserbaseResearchService(tmp_path / "browserbase-research.sqlite")
    app = _workflow_app(tmp_path, browserbase_service=browserbase_service)
    await browserbase_service.start()

    await _startup_workflow_service(app)

    assert app.state.workflow_service.started is True
    assert app.state.workflow_service.browser_service is browserbase_service

    await app.state.workflow_service.aclose()
    await browserbase_service.aclose()
