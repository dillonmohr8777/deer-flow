"""Identity-bound tools: the TOOL layer, where the model supplies the ID.

lane/identity-bound-tools. Router and repository proof for these resources
already lives in test_org_isolation_a_projects.py .. g_memory.py and
test_org_isolation_phase2.py; the full inventory with citations is
plans/momentum-identity-bound-tools.md.

This file covers the two agent-callable @tool functions that call straight
into a manager or repository, bypassing the Gateway router entirely, and had
no existing proof at that exact entry point:

- memory_search_tool / memory_update_tool / memory_delete_tool
  (packages/harness/deerflow/agents/memory/tools.py) -- fact_id is
  model-supplied; existing test_memory_tools.py only exercises a mock
  manager, never a real backend, so it cannot prove cross-org isolation.
- batch_status / cancel_batch
  (packages/harness/deerflow/tools/builtins/batch_task_tool.py) --
  batch_id is model-supplied; existing test_batch_task_tool.py never seeds
  two organizations.

Both groups run the actual tool function (".func" / ".coroutine", the same
accessor a bound LangGraph tool node uses) against a real backend, with
identity established the same way a live run establishes it: the
runtime/user_context contextvars org_isolation_fixtures.acting_as() sets,
not a monkeypatched resolver. A model that names another org's id must get
the same response as a made-up id: no data, no write, no distinguishable
error.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, org_world  # noqa: F401

pytestmark = pytest.mark.asyncio

# No storage_user_id key, so resolve_runtime_user_id() falls through to the
# acting_as() contextvar -- exactly like a real run with no workspace header.
_RUNTIME = SimpleNamespace(context={})


# ---------------------------------------------------------------------------
# memory_search_tool / memory_update_tool / memory_delete_tool
# ---------------------------------------------------------------------------


@pytest.fixture()
def deermem_manager(tmp_path, monkeypatch):
    from deerflow.agents.memory import tools as memory_tools
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    monkeypatch.setattr(memory_tools, "get_memory_manager", lambda: manager)
    return manager


def _add_fact(actor, organization_id, content):
    from deerflow.agents.memory.tools import memory_add_tool

    with acting_as(actor, organization_id):
        result = json.loads(memory_add_tool.func(_RUNTIME, content))
    assert "fact_id" in result, result
    return result["fact_id"]


def _search(actor, organization_id, query):
    from deerflow.agents.memory.tools import memory_search_tool

    with acting_as(actor, organization_id):
        return json.loads(memory_search_tool.func(_RUNTIME, query))


async def test_org_b_gets_no_data_and_no_write_from_org_as_fact_through_the_tools(deermem_manager):  # noqa: ARG001
    from deerflow.agents.memory.tools import memory_delete_tool, memory_update_tool

    fact_a = _add_fact(USER_A, ORG_A, "A's private fact, held via the tool layer")
    # Baseline: the exact error shape for an id that never existed anywhere.
    not_found = json.loads(memory_delete_tool.func(_RUNTIME, "made-up-fact-id"))
    assert not_found == {"error": "Fact not found: made-up-fact-id"}

    with acting_as(USER_B, ORG_B):
        assert _search(USER_B, ORG_B, "private fact")["results"] == []
        deleted = json.loads(memory_delete_tool.func(_RUNTIME, fact_a))
        updated = json.loads(memory_update_tool.func(_RUNTIME, fact_a, content="overwritten by B"))

    # Same error shape (an "error" key, the same "Fact not found: <id>" template)
    # as the made-up id above: no existence oracle for a real id in another org.
    assert deleted == {"error": f"Fact not found: {fact_a}"}
    assert updated == {"error": f"Fact not found: {fact_a}"}

    # A's fact is untouched and still searchable by A.
    still_there = {item["id"]: item["content"] for item in _search(USER_A, ORG_A, "private fact")["results"]}
    assert still_there[fact_a] == "A's private fact, held via the tool layer"


async def test_shared_workspace_co_member_uses_the_memory_tools_outsider_gets_nothing(deermem_manager):  # noqa: ARG001
    from deerflow.agents.memory.tools import memory_delete_tool

    fact_s = _add_fact(USER_A, ORG_S, "shared workspace fact via the tool layer")

    # c is an active member of S: the tool surfaces and can act on it.
    comember_hits = {item["id"] for item in _search(USER_C, ORG_S, "shared workspace")["results"]}
    assert fact_s in comember_hits

    # b is not a member of S and has no route to select it as active org here,
    # but even resolved against b's own org the shared fact never appears.
    assert _search(USER_B, ORG_B, "shared workspace")["results"] == []

    with acting_as(USER_C, ORG_S):
        deleted = json.loads(memory_delete_tool.func(_RUNTIME, fact_s))
    assert deleted == {"fact_id": fact_s, "status": "deleted"}


# ---------------------------------------------------------------------------
# batch_status / cancel_batch
# ---------------------------------------------------------------------------


def _seed_batch(session, *, batch_id, user_id, organization_id, thread_id="thread-1", status="running"):
    from deerflow.persistence.subagent_batches.model import SubagentBatchRow

    session.add(
        SubagentBatchRow(
            id=batch_id,
            user_id=user_id,
            organization_id=organization_id,
            thread_id=thread_id,
            submission_key=f"key-{batch_id}",
            title="t",
            subagent_type="general_purpose",
            status=status,
            total_items=1,
            max_live_items=1,
            max_running_items=1,
            max_attempts=1,
            execution_spec={},
        )
    )


@pytest.fixture()
def batch_submitter(org_world):  # noqa: F811
    from deerflow.persistence.subagent_batches.sql import SubagentBatchRepository
    from deerflow.tools.builtins.batch_task_tool import _explicit_batch_submitter

    token = _explicit_batch_submitter.set(SubagentBatchRepository(org_world))
    try:
        yield
    finally:
        _explicit_batch_submitter.reset(token)


async def test_org_b_gets_no_data_and_no_cancel_from_org_as_batch_through_the_tools(org_world, batch_submitter):  # noqa: F811, ARG001
    from deerflow.tools.builtins.batch_task_tool import batch_status, cancel_batch

    async with org_world() as session, session.begin():
        _seed_batch(session, batch_id="batch-a", user_id=USER_A, organization_id=ORG_A)

    with acting_as(USER_B, ORG_B):
        assert await batch_status.coroutine(runtime=_RUNTIME, batch_id="batch-a") == "Batch not found."
        assert await batch_status.coroutine(runtime=_RUNTIME, batch_id="made-up-batch-id") == "Batch not found."
        assert await cancel_batch.coroutine(runtime=_RUNTIME, batch_id="batch-a") == "Batch not found."

    # A's batch is untouched, and the rightful owner still sees and can cancel it.
    with acting_as(USER_A, ORG_A):
        status = json.loads(await batch_status.coroutine(runtime=_RUNTIME, batch_id="batch-a"))
        assert status["status"] == "running"
        assert await cancel_batch.coroutine(runtime=_RUNTIME, batch_id="batch-a") == "Batch batch-a cancellation requested."


async def test_shared_workspace_co_member_reads_its_batch_outsider_gets_not_found(org_world, batch_submitter):  # noqa: F811, ARG001
    from deerflow.tools.builtins.batch_task_tool import batch_status

    async with org_world() as session, session.begin():
        _seed_batch(session, batch_id="batch-s", user_id=STORAGE_S, organization_id=ORG_S, thread_id="thread-s")

    with acting_as(USER_C, ORG_S):
        status = json.loads(await batch_status.coroutine(runtime=_RUNTIME, batch_id="batch-s"))
    assert status["batch_id"] == "batch-s"

    with acting_as(USER_B, ORG_B):
        assert await batch_status.coroutine(runtime=_RUNTIME, batch_id="batch-s") == "Batch not found."
