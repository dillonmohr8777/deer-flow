"""Completion proof, not a cancelled Future, releases an ordinary child's owner."""

import asyncio

import pytest

from deerflow.runtime.runs.owned_children import OwnedChild, OwnedChildCompletion, OwnedRunChildren


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executed", "cleanup_reached", "cleanup_failed", "completion", "confirmed"),
    [
        (False, False, False, OwnedChildCompletion.NOT_EXECUTED, True),
        (True, True, False, OwnedChildCompletion.CLEANUP_CONFIRMED, True),
        (True, False, False, OwnedChildCompletion.CLEANUP_UNCONFIRMED, False),
        (True, True, True, OwnedChildCompletion.CLEANUP_UNCONFIRMED, False),
    ],
)
async def test_terminal_proof_controls_owner_release(executed, cleanup_reached, cleanup_failed, completion, confirmed):
    tracker = OwnedRunChildren()
    child = OwnedChild(cancel=lambda: None)
    tracker.register(child)
    assert child.enter()
    child.execution_entered = executed
    child.cleanup_reached = cleanup_reached
    child.cleanup_failed = cleanup_failed
    child.finish()

    assert child.completed.is_set()
    assert child.completion is completion
    assert child.confirmed is confirmed
    if confirmed:
        await tracker.drain(asyncio.Event())
    else:
        with pytest.raises(RuntimeError, match="cleanup is unconfirmed"):
            await tracker.drain(asyncio.Event())


@pytest.mark.asyncio
async def test_bare_completion_event_does_not_establish_cleanup_proof():
    tracker = OwnedRunChildren()
    child = OwnedChild(cancel=lambda: None)
    tracker.register(child)
    child.completed.set()
    assert child.completion is None
    with pytest.raises(RuntimeError, match="cleanup is unconfirmed"):
        await tracker.drain(asyncio.Event())


@pytest.mark.asyncio
async def test_pre_entry_cancellation_proves_no_work_and_fences_late_entry():
    tracker = OwnedRunChildren()
    child = OwnedChild(cancel=lambda: None)
    tracker.register(child)
    child.cancel_before_entry()
    assert child.completion is OwnedChildCompletion.NOT_EXECUTED
    assert not child.enter()
    await tracker.drain(asyncio.Event())


@pytest.mark.asyncio
async def test_drain_keeps_ownership_through_cooperative_cleanup():
    entered, begin_cleanup, cleanup_started, release_cleanup = (asyncio.Event() for _ in range(4))
    cancel_count = 0

    def cancel():
        nonlocal cancel_count
        cancel_count += 1
        begin_cleanup.set()

    tracker = OwnedRunChildren()
    child = OwnedChild(cancel=cancel)
    tracker.register(child)

    async def execute():
        assert child.enter()
        child.execution_entered = True
        entered.set()
        await begin_cleanup.wait()
        child.cleanup_started.set()
        cleanup_started.set()
        await release_cleanup.wait()
        child.cleanup_reached = True
        child.finish()

    execution = asyncio.create_task(execute())
    await entered.wait()
    abort = asyncio.Event()
    abort.set()
    drain = asyncio.create_task(tracker.drain(abort))
    try:
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert not drain.done()
        assert not child.completed.is_set()
        assert child.completion is None
        assert cancel_count == 1
    finally:
        release_cleanup.set()
        await asyncio.wait_for(execution, 2)
        await asyncio.wait_for(drain, 2)
    assert child.completion is OwnedChildCompletion.CLEANUP_CONFIRMED
