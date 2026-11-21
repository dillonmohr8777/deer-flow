"""Slack agent sessions (Agents & tools): inert by default, then processing -> reply -> active."""

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph_sdk.errors import ConflictError
from slack_sdk.errors import SlackApiError

from app.channels.manager import ChannelManager
from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.slack import SlackChannel, SlackSendOutcomeUnknown
from app.channels.slack_agent import DEFAULT_STOPPED_TEXT, SlackAgentSessions, session_title
from app.channels.store import ChannelStore

WORKING = ":hourglass_flowing_sand: Working on it..."


class FakeWebClient:
    """Records Slack Web API calls.

    ``agent=False`` answers the agent methods like a non-agent app; ``errors`` are returned, in
    order, by the next agent-method calls (``""`` means succeed for that call).
    """

    def __init__(self, *, agent: bool = True, history: list | None = None, errors: list[str] | None = None) -> None:
        self.agent = agent
        self.history = [] if history is None else history
        self.errors = list(errors or [])
        self.api_calls: list[tuple[str, dict]] = []
        self.posts: list[dict] = []
        self.uploads: list[dict] = []
        self.reactions: list[dict] = []

    def api_call(self, method, json=None):
        self.api_calls.append((method, dict(json or {})))
        if self.errors:
            err = self.errors.pop(0)
            if err:
                return {"ok": False, "error": err}
            return {"ok": True}
        if not self.agent:
            return {"ok": False, "error": "not_allowed_token_type"}
        return {"ok": True}

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ok": True, "channel": kwargs["channel"], "ts": f"9.{len(self.posts)}"}

    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        return {"ok": True}

    def reactions_add(self, **kwargs):
        self.reactions.append(kwargs)

    def conversations_history(self, **kwargs):
        return {"ok": True, "messages": list(self.history)}

    def statuses(self):
        return [payload for method, payload in self.api_calls if method == "agents.sessions.setStatus"]


def _channel(agent_config=None, *, web=None, loop=None, **config):
    config = {"allowed_users": ["U1"], **config}
    if agent_config is not None:
        config["agent"] = agent_config
    bus = MessageBus()
    channel = SlackChannel(bus=bus, config=config)
    if loop is None:
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


def _socket(channel, event: dict, *, event_id: str | None = None, event_time: int | None = None) -> None:
    payload: dict = {"team_id": "T1", "event": event}
    if event_id is not None:
        payload["event_id"] = event_id
    if event_time is not None:
        payload["event_time"] = event_time
    req = SimpleNamespace(type="events_api", envelope_id="env-1", payload=payload)
    channel._on_socket_event(MagicMock(), req)


def _dm(text="summarize the launch notes", ts="1.1", user="U1", channel="D1"):
    return {"type": "message", "channel_type": "im", "user": user, "text": text, "channel": channel, "ts": ts}


def _reply(text="answer", *, thread_ts="1.1", message_id="1.1", attachments=None, **metadata):
    return OutboundMessage(
        channel_name="slack",
        chat_id="D1",
        thread_id="t1",
        thread_ts=thread_ts,
        text=text,
        attachments=list(attachments or []),
        metadata={"message_id": message_id, **metadata},
    )


def _attachment(name="report.pdf"):
    return ResolvedAttachment(
        virtual_path=f"/mnt/user-data/outputs/{name}",
        actual_path=Path(f"/tmp/{name}"),
        filename=name,
        mime_type="application/pdf",
        size=12,
        is_image=False,
    )


def _stop(thread_ts="1.1", user="U1", *, event_ts: str | None = None):
    event = {"type": "agent_session_stopped", "channel": "D1", "thread_ts": thread_ts, "user": user, "streaming_message_ts": []}
    if event_ts is not None:
        event["event_ts"] = event_ts
    return event


def _context_changed():
    return {"type": "app_context_changed", "context": {"entities": [{"type": "slack#/types/channel_id", "value": "C1"}]}}


