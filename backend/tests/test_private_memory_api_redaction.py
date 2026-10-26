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
