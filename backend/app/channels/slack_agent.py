"""Slack agent sessions: the Agents & tools messaging experience for the Slack channel.

Inert until the Slack app manifest declares the app an agent (``features.agent_view`` plus the
``assistant:write`` scope) and subscribes to the agent events. Until then Slack never sends the
events handled here and direct messages keep the plain eyes + "Working on it..." acknowledgement.

Configuration keys (``channels.slack.agent``):
    - ``enabled``: ``"auto"`` (default), ``true`` or ``false``. ``auto`` switches agent sessions on
      the first time Slack shows the app is an agent: an agent-only event arrives
      (``app_context_changed``, ``agent_session_stopped``, ``agent_session_title_changed``) or the
      startup ``auth.test`` reports the ``assistant:write`` scope. A failed ``processing`` status
      call switches ``auto`` back off and falls back to the plain acknowledgement.
    - ``suggested_prompts``: up to 4 ``{"title", "message"}`` items shown at the top of the DM.
    - ``prompts_title``: heading over the suggested prompts.
    - ``welcome_text``: posted once in an empty DM with the agent (blank = no welcome).
    - ``stopped_text``: posted in the thread when a user presses Stop.

Session lifecycle (https://docs.slack.dev/ai/agent-sessions): a direct message sets the thread's
session to ``processing`` (Slack shows its own "Working..." state and a Stop button), the reply is
posted, then the session goes to ``active`` (or ``suspended`` when the agent asked a question).
Stop marks the in-flight request so its answer is dropped when it arrives, confirms in the thread
and returns the session to ``active``. The Gateway run itself is not cancelled here.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from app.channels.message_bus import PENDING_CLARIFICATION_METADATA_KEY, OutboundMessage

logger = logging.getLogger(__name__)

AGENT_ONLY_EVENTS = frozenset({"app_context_changed", "agent_session_stopped", "agent_session_title_changed"})
AGENT_EVENTS = AGENT_ONLY_EVENTS | {"app_home_opened"}
AGENT_SCOPE = "assistant:write"

DEFAULT_PROMPTS_TITLE = "Try asking"
DEFAULT_SUGGESTED_PROMPTS: tuple[dict[str, str], ...] = (
    {"title": "What can you do?", "message": "What can you help me with?"},
    {"title": "Summarize a thread", "message": "Summarize the thread I paste here and list the open asks with owners."},
    {"title": "Draft a reply", "message": "Help me draft a short, friendly reply to the message I paste here."},
    {"title": "Plan my day", "message": "Turn the list I paste here into a prioritized plan for today."},
)
DEFAULT_WELCOME_TEXT = "Hi! Ask me anything here, or start from one of the suggested prompts above. Each thread is its own session, and you can stop me while I work."
DEFAULT_STOPPED_TEXT = "Stopped. I won't post the answer I was working on. Send a new message when you're ready."

_MAX_TRACKED = 512
_MAX_PROMPTS = 4
_TITLE_LIMIT = 80


def _bounded_set(store: OrderedDict, key: Any, value: Any = None) -> None:
    store[key] = value
    store.move_to_end(key)
    while len(store) > _MAX_TRACKED:
        store.popitem(last=False)


def _parse_enabled(raw: Any) -> str:
    if raw is True or (isinstance(raw, str) and raw.strip().lower() in {"true", "on", "yes"}):
        return "on"
    if raw is False or (isinstance(raw, str) and raw.strip().lower() in {"false", "off", "no"}):
        return "off"
    return "auto"


def _parse_prompts(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return [dict(item) for item in DEFAULT_SUGGESTED_PROMPTS]
    prompts: list[dict[str, str]] = []
    if isinstance(raw, list | tuple):
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            message = str(item.get("message") or "").strip()
            if title and message:
                prompts.append({"title": title, "message": message})
    if len(prompts) > _MAX_PROMPTS:
        logger.warning("[Slack agent] %d suggested prompts configured; Slack shows at most %d, keeping the first %d", len(prompts), _MAX_PROMPTS, _MAX_PROMPTS)
    return prompts[:_MAX_PROMPTS]


def _response_get(response: Any, key: str) -> Any:
    getter = getattr(response, "get", None)
    return getter(key) if callable(getter) else None


def session_title(text: str) -> str:
    """First line of the request, trimmed to a short session title (Slack allows 200)."""
    first_line = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    if len(first_line) <= _TITLE_LIMIT:
        return first_line
    return first_line[: _TITLE_LIMIT - 3].rstrip() + "..."


def scopes_from_response(response: Any) -> set[str]:
    """Read the token's scopes from a Slack response's ``x-oauth-scopes`` header, if present."""
    headers = getattr(response, "headers", None)
    if not isinstance(headers, dict):
        return set()
    for name, value in headers.items():
        if str(name).lower() == "x-oauth-scopes" and value:
            raw = value[0] if isinstance(value, list | tuple) and value else value
            return {scope.strip() for scope in str(raw).split(",") if scope.strip()}
    return set()


class SlackAgentSessions:
    """Agent-session state and Slack calls for one Slack channel adapter.

    Socket Mode events arrive on the slack-sdk thread while replies are sent from the event
    loop, so every state change takes ``_lock``. Every Slack call is best-effort: a failure is
    logged and never raised into the message path.
    """

    def __init__(self, config: Any) -> None:
        config = config if isinstance(config, dict) else {}
        self._mode = _parse_enabled(config.get("enabled", "auto"))
        self._detected = False
        self.prompts_title = str(config.get("prompts_title") or DEFAULT_PROMPTS_TITLE)
        self.suggested_prompts = _parse_prompts(config.get("suggested_prompts"))
        welcome = config.get("welcome_text", DEFAULT_WELCOME_TEXT)
        self.welcome_text = str(welcome).strip() if welcome else ""
        self.stopped_text = str(config.get("stopped_text") or DEFAULT_STOPPED_TEXT)
        self._lock = threading.Lock()
        # (channel, thread_ts) -> message ids still waiting for a final reply in that session.
        self._in_flight: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
        # (channel, message_id) of requests the user stopped; their replies are dropped.
        self._stopped: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._titles: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._welcomed: OrderedDict[str, None] = OrderedDict()
        self._warned_no_stop_subscription = False

    # -- activation ---------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def active(self) -> bool:
        """True when DM requests should open agent sessions."""
        if self._mode == "on":
            return True
        if self._mode == "off":
            return False
        return self._detected

    def note_scopes(self, scopes: set[str]) -> None:
        if self._mode == "auto" and AGENT_SCOPE in scopes and not self._detected:
            self._detected = True
            logger.info("[Slack agent] bot token has %s; agent sessions on", AGENT_SCOPE)

    def note_event(self, event_type: str) -> None:
        if self._mode == "auto" and event_type in AGENT_ONLY_EVENTS and not self._detected:
            self._detected = True
            logger.info("[Slack agent] received %s; agent sessions on", event_type)

    # -- session lifecycle ----------------------------------------------------

    def begin(self, web_client, *, channel_id: str, thread_ts: str, message_id: str, user_id: str, text: str) -> bool:
        """Set the thread's session to ``processing``. False means fall back to the plain acknowledgement."""
        if not web_client or not channel_id or not thread_ts:
            return False
        payload: dict[str, Any] = {"channel_id": channel_id, "thread_ts": thread_ts, "status": "processing"}
        title = session_title(text)
        if title:
            payload["title"] = title
        if user_id:
            payload["initiator_user_id"] = user_id
        if not self._set_status(web_client, payload):
            if self._mode == "auto" and self._detected:
                self._detected = False
                logger.warning("[Slack agent] processing status refused; agent sessions off until Slack shows the app is an agent again")
            return False
        with self._lock:
            ids = self._in_flight.get((channel_id, thread_ts), [])
            if message_id and message_id not in ids:
                ids.append(message_id)
            _bounded_set(self._in_flight, (channel_id, thread_ts), ids)
        return True

    def has_session(self, channel_id: str, thread_ts: str) -> bool:
        """True while this process has a request in flight in the thread's session."""
        with self._lock:
            return (channel_id, thread_ts) in self._in_flight

    def should_drop(self, msg: OutboundMessage) -> bool:
        """True for a reply to a request the user stopped. The final reply clears the mark."""
        message_id = str(msg.metadata.get("message_id") or "")
        if not message_id:
            return False
        key = (msg.chat_id, message_id)
        with self._lock:
            if key not in self._stopped:
                return False
            if msg.is_final:
                self._stopped.pop(key, None)
        return True

    def finish(self, web_client, msg: OutboundMessage) -> None:
        """After a final reply posts, move the session to ``active`` (``suspended`` if the agent asked a question)."""
        if not msg.is_final or not msg.thread_ts:
            return
        key = (msg.chat_id, str(msg.thread_ts))
        message_id = str(msg.metadata.get("message_id") or "")
        with self._lock:
            ids = self._in_flight.get(key)
            if ids is None:
                return
            if message_id in ids:
                ids.remove(message_id)
            elif not message_id and ids:
                # A reply that carries no request id settles the oldest request.
                ids.pop(0)
            else:
                # A late reply to an earlier request (e.g. a follow-up) must not end a newer one.
                return
            if ids:
                return
            self._in_flight.pop(key, None)
        status = "suspended" if msg.metadata.get(PENDING_CLARIFICATION_METADATA_KEY) else "active"
        self._set_status(web_client, {"channel_id": key[0], "thread_ts": key[1], "status": status})

    def stopped(self, web_client, event: dict) -> None:
        """Handle ``agent_session_stopped``: drop in-flight answers, confirm, return the session to active."""
        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or "")
        if not channel_id or not thread_ts:
            return
        with self._lock:
            ids = self._in_flight.pop((channel_id, thread_ts), None)
            if ids is None:
                # Not a session this process opened (or it already finished); never create one here.
                logger.info("[Slack agent] stop for an idle thread channel=%s thread_ts=%s", channel_id, thread_ts)
                return
            for message_id in ids:
                _bounded_set(self._stopped, (channel_id, message_id))
        logger.info("[Slack agent] user stopped %d request(s) in channel=%s thread_ts=%s", len(ids), channel_id, thread_ts)
        self._set_status(web_client, {"channel_id": channel_id, "thread_ts": thread_ts, "status": "active"})
        try:
            web_client.chat_postMessage(channel=channel_id, text=self.stopped_text, thread_ts=thread_ts)
        except Exception:
            logger.exception("[Slack agent] failed to confirm stop in channel=%s", channel_id)

    def title_changed(self, event: dict) -> None:
        """Handle ``agent_session_title_changed``: remember the user's title for the session."""
        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or "")
        title = str(event.get("title") or "")
        if not channel_id or not thread_ts:
            return
        with self._lock:
            _bounded_set(self._titles, (channel_id, thread_ts), title)
        logger.info("[Slack agent] session renamed channel=%s thread_ts=%s", channel_id, thread_ts)

    def title_for(self, channel_id: str, thread_ts: str) -> str | None:
        with self._lock:
            return self._titles.get((channel_id, thread_ts))

    def context_changed(self, event: dict) -> None:
        """Handle ``app_context_changed``. Only logged for now; the context is not sent to the agent."""
        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        entities = context.get("entities") if isinstance(context.get("entities"), list) else []
        logger.debug("[Slack agent] app context changed: %d entities", len(entities))

    # -- welcome and suggested prompts ---------------------------------------

    def home_opened(self, web_client, event: dict) -> None:
        """Handle ``app_home_opened`` on the Messages tab: suggested prompts, then a one-time welcome."""
        if self._mode == "off" or not web_client:
            return
        if event.get("tab") != "messages":
            return
        channel_id = str(event.get("channel") or "")
        if not channel_id.startswith("D"):
            return
        if self.suggested_prompts:
            # Agent apps set DM-level prompts: passing thread_ts makes the call fail.
            payload: dict[str, Any] = {"channel_id": channel_id, "prompts": self.suggested_prompts}
            if self.prompts_title:
                payload["title"] = self.prompts_title
            self._api_call(web_client, "assistant.threads.setSuggestedPrompts", payload)
        if not self.welcome_text:
            return
        with self._lock:
            if channel_id in self._welcomed:
                return
            _bounded_set(self._welcomed, channel_id)
        try:
            history = web_client.conversations_history(channel=channel_id, limit=1)
        except Exception:
            logger.warning("[Slack agent] could not read DM history; skipping welcome in channel=%s", channel_id)
            return
        messages = _response_get(history, "messages")
        if _response_get(history, "ok") is not True or not isinstance(messages, list) or messages:
            return
        try:
            web_client.chat_postMessage(channel=channel_id, text=self.welcome_text)
        except Exception:
            logger.exception("[Slack agent] failed to post welcome in channel=%s", channel_id)

    # -- Slack calls ------------------------------------------------------------

    def _set_status(self, web_client, payload: dict[str, Any]) -> bool:
        response = self._api_call(web_client, "agents.sessions.setStatus", payload)
        if response is None:
            return False
        warning = str(_response_get(response, "warning") or "")
        if "missing_agent_session_stopped_event_subscription" in warning and not self._warned_no_stop_subscription:
            self._warned_no_stop_subscription = True
            logger.warning("[Slack agent] app is not subscribed to agent_session_stopped; users get no Stop button")
        return True

    @staticmethod
    def _api_call(web_client, method: str, payload: dict[str, Any]):
        """POST a JSON Web API call (slack-sdk 3.41 has no typed wrapper for the agent methods)."""
        try:
            response = web_client.api_call(method, json=payload)
        except Exception as exc:
            logger.warning("[Slack agent] %s failed: %s", method, exc)
            return None
        if _response_get(response, "ok") is not True:
            logger.warning("[Slack agent] %s returned error=%s", method, _response_get(response, "error"))
            return None
        return response