async def _accept_dm(bus, channel, event=None):
    """Queue a DM and run the post-dedupe admission hook that ChannelManager invokes."""
    channel._handle_message_event(event or _dm(), team_id="T1")
    inbound = _queued(bus)
    assert inbound is not None
    accepted = await channel.on_inbound_accepted(inbound)
    return inbound, accepted


async def _wait_for(predicate, *, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


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


def test_enabled_false_ignores_all_agent_events_including_stop():
    bus, channel = _channel({"enabled": False})
    _socket(channel, _context_changed())
    _socket(channel, _stop(event_ts="1.5"), event_id="Ev-stop-off")
    _socket(channel, {"type": "agent_session_title_changed", "channel": "D1", "thread_ts": "1.1", "title": "Ignored", "user": "U1"})
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    channel._handle_message_event(_dm())
    assert channel._agent.active is False
    assert channel._agent.title_for("D1", "1.1") is None
    assert channel._web_client.api_calls == []
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]
    assert _queued(bus) is not None


# -- activation ---------------------------------------------------------------


def test_agent_only_event_switches_auto_on():
    _, channel = _channel()
    _socket(channel, _context_changed())
    assert channel._agent.active is True


def test_app_home_opened_alone_does_not_switch_auto_on():
    _, channel = _channel()
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    assert channel._agent.active is False


def test_assistant_write_scope_alone_does_not_switch_auto_on():
    # Apps built for the older assistant view hold assistant:write too; only agent-only events count.
    class AuthResponse(dict):
        headers = {"X-OAuth-Scopes": "chat:write,im:history,assistant:write"}

    web = MagicMock()
    web.auth_test.return_value = AuthResponse(ok=True, user_id="UBOT")
    channel = SlackChannel(bus=MessageBus(), config={"web_client_factory": lambda **_kwargs: web})
    asyncio.run(channel._initialize_operator_web_client("xoxb-synthetic"))
    assert channel._bot_user_id == "UBOT"
    assert channel._agent.active is False


# -- processing -> reply -> active -------------------------------------------


@pytest.mark.asyncio
async def test_dm_in_agent_mode_defers_processing_until_dispatcher_accepts():
    bus, channel = _channel({"enabled": True})
    channel._handle_message_event(_dm(), team_id="T1")
    web = channel._web_client
    # Before dispatcher dedupe accepts the message, no session status or "Working on it..." is sent.
    assert web.statuses() == []
    assert web.posts == []
    assert web.reactions[0]["name"] == "eyes"

    inbound = _queued(bus)
    assert inbound.text == "summarize the launch notes"
    assert await channel.on_inbound_accepted(inbound) is True
    assert web.statuses() == [{"channel_id": "D1", "thread_ts": "1.1", "status": "processing", "title": "summarize the launch notes", "initiator_user_id": "U1"}]
    assert web.posts == []


@pytest.mark.asyncio
async def test_redelivered_dm_after_completion_does_not_reopen_session(tmp_path):
    loop = asyncio.get_running_loop()
    web = FakeWebClient()
    bus, channel = _channel({"enabled": True}, web=web, loop=loop)
    store = ChannelStore(path=tmp_path / "store.json")
    manager = ChannelManager(bus=bus, store=store, channel_getter=lambda name: channel if name == "slack" else None)
    channel._channel_manager = manager
    bus.subscribe_outbound(channel._on_outbound)

    fake_client = MagicMock()
    fake_client.threads = MagicMock()
    fake_client.threads.create = AsyncMock(return_value={"thread_id": "thread-1"})
    fake_client.threads.update = AsyncMock(return_value={})
    fake_client.threads.get = AsyncMock(return_value={"metadata": {}})
    fake_client.runs = MagicMock()
    fake_client.runs.wait = AsyncMock(return_value={"messages": [{"type": "ai", "content": "all set"}]})
    manager._client = fake_client

    await manager.start()
    try:
        _socket(channel, _dm(ts="1.1"))
        await _wait_for(lambda: [s["status"] for s in web.statuses()] == ["processing", "active"])
        assert [post["text"] for post in web.posts] == ["all set"]
        assert channel._agent.has_session("D1", "1.1") is False

        # Slack redelivers the same DM after the first delivery has already settled.
        _socket(channel, _dm(ts="1.1"))
        await asyncio.sleep(0.05)
        await bus.join_inbound()

        assert fake_client.runs.wait.await_count == 1
        assert [s["status"] for s in web.statuses()] == ["processing", "active"]
        assert channel._agent.has_session("D1", "1.1") is False
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_final_reply_posts_then_sets_active():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    await channel._on_outbound(_reply())
    web = channel._web_client
    assert [post["text"] for post in web.posts] == ["answer"]
    assert web.posts[0]["thread_ts"] == "1.1"
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]
    assert channel._agent.has_session("D1", "1.1") is False


