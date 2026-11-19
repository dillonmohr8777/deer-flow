"""Slack agent sessions (Agents & tools): inert by default, then processing -> reply -> active."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.slack import SlackChannel
from app.channels.slack_agent import DEFAULT_STOPPED_TEXT, SlackAgentSessions, scopes_from_response, session_title

WORKING = ":hourglass_flowing_sand: Working on it..."


class FakeWebClient:
    """Records Slack Web API calls. ``agent=False`` answers the agent methods like a non-agent app."""

    def __init__(self, *, agent: bool = True, history: list | None = None) -> None:
        self.agent = agent
        self.history = [] if history is None else history
        self.api_calls: list[tuple[str, dict]] = []
        self.posts: list[dict] = []
        self.reactions: list[dict] = []

    def api_call(self, method, json=None):
        self.api_calls.append((method, dict(json or {})))
        if not self.agent:
            return {"ok": False, "error": "not_allowed_token_type"}
        return {"ok": True}

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ok": True, "channel": kwargs["channel"], "ts": f"9.{len(self.posts)}"}

    def reactions_add(self, **kwargs):
        self.reactions.append(kwargs)

    def conversations_history(self, **kwargs):
        return {"ok": True, "messages": list(self.history)}

    def statuses(self):
        return [payload for method, payload in self.api_calls if method == "agents.sessions.setStatus"]


def _channel(agent_config=None, *, web=None, **config):
    config = {"allowed_users": ["U1"], **config}
    if agent_config is not None:
        config["agent"] = agent_config
    bus = MessageBus()
    channel = SlackChannel(bus=bus, config=config)
    loop = MagicMock()
    loop.is_running.return_value = True
    loop.call_soon_threadsafe.side_effect = lambda callback, *args: callback(*args)
    channel._loop = loop
    channel._web_client = web or FakeWebClient()
    channel._running = True
    channel._SocketModeResponse = lambda envelope_id: envelope_id
    return bus, channel


def _queued(bus):
    try:
        return bus.get_inbound_nowait()
    except asyncio.QueueEmpty:
        return None


def _socket(channel, event: dict) -> None:
    req = SimpleNamespace(type="events_api", envelope_id="env-1", payload={"team_id": "T1", "event": event})
    channel._on_socket_event(MagicMock(), req)


def _dm(text="summarize the launch notes", ts="1.1", user="U1", channel="D1"):
    return {"type": "message", "channel_type": "im", "user": user, "text": text, "channel": channel, "ts": ts}


def _reply(text="answer", *, thread_ts="1.1", message_id="1.1", **metadata):
    return OutboundMessage(channel_name="slack", chat_id="D1", thread_id="t1", thread_ts=thread_ts, text=text, metadata={"message_id": message_id, **metadata})


# -- inert by default ---------------------------------------------------------


def test_default_config_is_auto_and_off_until_slack_says_agent():
    _, channel = _channel()
    assert channel._agent.mode == "auto"
    assert channel._agent.active is False


def test_dm_today_keeps_plain_acknowledgement_and_makes_no_agent_calls():
    bus, channel = _channel()
    channel._handle_message_event(_dm())
    web = channel._web_client
    assert _queued(bus).text == "summarize the launch notes"
    assert web.api_calls == []
    assert [post["text"] for post in web.posts] == [WORKING]
    assert web.reactions[0]["name"] == "eyes"


@pytest.mark.asyncio
async def test_reply_today_makes_no_agent_calls():
    _, channel = _channel()
    await channel.send(_reply())
    assert channel._web_client.api_calls == []
    assert [post["text"] for post in channel._web_client.posts] == ["answer"]


def test_enabled_false_ignores_agent_events():
    bus, channel = _channel({"enabled": False})
    _socket(channel, {"type": "app_context_changed", "context": {}})
    channel._handle_message_event(_dm())
    assert channel._agent.active is False
    assert channel._web_client.api_calls == []
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]
    assert _queued(bus) is not None


# -- activation ---------------------------------------------------------------


def test_agent_only_event_switches_auto_on():
    _, channel = _channel()
    _socket(channel, {"type": "app_context_changed", "context": {"entities": [{"type": "slack#/types/channel_id", "value": "C1"}]}})
    assert channel._agent.active is True


def test_app_home_opened_alone_does_not_switch_auto_on():
    _, channel = _channel()
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "home"})
    assert channel._agent.active is False


def test_assistant_write_scope_on_startup_auth_test_switches_auto_on():
    class AuthResponse(dict):
        headers = {"X-OAuth-Scopes": "chat:write,im:history,assistant:write"}

    web = MagicMock()
    web.auth_test.return_value = AuthResponse(ok=True, user_id="UBOT")
    channel = SlackChannel(bus=MessageBus(), config={"web_client_factory": lambda **_kwargs: web})
    asyncio.run(channel._initialize_operator_web_client("xoxb-synthetic"))
    assert channel._bot_user_id == "UBOT"
    assert channel._agent.active is True


def test_scopes_from_response_reads_list_or_string_headers():
    assert "assistant:write" in scopes_from_response(SimpleNamespace(headers={"x-oauth-scopes": ["chat:write, assistant:write"]}))
    assert scopes_from_response(SimpleNamespace(headers={"x-oauth-scopes": "chat:write"})) == {"chat:write"}
    assert scopes_from_response(MagicMock()) == set()


# -- processing -> reply -> active -------------------------------------------


def test_dm_in_agent_mode_sets_processing_instead_of_working_post():
    bus, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm())
    web = channel._web_client
    assert _queued(bus).text == "summarize the launch notes"
    assert web.statuses() == [{"channel_id": "D1", "thread_ts": "1.1", "status": "processing", "title": "summarize the launch notes", "initiator_user_id": "U1"}]
    assert web.posts == []
    assert web.reactions[0]["name"] == "eyes"


@pytest.mark.asyncio
async def test_final_reply_posts_then_sets_active():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm())
    await channel._on_outbound(_reply())
    web = channel._web_client
    assert [post["text"] for post in web.posts] == ["answer"]
    assert web.posts[0]["thread_ts"] == "1.1"
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]
    assert channel._agent.has_session("D1", "1.1") is False


@pytest.mark.asyncio
async def test_clarifying_question_sets_suspended():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm())
    await channel._on_outbound(_reply("Which week?", pending_clarification=True))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "suspended"]


@pytest.mark.asyncio
async def test_session_stays_processing_until_every_request_in_the_thread_is_answered():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm(ts="1.1"))
    channel._handle_message_event({**_dm("and the budget", ts="1.2"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply(message_id="1.1"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "processing"]
    await channel._on_outbound(_reply(message_id="1.2"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "processing", "active"]


@pytest.mark.asyncio
async def test_late_reply_to_an_earlier_request_does_not_end_a_newer_one():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm(ts="1.1"))
    await channel._on_outbound(_reply(message_id="1.1"))
    channel._handle_message_event({**_dm("next", ts="1.2"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply("follow-up", message_id="1.1"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "active", "processing"]
    assert channel._agent.has_session("D1", "1.1") is True


def test_command_in_dm_keeps_plain_acknowledgement():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm("what is momobot?"))
    assert channel._web_client.statuses() == []
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]


def test_channel_mention_is_not_an_agent_session():
    _, channel = _channel({"enabled": True}, bot_user_id="UBOT")
    channel._handle_message_event({"type": "app_mention", "user": "U1", "text": "<@UBOT> status?", "channel": "C1", "ts": "3.1"})
    assert channel._web_client.statuses() == []
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]


def test_refused_processing_falls_back_and_turns_auto_off():
    bus, channel = _channel(web=FakeWebClient(agent=False))
    _socket(channel, {"type": "app_context_changed", "context": {}})
    assert channel._agent.active is True
    channel._handle_message_event(_dm())
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]
    assert channel._agent.active is False
    assert _queued(bus) is not None


# -- stop and title --------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_drops_the_answer_confirms_and_sets_active():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm())
    _socket(channel, {"type": "agent_session_stopped", "channel": "D1", "thread_ts": "1.1", "user": "U1", "streaming_message_ts": []})
    web = channel._web_client
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]
    assert web.posts == [{"channel": "D1", "text": DEFAULT_STOPPED_TEXT, "thread_ts": "1.1"}]

    await channel._on_outbound(_reply("late answer"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]

    # The next request in the same thread is answered normally.
    channel._handle_message_event({**_dm("try again", ts="1.3"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply("new answer", message_id="1.3"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "new answer"]
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing", "active"]


def test_stop_for_an_idle_thread_creates_nothing():
    _, channel = _channel({"enabled": True})
    _socket(channel, {"type": "agent_session_stopped", "channel": "D1", "thread_ts": "5.5", "user": "U1", "streaming_message_ts": []})
    assert channel._web_client.api_calls == []
    assert channel._web_client.posts == []


def test_stop_from_a_non_allowed_user_is_ignored():
    _, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm())
    _socket(channel, {"type": "agent_session_stopped", "channel": "D1", "thread_ts": "1.1", "user": "U_OTHER", "streaming_message_ts": []})
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing"]
    assert channel._agent.has_session("D1", "1.1") is True


def test_title_change_is_recorded_without_posting():
    _, channel = _channel()
    _socket(channel, {"type": "agent_session_title_changed", "channel": "D1", "thread_ts": "1.1", "title": "Launch notes", "previous_title": "summarize", "user": "U1", "team_id": "T1"})
    assert channel._agent.title_for("D1", "1.1") == "Launch notes"
    assert channel._agent.active is True
    assert channel._web_client.posts == []


# -- welcome and suggested prompts ------------------------------------------------


def test_messages_tab_sets_prompts_without_thread_ts_and_welcomes_once():
    _, channel = _channel()
    event = {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages", "event_ts": "7.7"}
    _socket(channel, event)
    _socket(channel, event)
    web = channel._web_client
    prompt_calls = [payload for method, payload in web.api_calls if method == "assistant.threads.setSuggestedPrompts"]
    assert len(prompt_calls) == 2
    assert all("thread_ts" not in payload and payload["channel_id"] == "D1" for payload in prompt_calls)
    assert 1 <= len(prompt_calls[0]["prompts"]) <= 4
    assert len(web.posts) == 1
    assert web.posts[0]["channel"] == "D1" and "thread_ts" not in web.posts[0]


def test_no_welcome_when_the_dm_already_has_messages():
    _, channel = _channel(web=FakeWebClient(history=[{"ts": "1.0", "text": "earlier"}]))
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    assert channel._web_client.posts == []


def test_home_tab_and_non_allowed_users_get_nothing():
    _, channel = _channel()
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "home"})
    _socket(channel, {"type": "app_home_opened", "user": "U_OTHER", "channel": "D2", "tab": "messages"})
    assert channel._web_client.api_calls == []
    assert channel._web_client.posts == []


def test_enabled_false_skips_welcome_and_prompts():
    _, channel = _channel({"enabled": False})
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    assert channel._web_client.api_calls == []
    assert channel._web_client.posts == []


# -- config helpers -----------------------------------------------------------------


def test_suggested_prompts_are_validated_and_capped_at_four():
    prompts = [{"title": f"T{i}", "message": f"M{i}"} for i in range(6)] + [{"title": "no message"}, "junk"]
    sessions = SlackAgentSessions({"suggested_prompts": prompts, "welcome_text": ""})
    assert [prompt["title"] for prompt in sessions.suggested_prompts] == ["T0", "T1", "T2", "T3"]
    assert sessions.welcome_text == ""


def test_session_title_uses_first_line_and_stays_short():
    assert session_title("\n  first line\nsecond") == "first line"
    long_title = session_title("x" * 300)
    assert len(long_title) == 80 and long_title.endswith("...")
