"""Private staff memory never leaves through the thread APIs, and roles don't partition it."""

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.scope import STAFF_MEMORY_PROVENANCE_KEY, staff_memory_scope
from deerflow.runtime import serialize_channel_values_for_api
from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER, AUTHENTICATED_CONTEXT_MARKER_KEY


def test_api_values_drop_the_private_memory_block():
    memory = HumanMessage(
        id="run-1__memory",
        content="<memory>staff A private fact ZEBRA-41</memory>",
        additional_kwargs={"hide_from_ui": True, STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"},
    )
    values = {"messages": [HumanMessage(id="u1", content="hi"), memory, AIMessage(id="a1", content="hello")]}
    out = serialize_channel_values_for_api(values)
    ids = [m["id"] for m in out["messages"]]
    assert ids == ["u1", "a1"]
    assert "ZEBRA-41" not in str(out)


def test_stream_values_mode_drops_the_private_memory_block():
    from deerflow.runtime import serialize

    memory = HumanMessage(id="r__memory", content="secret", additional_kwargs={"hide_from_ui": True})
    out = serialize({"messages": [memory, AIMessage(id="a", content="ok")]}, mode="values")
    assert [m["id"] for m in out["messages"]] == ["a"]


def _context(role: str, organization_role: str) -> dict:
    return {
        AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
        "actor_user_id": "staff-a",
        "storage_user_id": "agency",
        "organization_id": "org-1",
        "organization_role": organization_role,
        "user_role": role,
    }


def test_promotion_keeps_the_same_memory_bucket():
    before = staff_memory_scope(_context("user", "member"), agent_name="momobot-max")
    after = staff_memory_scope(_context("admin", "owner"), agent_name="momobot-max")
    assert before is not None and after is not None
    assert before.user_id == after.user_id


def test_other_actor_or_agent_still_gets_a_different_bucket():
    base = staff_memory_scope(_context("user", "member"), agent_name="momobot-max")
    other_agent = staff_memory_scope(_context("user", "member"), agent_name="vhin-max-plus")
    other_actor = staff_memory_scope({**_context("user", "member"), "actor_user_id": "staff-b"}, agent_name="momobot-max")
    assert len({base.user_id, other_agent.user_id, other_actor.user_id}) == 3


def test_stream_updates_mode_drops_the_private_memory_block():
    from langchain_core.messages import SystemMessage

    from deerflow.runtime import serialize

    memory = HumanMessage(id="r__memory", content="ZEBRA-41", additional_kwargs={"hide_from_ui": True, STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"})
    reminder = SystemMessage(id="r", content="<system-reminder>date</system-reminder>", additional_kwargs={"dynamic_context_reminder": True, STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"})
    out = serialize({"DynamicContextMiddleware.before_agent": {"messages": [reminder, memory]}}, mode="updates")
    assert "ZEBRA-41" not in str(out)
    assert "staff-v1-abc" not in str(out)
    assert [m["id"] for m in out["DynamicContextMiddleware.before_agent"]["messages"]] == ["r"]


def test_stream_messages_mode_blanks_a_private_memory_chunk():
    from deerflow.runtime import serialize

    memory = HumanMessage(id="r__memory", content="ZEBRA-41", additional_kwargs={"hide_from_ui": True})
    out = serialize((memory, {"langgraph_node": "x"}), mode="messages")
    assert "ZEBRA-41" not in str(out)


def test_api_values_hide_the_scope_hash_on_the_visible_reminder():
    from langchain_core.messages import SystemMessage

    reminder = SystemMessage(id="r", content="date", additional_kwargs={"dynamic_context_reminder": True, STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"})
    out = serialize_channel_values_for_api({"messages": [reminder]})
    assert "staff-v1-abc" not in str(out)
    assert out["messages"][0]["additional_kwargs"]["dynamic_context_reminder"] is True


def test_stream_messages_mode_keeps_the_frame_shape():
    from deerflow.runtime import serialize

    memory = HumanMessage(id="r__memory", content="ZEBRA-41", additional_kwargs={"hide_from_ui": True})
    out = serialize((memory, {"langgraph_node": "x"}), mode="messages")
    assert isinstance(out, list) and len(out) == 2
    assert out[0]["id"] == "r__memory" and out[0]["content"] == ""
    assert out[1] == {"langgraph_node": "x"}
    ai = serialize((AIMessage(id="a", content="ok"), {}), mode="messages")
    assert ai[0]["content"] == "ok" and ai[1] == {}


def test_debug_and_checkpoint_output_drop_the_staff_scope_binding():
    from deerflow.agents.memory.scope import STAFF_MEMORY_SCOPE_KEY
    from deerflow.runtime import serialize

    scope = staff_memory_scope(_context("user", "member"), agent_name="momobot-max")
    payload = {"type": "checkpoint", "payload": {"config": {"context": {STAFF_MEMORY_SCOPE_KEY: scope, "thread_id": "t"}}}}
    out = serialize(payload, mode="debug")
    assert scope.user_id not in str(out) and "staff-a" not in str(out)
    assert out["payload"]["config"]["context"] == {"thread_id": "t"}


def test_run_events_api_drops_private_memory_from_run_output():
    from app.gateway.routers.thread_runs import _public_run_events

    memory = HumanMessage(id="r__memory", content="ZEBRA-41", additional_kwargs={STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"})
    events = [{"event_type": "run.end", "content": {"messages": [HumanMessage(id="u", content="hi"), memory, AIMessage(id="a", content="ok")]}, "metadata": {"status": "success"}}]
    out = _public_run_events(events)
    assert "ZEBRA-41" not in str(out) and "staff-v1-abc" not in str(out)
    assert [m["id"] for m in out[0]["content"]["messages"]] == ["u", "a"]
    assert out[0]["metadata"] == {"status": "success"}


def test_persisted_run_output_is_scrubbed_before_the_store_stringifies_it():
    """The DB and JSONL stores json.dumps(..., default=str); scrubbing after that is too late."""
    import asyncio
    import json

    from app.gateway.routers.thread_runs import _public_run_events
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    memory = HumanMessage(id="r1__memory", content="ZEBRA-41", additional_kwargs={STAFF_MEMORY_PROVENANCE_KEY: "staff-v1-abc"})
    journal._put(event_type="run.end", category="outputs", content={"messages": [HumanMessage(id="u", content="hi"), memory, AIMessage(id="a", content="ok")]})
    asyncio.run(journal.flush())
    events = asyncio.run(store.list_events("t1", "r1"))
    persisted = [json.loads(json.dumps(event, default=str)) for event in events]  # what DbRunEventStore reads back
    assert "ZEBRA-41" not in str(persisted) and "staff-v1-abc" not in str(persisted)
    assert [m["id"] for m in _public_run_events(persisted)[0]["content"]["messages"]] == ["u", "a"]


def test_legacy_stringified_memory_rows_are_dropped_on_read():
    from app.gateway.routers.thread_runs import _public_run_events

    legacy = {"event_type": "run.end", "content": {"messages": [str(HumanMessage(id="u", content="hi")), str(HumanMessage(id="r0__memory", content="ZEBRA-41"))]}}
    out = _public_run_events([legacy])
    assert "ZEBRA-41" not in str(out)
    assert len(out[0]["content"]["messages"]) == 1
