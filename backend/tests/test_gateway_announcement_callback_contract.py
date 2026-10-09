"""Fire-and-forget sweep adaptation preserves the confirmed-post API."""

from unittest.mock import AsyncMock

import pytest

from app.gateway.app import _announce_to_exec_without_receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_sweep_callback_waits_for_post_and_discards_only_receipt(monkeypatch, confirmed):
    notifier = AsyncMock(return_value=confirmed)
    monkeypatch.setattr("deerflow.tools.exec_seat_tools.announce_to_exec", notifier)
    assert await _announce_to_exec_without_receipt("synthetic sweep notice") is None
    notifier.assert_awaited_once_with("synthetic sweep notice")
    # The receipt-returning API remains available to scorecard callers.
    assert await notifier("synthetic scorecard notice") is confirmed


@pytest.mark.asyncio
async def test_sweep_callback_propagates_notification_failure(monkeypatch):
    notifier = AsyncMock(side_effect=RuntimeError("synthetic delivery failure"))
    monkeypatch.setattr("deerflow.tools.exec_seat_tools.announce_to_exec", notifier)
    with pytest.raises(RuntimeError, match="synthetic delivery failure"):
        await _announce_to_exec_without_receipt("synthetic sweep notice")
    notifier.assert_awaited_once_with("synthetic sweep notice")