@pytest.mark.asyncio
async def test_clarifying_question_sets_suspended():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    await channel._on_outbound(_reply("Which week?", pending_clarification=True))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "suspended"]


@pytest.mark.asyncio
async def test_session_stays_processing_until_every_request_in_the_thread_is_answered():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel, _dm(ts="1.1"))
    await _accept_dm(bus, channel, {**_dm("and the budget", ts="1.2"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply(message_id="1.1"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "processing"]
    await channel._on_outbound(_reply(message_id="1.2"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "processing", "active"]


@pytest.mark.asyncio
async def test_late_reply_to_an_earlier_request_does_not_end_a_newer_one():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel, _dm(ts="1.1"))
    await channel._on_outbound(_reply(message_id="1.1"))
    await _accept_dm(bus, channel, {**_dm("next", ts="1.2"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply("follow-up", message_id="1.1"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "active", "processing"]
    assert channel._agent.has_session("D1", "1.1") is True


@pytest.mark.asyncio
async def test_notice_without_a_request_id_leaves_the_session_processing():
    # Shaped like the approvals adapter's message: no metadata, so no message_id.
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    notice = OutboundMessage(channel_name="slack", chat_id="D1", thread_id="t1", thread_ts="1.1", text="Approve this action?")
    await channel.send(notice)
    assert notice.metadata["slack_delivery"]["state"] == "sent"
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing"]
    assert channel._agent.has_session("D1", "1.1") is True


@pytest.mark.asyncio
async def test_unknown_post_outcome_still_settles_the_session():
    class TimeoutWeb(FakeWebClient):
        def chat_postMessage(self, **kwargs):
            raise TimeoutError("read timed out")

    bus, channel = _channel({"enabled": True}, web=TimeoutWeb())
    await _accept_dm(bus, channel)
    reply = _reply()
    with pytest.raises(SlackSendOutcomeUnknown):
        await channel.send(reply)
    assert reply.metadata["slack_delivery"]["state"] == "outcome_unknown"
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing", "active"]
    assert channel._agent.has_session("D1", "1.1") is False


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


@pytest.mark.asyncio
async def test_refused_processing_falls_back_and_turns_auto_off():
    bus, channel = _channel(web=FakeWebClient(agent=False))
    _socket(channel, _context_changed())
    assert channel._agent.active is True
    inbound, accepted = await _accept_dm(bus, channel)
    assert accepted is True
    assert inbound is not None
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]
    assert channel._agent.active is False
    assert channel._agent.has_session("D1", "1.1") is False


@pytest.mark.asyncio
async def test_not_an_agent_error_raised_by_the_sdk_turns_auto_off():
    class RaisingWeb(FakeWebClient):
        def api_call(self, method, json=None):
            self.api_calls.append((method, dict(json or {})))
            raise SlackApiError("refused", {"ok": False, "error": "missing_scope"})

    bus, channel = _channel(web=RaisingWeb())
    _socket(channel, _context_changed())
    await _accept_dm(bus, channel)
    assert [post["text"] for post in channel._web_client.posts] == [WORKING]
    assert channel._agent.active is False


@pytest.mark.asyncio
async def test_transient_failure_falls_back_once_and_keeps_sessions_on():
    web = FakeWebClient(errors=["ratelimited"])
    bus, channel = _channel(web=web)
    _socket(channel, _context_changed())
    await _accept_dm(bus, channel)
    assert [post["text"] for post in web.posts] == [WORKING]
    assert channel._agent.active is True
    assert channel._agent.has_session("D1", "1.1") is False

    await _accept_dm(bus, channel, _dm("plan the launch week", ts="2.1"))
    assert [status["status"] for status in web.statuses()] == ["processing", "processing"]
    assert [post["text"] for post in web.posts] == [WORKING]
    assert channel._agent.has_session("D1", "2.1") is True


def test_request_is_registered_before_the_processing_call():
    seen: list[bool] = []
    sessions = SlackAgentSessions({"enabled": True})

    class WatchingWeb(FakeWebClient):
        def api_call(self, method, json=None):
            seen.append(sessions.has_session("D1", "1.1"))
            return super().api_call(method, json=json)

    assert sessions.begin(WatchingWeb(), channel_id="D1", thread_ts="1.1", message_id="1.1", user_id="U1", text="hi") is True
    assert seen == [True]


def test_status_calls_for_one_thread_are_serialized():
    entered, release = threading.Event(), threading.Event()

    class SlowWeb(FakeWebClient):
        def api_call(self, method, json=None):
            if (json or {}).get("status") == "processing":
                entered.set()
                release.wait(5)
            return super().api_call(method, json=json)

    web = SlowWeb()
    sessions = SlackAgentSessions({"enabled": True})
    begin = threading.Thread(target=sessions.begin, args=(web,), kwargs={"channel_id": "D1", "thread_ts": "1.1", "message_id": "1.1", "user_id": "U1", "text": "hi"})
    begin.start()
    assert entered.wait(5)
    # A fast reply finishing while the processing call is still out must wait for it.
    finisher = threading.Thread(target=sessions.finish, args=(web, _reply()))
    finisher.start()
    finisher.join(0.2)
    assert finisher.is_alive()
    release.set()
    begin.join(5)
    finisher.join(5)
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]


def test_finish_retries_transient_failure_and_keeps_pending_transition_until_accepted():
    # Automatic retry succeeds on second attempt.
    web = FakeWebClient(errors=["", "ratelimited", ""])
    sessions = SlackAgentSessions({"enabled": True}, finish_retry_delays=(0.0, 0.0), sleep_fn=lambda _: None)
    assert sessions.begin(web, channel_id="D1", thread_ts="1.1", message_id="1.1", user_id="U1", text="hi") is True
    assert sessions.finish(web, _reply()) is True
    assert [s["status"] for s in web.statuses()] == ["processing", "active", "active"]
    assert sessions.has_session("D1", "1.1") is False

    # When all automatic retries fail transiently, the terminal transition stays pending for a later retry.
    web2 = FakeWebClient(errors=["", "ratelimited", "ratelimited"])
    sessions2 = SlackAgentSessions({"enabled": True}, finish_retry_delays=(0.0,), sleep_fn=lambda _: None)
    assert sessions2.begin(web2, channel_id="D1", thread_ts="1.1", message_id="1.1", user_id="U1", text="hi") is True
    assert sessions2.finish(web2, _reply()) is False
    assert sessions2.has_session("D1", "1.1") is True

    # Repeated finalization attempt finds the pending transition and settles once Slack accepts.
    assert sessions2.finish(web2, _reply()) is True
    assert sessions2.has_session("D1", "1.1") is False
    assert [s["status"] for s in web2.statuses()] == ["processing", "active", "active", "active"]


def test_finish_retry_does_not_overwrite_newer_request_processing_status():
    web = FakeWebClient(errors=["", "ratelimited", ""])
    sessions: SlackAgentSessions

    def start_newer_during_backoff(_delay: float) -> None:
        # Newer request starts in the same thread while the earlier finish is backing off.
        assert sessions.begin(web, channel_id="D1", thread_ts="1.1", message_id="1.2", user_id="U1", text="next") is True

    sessions = SlackAgentSessions({"enabled": True}, finish_retry_delays=(0.01,), sleep_fn=start_newer_during_backoff)
    assert sessions.begin(web, channel_id="D1", thread_ts="1.1", message_id="1.1", user_id="U1", text="first") is True
    assert sessions.finish(web, _reply(message_id="1.1")) is False
    # No retry "active" call landed after the newer request's "processing".
    assert [s["status"] for s in web.statuses()] == ["processing", "active", "processing"]
    assert sessions.has_session("D1", "1.1") is True


# -- stop and title --------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_drops_the_answer_confirms_and_sets_active():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    _socket(channel, _stop())
    web = channel._web_client
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]
    assert web.posts == [{"channel": "D1", "text": DEFAULT_STOPPED_TEXT, "thread_ts": "1.1"}]

    await channel._on_outbound(_reply("late answer"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]

    # The next request in the same thread is answered normally.
    await _accept_dm(bus, channel, {**_dm("try again", ts="1.3"), "thread_ts": "1.1"})
    await channel._on_outbound(_reply("new answer", message_id="1.3"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "new answer"]
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing", "active"]


@pytest.mark.asyncio
async def test_stop_after_the_reply_left_the_bus_still_drops_it_and_its_files():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    reply = _reply("late answer", attachments=[_attachment("a.pdf"), _attachment("b.pdf")])
    # The outbound check already passed; Stop lands before the post.
    _socket(channel, _stop())
    await channel.send(reply)
    web = channel._web_client
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]
    assert reply.metadata["slack_delivery"] == {"state": "dropped", "channel": "D1"}
    assert await channel.send_file(reply, reply.attachments[0]) is False
    assert await channel.send_file(reply, reply.attachments[1]) is False
    assert web.uploads == []
    # Marker stays recorded through outbound delivery so repeated/file checks still drop it.
    assert channel._agent.should_drop(_reply("again")) is True


@pytest.mark.asyncio
async def test_stop_during_in_flight_text_post_blocks_all_attachment_uploads():
    class StopDuringPostWeb(FakeWebClient):
        def chat_postMessage(self, **kwargs):
            result = super().chat_postMessage(**kwargs)
            if kwargs["text"] == "here are your files":
                _socket(channel, _stop(event_ts="1.15"), event_id="Ev-mid-post")
            return result

    web = StopDuringPostWeb()
    bus, channel = _channel({"enabled": True}, web=web)
    await _accept_dm(bus, channel)
    reply = _reply("here are your files", attachments=[_attachment("one.pdf"), _attachment("two.pdf")])
    await channel._on_outbound(reply)
    assert reply.metadata["slack_delivery"]["state"] == "sent"
    assert web.uploads == []


@pytest.mark.asyncio
async def test_stop_between_attachments_blocks_remaining_uploads():
    class StopDuringFirstUploadWeb(FakeWebClient):
        def files_upload_v2(self, **kwargs):
            result = super().files_upload_v2(**kwargs)
            if kwargs["filename"] == "one.pdf":
                _socket(channel, _stop(event_ts="1.15"), event_id="Ev-mid-upload")
            return result

    web = StopDuringFirstUploadWeb()
    bus, channel = _channel({"enabled": True}, web=web)
    await _accept_dm(bus, channel)
    reply = _reply("files", attachments=[_attachment("one.pdf"), _attachment("two.pdf")])
    await channel._on_outbound(reply)
    assert [u["filename"] for u in web.uploads] == ["one.pdf"]


@pytest.mark.asyncio
async def test_stop_redelivery_is_deduplicated_and_does_not_affect_newer_request():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel, _dm(ts="1.10"))
    _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-stop-1")
    web = channel._web_client
    assert [status["status"] for status in web.statuses()] == ["processing", "active"]
    assert len(web.posts) == 1

    # Newer request submitted after the user clicked Stop.
    await _accept_dm(bus, channel, {**_dm("fresh ask", ts="1.20"), "thread_ts": "1.10"})
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing"]

    # Redelivered Stop with the same event_id / event_ts is ignored.
    _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-stop-1")
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing"]
    assert len(web.posts) == 1

    await channel._on_outbound(_reply("fresh answer", thread_ts="1.10", message_id="1.20"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "fresh answer"]
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing", "active"]


@pytest.mark.asyncio
async def test_delayed_stop_only_cancels_older_requests_and_keeps_newer_request_processing():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel, _dm(ts="1.10"))
    await _accept_dm(bus, channel, {**_dm("newer ask", ts="1.20"), "thread_ts": "1.10"})

    # Delayed Stop clicked at 1.15 covers 1.10 but NOT 1.20.
    _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-delayed")
    web = channel._web_client
    # Session must stay processing for 1.20.
    assert [status["status"] for status in web.statuses()] == ["processing", "processing"]
    assert channel._agent.has_session("D1", "1.10") is True

    # 1.10's reply is dropped, 1.20's reply is posted and settles the session.
    await channel._on_outbound(_reply("old answer", thread_ts="1.10", message_id="1.10"))
    await channel._on_outbound(_reply("new answer", thread_ts="1.10", message_id="1.20"))
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "new answer"]
    assert [status["status"] for status in web.statuses()] == ["processing", "processing", "active"]


@pytest.mark.asyncio
async def test_delayed_stop_after_older_request_finished_leaves_newer_request_untouched():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel, _dm(ts="1.10"))
    await channel._on_outbound(_reply("first answer", thread_ts="1.10", message_id="1.10"))

    await _accept_dm(bus, channel, {**_dm("second ask", ts="1.20"), "thread_ts": "1.10"})
    _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-late")
    web = channel._web_client
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing"]
    assert [post["text"] for post in web.posts] == ["first answer"]

    await channel._on_outbound(_reply("second answer", thread_ts="1.10", message_id="1.20"))
    assert [post["text"] for post in web.posts] == ["first answer", "second answer"]
    assert [status["status"] for status in web.statuses()] == ["processing", "active", "processing", "active"]


@pytest.mark.asyncio
async def test_stop_cancels_active_gateway_run_and_allows_immediate_followup(tmp_path):
    """Finding 1: Stop cancels the specific Gateway run and frees the thread before confirming."""
    loop = asyncio.get_running_loop()
    web = FakeWebClient()
    bus, channel = _channel({"enabled": True}, web=web, loop=loop)
    store = ChannelStore(path=tmp_path / "store.json")
    manager = ChannelManager(bus=bus, store=store, channel_getter=lambda name: channel if name == "slack" else None)
    channel._channel_manager = manager
    bus.subscribe_outbound(channel._on_outbound)

    first_run_started = asyncio.Event()
    active_runs: dict[str, dict] = {}
    cancel_calls: list[tuple[str, str, bool, str]] = []
    run_counter = 0

    class FakeRuns:
        async def wait(self, thread_id, assistant_id, *, on_run_created=None, metadata=None, **kwargs):
            nonlocal run_counter
            if any(r["thread_id"] == thread_id and r["status"] == "running" for r in active_runs.values()):
                raise ConflictError("Thread is already running a task")
            run_counter += 1
            run_id = f"run-{run_counter}"
            gate = asyncio.Event()
            entry = {"run_id": run_id, "thread_id": thread_id, "status": "running", "metadata": dict(metadata or {}), "gate": gate}
            active_runs[run_id] = entry
            if run_counter == 1:
                first_run_started.set()
                # Simulate real Gateway wait_run: Content-Location is not returned until wait finishes.
                await gate.wait()
                if entry["status"] == "interrupted":
                    return {"status": "interrupted"}
                return {"messages": [{"type": "ai", "content": "should not be posted"}]}
            entry["status"] = "success"
            if on_run_created:
                on_run_created({"run_id": run_id})
            return {"messages": [{"type": "ai", "content": "follow-up answer"}]}

        async def list(self, thread_id, *, headers=None):
            return [{"run_id": r["run_id"], "thread_id": r["thread_id"], "status": r["status"], "metadata": r["metadata"]} for r in active_runs.values() if r["thread_id"] == thread_id]

        async def cancel(self, thread_id, run_id, *, wait=False, action="interrupt", headers=None):
            cancel_calls.append((thread_id, run_id, wait, action))
            entry = active_runs[run_id]
            entry["status"] = "interrupted"
            entry["gate"].set()

        async def get(self, thread_id, run_id, *, headers=None):
            entry = active_runs[run_id]
            return {"run_id": run_id, "thread_id": thread_id, "status": entry["status"]}

    fake_client = MagicMock()
    fake_client.threads = MagicMock()
    fake_client.threads.create = AsyncMock(return_value={"thread_id": "thread-1"})
    fake_client.threads.update = AsyncMock(return_value={})
    fake_client.threads.get = AsyncMock(return_value={"metadata": {}})
    fake_client.runs = FakeRuns()
    manager._client = fake_client

    await manager.start()
    try:
        _socket(channel, _dm("long task", ts="1.10"))
        await asyncio.wait_for(first_run_started.wait(), timeout=3.0)
        assert [s["status"] for s in web.statuses()] == ["processing"]

        _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-cancel-1")
        await _wait_for(lambda: len(web.posts) == 1)

        assert cancel_calls == [("thread-1", "run-1", True, "interrupt")]
        assert [s["status"] for s in web.statuses()] == ["processing", "active"]
        assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]

        # An immediate follow-up in the same thread succeeds without hitting ConflictError / busy.
        _socket(channel, {**_dm("try again", ts="1.20"), "thread_ts": "1.10"})
        await _wait_for(lambda: len(web.posts) == 2 and [s["status"] for s in web.statuses()] == ["processing", "active", "processing", "active"])
        assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "follow-up answer"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_blocks_queued_covered_requests_from_starting(tmp_path):
    loop = asyncio.get_running_loop()
    web = FakeWebClient()
    bus, channel = _channel({"enabled": True}, web=web, loop=loop)
    store = ChannelStore(path=tmp_path / "store.json")
    manager = ChannelManager(bus=bus, store=store, channel_getter=lambda name: channel if name == "slack" else None)
    channel._channel_manager = manager
    bus.subscribe_outbound(channel._on_outbound)

    seen_texts: list[str] = []

    class FakeRuns:
        async def wait(self, thread_id, assistant_id, *, input=None, **kwargs):
            seen_texts.append(input["messages"][0]["content"])
            return {"messages": [{"type": "ai", "content": f"reply:{input['messages'][0]['content']}"}]}

        async def list(self, thread_id, *, headers=None):
            return []

        async def cancel(self, thread_id, run_id, *, wait=False, action="interrupt", headers=None):
            pass

    fake_client = MagicMock()
    fake_client.threads = MagicMock()
    fake_client.threads.create = AsyncMock(return_value={"thread_id": "thread-1"})
    fake_client.threads.update = AsyncMock(return_value={})
    fake_client.threads.get = AsyncMock(return_value={"metadata": {}})
    fake_client.runs = FakeRuns()
    manager._client = fake_client

    # Queue request 1.10 before manager workers start, then Stop at 1.15.
    _socket(channel, _dm("queued work", ts="1.10"))
    await asyncio.sleep(0)
    _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-stop-queued")
    await _wait_for(lambda: len(web.posts) == 1)
    assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]

    await manager.start()
    try:
        # Newer request 1.20 arrives after Stop and should run while 1.10 is dropped before starting.
        _socket(channel, {**_dm("fresh work", ts="1.20"), "thread_ts": "1.10"})
        await _wait_for(lambda: len(web.posts) == 2)
        await bus.join_inbound()

        assert seen_texts == ["fresh work"]
        assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT, "reply:fresh work"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_does_not_confirm_when_gateway_cancel_fails(tmp_path):
    loop = asyncio.get_running_loop()
    web = FakeWebClient()
    bus, channel = _channel({"enabled": True}, web=web, loop=loop)
    store = ChannelStore(path=tmp_path / "store.json")
    manager = ChannelManager(bus=bus, store=store, channel_getter=lambda name: channel if name == "slack" else None)
    channel._channel_manager = manager
    bus.subscribe_outbound(channel._on_outbound)

    run_started = asyncio.Event()
    gate = asyncio.Event()
    fail_cancel = True

    class FlakyCancelRuns:
        async def wait(self, thread_id, assistant_id, *, on_run_created=None, metadata=None, **kwargs):
            run_started.set()
            await gate.wait()
            return {"status": "interrupted"}

        async def list(self, thread_id, *, headers=None):
            return [{"run_id": "run-1", "thread_id": thread_id, "status": "running", "metadata": {"channel_name": "slack", "channel_chat_id": "D1", "channel_message_id": "1.10"}}]

        async def cancel(self, thread_id, run_id, *, wait=False, action="interrupt", headers=None):
            if fail_cancel:
                raise RuntimeError("gateway unavailable")
            gate.set()

    fake_client = MagicMock()
    fake_client.threads = MagicMock()
    fake_client.threads.create = AsyncMock(return_value={"thread_id": "thread-1"})
    fake_client.threads.update = AsyncMock(return_value={})
    fake_client.threads.get = AsyncMock(return_value={"metadata": {}})
    fake_client.runs = FlakyCancelRuns()
    manager._client = fake_client

    await manager.start()
    try:
        _socket(channel, _dm("long task", ts="1.10"))
        await asyncio.wait_for(run_started.wait(), timeout=3.0)

        # First Stop fails on Gateway: must NOT confirm or set active.
        _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-stop-retry")
        await asyncio.sleep(0.05)
        assert web.posts == []
        assert [s["status"] for s in web.statuses()] == ["processing"]
        assert channel._agent.has_session("D1", "1.10") is True

        # Retry after Gateway recovers: now cancels, sets active, and confirms.
        fail_cancel = False
        _socket(channel, _stop(thread_ts="1.10", event_ts="1.15"), event_id="Ev-stop-retry")
        await _wait_for(lambda: len(web.posts) == 1)
        assert [s["status"] for s in web.statuses()] == ["processing", "active"]
        assert [post["text"] for post in web.posts] == [DEFAULT_STOPPED_TEXT]
    finally:
        gate.set()
        await manager.stop()


def test_stop_for_an_untracked_thread_still_returns_it_to_active():
    # e.g. after a restart: Slack shows Stop only while processing, so the session must leave it.
    _, channel = _channel({"enabled": True})
    _socket(channel, _stop(thread_ts="5.5"))
    assert channel._web_client.statuses() == [{"channel_id": "D1", "thread_ts": "5.5", "status": "active"}]
    assert channel._web_client.posts == [{"channel": "D1", "text": DEFAULT_STOPPED_TEXT, "thread_ts": "5.5"}]


@pytest.mark.asyncio
async def test_stop_from_a_non_allowed_user_is_ignored():
    bus, channel = _channel({"enabled": True})
    await _accept_dm(bus, channel)
    _socket(channel, _stop(user="U_OTHER"))
    assert [status["status"] for status in channel._web_client.statuses()] == ["processing"]
    assert channel._agent.has_session("D1", "1.1") is True


def test_title_change_is_recorded_without_posting():
    _, channel = _channel()
    _socket(channel, {"type": "agent_session_title_changed", "channel": "D1", "thread_ts": "1.1", "title": "Launch notes", "previous_title": "summarize", "user": "U1", "team_id": "T1"})
    assert channel._agent.title_for("D1", "1.1") == "Launch notes"
    assert channel._agent.active is True
    assert channel._web_client.posts == []


# -- welcome and suggested prompts ------------------------------------------------


def test_messages_tab_does_nothing_until_sessions_are_active():
    _, channel = _channel()
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    assert channel._web_client.api_calls == []
    assert channel._web_client.posts == []


@pytest.mark.parametrize("agent_config", [None, {"enabled": True}])
def test_messages_tab_sets_prompts_without_thread_ts_and_welcomes_once(agent_config):
    _, channel = _channel(agent_config)
    if agent_config is None:
        _socket(channel, _context_changed())
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
    _, channel = _channel({"enabled": True}, web=FakeWebClient(history=[{"ts": "1.0", "text": "earlier"}]))
    _socket(channel, {"type": "app_home_opened", "user": "U1", "channel": "D1", "tab": "messages"})
    assert channel._web_client.posts == []


def test_home_tab_and_non_allowed_users_get_nothing():
    _, channel = _channel({"enabled": True})
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
