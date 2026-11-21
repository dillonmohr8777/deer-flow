"""Slack agent sessions: the Agents & tools messaging experience for the Slack channel.

Inert until the Slack app manifest declares the app an agent (``features.agent_view`` plus the
``assistant:write`` scope) and subscribes to the agent events. Until then Slack never sends the
events handled here and direct messages keep the plain eyes + "Working on it..." acknowledgement.

Configuration keys (``channels.slack.agent``):
    - ``enabled``: ``"auto"`` (default), ``true`` or ``false``. ``auto`` switches agent sessions on
      the first time an agent-only event arrives (``app_context_changed``,
      ``agent_session_stopped``, ``agent_session_title_changed``); Slack sends those only to apps
      declared as agents. The ``assistant:write`` scope alone is not a signal, because apps built
      for the older assistant view hold it too. Set ``true`` to switch sessions on from startup.
      In ``auto``, a ``processing`` call refused because the app is not an agent
      (``not_allowed_token_type``, ``not_agent_app``, ``missing_scope``, ``feature_disabled``)
      switches sessions back off; any other failure (rate limit, timeout, network) only falls
      back to the plain acknowledgement for that one message.
    - ``suggested_prompts``: up to 4 ``{"title", "message"}`` items shown at the top of the DM.
    - ``prompts_title``: heading over the suggested prompts.
    - ``welcome_text``: posted once in an empty DM with the agent (blank = no welcome).
    - ``stopped_text``: posted in the thread when a user presses Stop.

Session lifecycle (https://docs.slack.dev/ai/agent-sessions): a direct message accepted past the
dispatcher's dedupe gate sets the thread's session to ``processing`` (Slack shows its own
"Working..." state and a Stop button), the full outbound delivery (text + attachments) completes,
then the session goes to ``active`` (or ``suspended`` when the agent asked a question). Terminal
transitions stay pending until Slack accepts them and schedule background retries honoring Slack's
``Retry-After`` header independently of reply delivery, cancelling the retry as soon as newer work
supersedes it. Only a reply that carries the request's ``message_id`` settles it; notices such as
approval prompts carry none and leave the session alone. Stop is deduplicated, scoped by event
timestamp to requests already present when the user clicked Stop (never clobbering newer in-flight
or completed turns), routes cancellation to the specific Gateway runs and queued requests, and
confirms in the thread only after cancellation is accepted. Stopped request markers stay recorded
through outbound delivery so both text posts and attachment uploads drop them.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

from app.channels.message_bus import PENDING_CLARIFICATION_METADATA_KEY, OutboundMessage

logger = logging.getLogger(__name__)

AGENT_ONLY_EVENTS = frozenset({"app_context_changed", "agent_session_stopped", "agent_session_title_changed"})
AGENT_EVENTS = AGENT_ONLY_EVENTS | {"app_home_opened"}
# setStatus errors that mean "this app is not an agent here"; anything else is treated as transient.
NOT_AN_AGENT_ERRORS = frozenset({"not_allowed_token_type", "not_agent_app", "missing_scope", "feature_disabled"})

DEFAULT_PROMPTS_TITLE = "Try asking"
DEFAULT_SUGGESTED_PROMPTS: tuple[dict[str, str], ...] = (
    {"title": "What can you do?", "message": "What can you help me with?"},
    {"title": "Summarize a thread", "message": "Summarize the thread I paste here and list the open asks with owners."},
    {"title": "Draft a reply", "message": "Help me draft a short, friendly reply to the message I paste here."},
    {"title": "Plan my day", "message": "Turn the list I paste here into a prioritized plan for today."},
)
DEFAULT_WELCOME_TEXT = "Hi! Ask me anything here, or start from one of the suggested prompts above. Each thread is its own session, and you can stop me while I work."
DEFAULT_STOPPED_TEXT = "Stopped. I won't post the answer I was working on. Send a new message when you're ready."
DEFAULT_FINISH_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
MAX_RETRY_AFTER_SECONDS = 300.0

_MAX_TRACKED = 512
_MAX_PROMPTS = 4
_TITLE_LIMIT = 80


def _bounded_set(store: OrderedDict, key: Any, value: Any = None) -> None:
    store[key] = value
    store.move_to_end(key)
    while len(store) > _MAX_TRACKED:
        store.popitem(last=False)


def _make_daemon_timer(delay: float, callback: Callable[[], None]) -> threading.Timer:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    return timer


def parse_slack_ts(value: Any) -> Decimal | None:
    """Parse a Slack timestamp (e.g. ``1700000001.000100``) without float rounding."""
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _extract_retry_after(response: Any) -> float | None:
    """Read Slack's ``Retry-After`` header (seconds or HTTP-date) from a SlackResponse or mapping."""
    if response is None:
        return None
    raw: Any = None
    headers = getattr(response, "headers", None)
    if isinstance(headers, Mapping):
        for header_name, value in headers.items():
            if str(header_name).lower() == "retry-after":
                raw = value
                break
    if raw is None:
        raw = _response_get(response, "retry_after")
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else None
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            target = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        seconds = max(0.0, (target - datetime.now(UTC)).total_seconds())
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


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


@dataclass(frozen=True, slots=True)
class StopPlan:
    """Snapshot of one deduplicated, timestamp-scoped ``agent_session_stopped`` event."""

    channel_id: str
    thread_ts: str
    stop_ts: Decimal | None
    covered_ids: tuple[str, ...]
    remaining_ids: tuple[str, ...]
    dedupe_keys: tuple[tuple[str, ...], ...]
    token: object


class SlackAgentSessions:
    """Agent-session state and Slack calls for one Slack channel adapter.

    Socket Mode events arrive on the slack-sdk thread while replies are sent from the event
    loop, so state changes take ``_lock``. Status changes for one thread are serialized by that
    thread's own lock (taken before ``_lock``, held across the Slack call), so ``processing`` can
    never land after the ``active`` of a fast reply. Every Slack call is best-effort: a failure is
    logged and never raised into the message path.
    """

    def __init__(
        self,
        config: Any,
        *,
        finish_retry_delays: tuple[float, ...] = DEFAULT_FINISH_RETRY_DELAYS,
        timer_factory: Callable[[float, Callable[[], None]], Any] = _make_daemon_timer,
    ) -> None:
        config = config if isinstance(config, dict) else {}
        self._mode = _parse_enabled(config.get("enabled", "auto"))
        self._detected = False
        self.prompts_title = str(config.get("prompts_title") or DEFAULT_PROMPTS_TITLE)
        self.suggested_prompts = _parse_prompts(config.get("suggested_prompts"))
        welcome = config.get("welcome_text", DEFAULT_WELCOME_TEXT)
        self.welcome_text = str(welcome).strip() if welcome else ""
        self.stopped_text = str(config.get("stopped_text") or DEFAULT_STOPPED_TEXT)
        self._finish_retry_delays = tuple(finish_retry_delays)
        self._timer_factory = timer_factory
        self._closed = False
        self._lock = threading.Lock()
        # (channel, thread_ts) -> lock serializing that thread's status calls.
        self._thread_locks: OrderedDict[tuple[str, str], threading.Lock] = OrderedDict()
        # (channel, thread_ts) -> message ids still waiting for a final reply in that session.
        self._in_flight: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
        # (channel, thread_ts) -> highest completed request timestamp so older Stops cannot clobber newer turns.
        self._latest_completed_ts: OrderedDict[tuple[str, str], Decimal] = OrderedDict()
        # (channel, thread_ts) -> (owner_id, terminal_status) pending Slack acceptance.
        self._pending_finish: OrderedDict[tuple[str, str], tuple[str, str]] = OrderedDict()
        # (channel, thread_ts) -> (pending_token, scheduled_timer) for background terminal-status retries.
        self._retry_timers: dict[tuple[str, str], tuple[tuple[str, str], Any]] = {}
        # (channel, message_id) of requests the user stopped; retained through outbound delivery.
        self._stopped: OrderedDict[tuple[str, str], None] = OrderedDict()
        # (channel, message_id) -> active cancellation refcount while Gateway cancel is in flight.
        self._stopping_counts: dict[tuple[str, str], int] = {}
        # (channel, thread_ts) -> highest accepted Stop event timestamp.
        self._stop_watermarks: OrderedDict[tuple[str, str], Decimal] = OrderedDict()
        # (channel, thread_ts) -> in-flight (token, stop_ts) pairs awaiting Gateway acceptance.
        self._pending_stop_watermarks: dict[tuple[str, str], list[tuple[object, Decimal]]] = {}
        # Deduplication keys for accepted and currently-cancelling Stop deliveries.
        self._seen_stops: OrderedDict[tuple[str, ...], None] = OrderedDict()
        self._in_progress_stops: set[tuple[str, ...]] = set()
        self._titles: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._welcomed: OrderedDict[str, None] = OrderedDict()
        self._warned_no_stop_subscription = False

    def close(self) -> None:
        """Cancel any pending background terminal-status retry timers."""
        with self._lock:
            self._closed = True
            timers = list(self._retry_timers.values())
            self._retry_timers.clear()
        for _, timer in timers:
            try:
                timer.cancel()
            except Exception:
                logger.debug("[Slack agent] failed cancelling retry timer on close", exc_info=True)

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

    def note_event(self, event_type: str) -> None:
        if self._mode == "auto" and event_type in AGENT_ONLY_EVENTS and not self._detected:
            self._detected = True
            logger.info("[Slack agent] received %s; agent sessions on", event_type)

    # -- session lifecycle ----------------------------------------------------

    def _thread_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            lock = self._thread_locks.get(key) or threading.Lock()
            _bounded_set(self._thread_locks, key, lock)
            return lock

    def _cancel_retry_timer_locked(self, key: tuple[str, str]) -> None:
        entry = self._retry_timers.pop(key, None)
        if entry is None:
            return
        _, timer = entry
        try:
            timer.cancel()
        except Exception:
            logger.debug("[Slack agent] failed cancelling scheduled terminal retry for %s", key, exc_info=True)

    def _record_completed_ts_locked(self, key: tuple[str, str], message_id: str) -> None:
        req_ts = parse_slack_ts(message_id)
        if req_ts is None:
            return
        existing = self._latest_completed_ts.get(key)
        if existing is None or req_ts > existing:
            _bounded_set(self._latest_completed_ts, key, req_ts)

    def _is_covered_by_stop_locked(self, channel_id: str, thread_ts: str, message_id: str) -> bool:
        if not channel_id or not message_id:
            return False
        msg_key = (channel_id, message_id)
        if msg_key in self._stopped or msg_key in self._stopping_counts:
            return True
        if not thread_ts:
            return False
        msg_ts = parse_slack_ts(message_id)
        if msg_ts is None:
            return False
        thread_key = (channel_id, thread_ts)
        watermark = self._stop_watermarks.get(thread_key)
        if watermark is not None and msg_ts <= watermark:
            return True
        return any(msg_ts <= pending_ts for _, pending_ts in self._pending_stop_watermarks.get(thread_key, ()))

    def is_stopped_or_covered(self, channel_id: str, thread_ts: str, message_id: str) -> bool:
        """True when *message_id* was stopped directly or falls at/before an accepted/in-flight Stop."""
        with self._lock:
            return self._is_covered_by_stop_locked(channel_id, thread_ts, message_id)

    def begin(self, web_client, *, channel_id: str, thread_ts: str, message_id: str, user_id: str, text: str) -> bool:
        """Set the thread's session to ``processing``. False means fall back to the plain acknowledgement."""
        # Without a request id the reply could never settle the session, so none is opened.
        if self._mode == "off" or not web_client or not channel_id or not thread_ts or not message_id:
            return False
        key = (channel_id, thread_ts)
        payload: dict[str, Any] = {"channel_id": channel_id, "thread_ts": thread_ts, "status": "processing"}
        title = session_title(text)
        if title:
            payload["title"] = title
        if user_id:
            payload["initiator_user_id"] = user_id
        with self._thread_lock(key):
            # Registered before the call, so a Stop or a reply racing the call finds the request.
            with self._lock:
                if self._is_covered_by_stop_locked(channel_id, thread_ts, message_id):
                    return False
                ids = self._in_flight.get(key, [])
                added = message_id not in ids
                if added:
                    ids.append(message_id)
                _bounded_set(self._in_flight, key, ids)
            ok, error, _retry_after = self._set_status(web_client, payload)
            if ok:
                with self._lock:
                    self._pending_finish.pop(key, None)
                    self._cancel_retry_timer_locked(key)
                return True
            with self._lock:
                ids = self._in_flight.get(key)
                if ids is not None:
                    if added and message_id in ids:
                        ids.remove(message_id)
                    if not ids:
                        self._in_flight.pop(key, None)
        if self._mode == "auto" and self._detected and error in NOT_AN_AGENT_ERRORS:
            self._detected = False
            logger.warning("[Slack agent] processing status refused (%s); agent sessions off until Slack shows the app is an agent again", error)
        return False

    def has_session(self, channel_id: str, thread_ts: str) -> bool:
        """True while this process has a request in flight or a terminal status pending in the thread."""
        key = (channel_id, thread_ts)
        with self._lock:
            return key in self._in_flight or key in self._pending_finish

    def should_drop(self, msg: OutboundMessage) -> bool:
        """True for a reply to a request the user stopped.

        The marker stays recorded in the bounded LRU through the entire outbound
        delivery so attachment uploads after the text post see it too.
        """
        message_id = str(msg.metadata.get("message_id") or "")
        if not message_id:
            return False
        return self.is_stopped_or_covered(msg.chat_id, str(msg.thread_ts or ""), message_id)

    def _attempt_terminal_status_locked(
        self,
        web_client,
        key: tuple[str, str],
        *,
        pending_token: tuple[str, str],
        status: str,
    ) -> tuple[str, float | None]:
        """Attempt one ``setStatus`` call while ``_thread_lock(key)`` is already held.

        Returns ``(outcome, retry_after)`` where outcome is ``"accepted"``, ``"superseded"``,
        ``"permanent_error"``, or ``"retry"``.
        """
        with self._lock:
            if self._in_flight.get(key) or self._pending_finish.get(key) != pending_token:
                return "superseded", None
        ok, error, retry_after = self._set_status(web_client, {"channel_id": key[0], "thread_ts": key[1], "status": status})
        if ok:
            with self._lock:
                if self._pending_finish.get(key) == pending_token:
                    self._pending_finish.pop(key, None)
                    self._cancel_retry_timer_locked(key)
            return "accepted", None
        if error in NOT_AN_AGENT_ERRORS:
            with self._lock:
                if self._pending_finish.get(key) == pending_token:
                    self._pending_finish.pop(key, None)
                    self._cancel_retry_timer_locked(key)
            if self._mode == "auto" and self._detected:
                self._detected = False
                logger.warning("[Slack agent] %s status refused (%s); agent sessions off until Slack shows the app is an agent again", status, error)
            return "permanent_error", None
        return "retry", retry_after

    def _schedule_terminal_retry(
        self,
        web_client,
        key: tuple[str, str],
        *,
        pending_token: tuple[str, str],
        status: str,
        attempt: int,
        retry_after: float | None,
    ) -> bool:
        """Schedule an asynchronous terminal-status retry honoring Slack's ``Retry-After`` header."""
        if attempt >= len(self._finish_retry_delays):
            return False
        delay = retry_after if retry_after is not None else self._finish_retry_delays[attempt]
        with self._lock:
            if self._closed or self._in_flight.get(key) or self._pending_finish.get(key) != pending_token:
                return False
            self._cancel_retry_timer_locked(key)
            timer = self._timer_factory(
                delay,
                lambda: self._run_scheduled_terminal_retry(
                    web_client,
                    key,
                    pending_token=pending_token,
                    status=status,
                    attempt=attempt,
                ),
            )
            self._retry_timers[key] = (pending_token, timer)
        try:
            timer.start()
        except Exception:
            with self._lock:
                if self._retry_timers.get(key) == (pending_token, timer):
                    self._retry_timers.pop(key, None)
            logger.exception("[Slack agent] failed starting terminal-status retry timer for channel=%s thread_ts=%s", key[0], key[1])
            return False
        return True

    def _run_scheduled_terminal_retry(
        self,
        web_client,
        key: tuple[str, str],
        *,
        pending_token: tuple[str, str],
        status: str,
        attempt: int,
    ) -> None:
        with self._thread_lock(key):
            with self._lock:
                if self._closed:
                    return
                entry = self._retry_timers.get(key)
                if entry is not None and entry[0] == pending_token:
                    self._retry_timers.pop(key, None)
            outcome, retry_after = self._attempt_terminal_status_locked(web_client, key, pending_token=pending_token, status=status)
        if outcome == "retry":
            self._schedule_terminal_retry(
                web_client,
                key,
                pending_token=pending_token,
                status=status,
                attempt=attempt + 1,
                retry_after=retry_after,
            )

    def finish(self, web_client, msg: OutboundMessage) -> bool:
        """After outbound delivery, move the session to ``active`` (``suspended`` if clarifying).

        Only a reply carrying the request's ``message_id`` settles it: a late reply to an earlier
        request, or a notice without an id (approval prompts), leaves a newer request processing.
        A transient failure keeps the transition pending and schedules a background retry honoring
        ``Retry-After`` without blocking reply delivery or overwriting a newer request.
        """
        if not web_client or not msg.is_final or not msg.thread_ts:
            return False
        message_id = str(msg.metadata.get("message_id") or "")
        if not message_id:
            return False
        key = (msg.chat_id, str(msg.thread_ts))
        desired_status = "suspended" if msg.metadata.get(PENDING_CLARIFICATION_METADATA_KEY) else "active"
        pending_token: tuple[str, str] | None = None
        with self._thread_lock(key):
            with self._lock:
                if self._is_covered_by_stop_locked(msg.chat_id, str(msg.thread_ts), message_id):
                    return False
                ids = self._in_flight.get(key)
                if ids is not None and message_id in ids:
                    ids.remove(message_id)
                    self._record_completed_ts_locked(key, message_id)
                    if ids:
                        return True
                    self._in_flight.pop(key, None)
                    pending_token = (message_id, desired_status)
                    _bounded_set(self._pending_finish, key, pending_token)
                    self._cancel_retry_timer_locked(key)
                else:
                    existing = self._pending_finish.get(key)
                    if self._in_flight.get(key) or existing is None or existing[0] != message_id:
                        return False
                    self._record_completed_ts_locked(key, message_id)
                    pending_token = existing
                    desired_status = existing[1]
                    self._cancel_retry_timer_locked(key)
            outcome, retry_after = self._attempt_terminal_status_locked(web_client, key, pending_token=pending_token, status=desired_status)
        if outcome == "accepted":
            return True
        if outcome == "retry":
            self._schedule_terminal_retry(
                web_client,
                key,
                pending_token=pending_token,
                status=desired_status,
                attempt=0,
                retry_after=retry_after,
            )
        return False

    def prepare_stop(
        self,
        event: dict,
        *,
        event_id: str | None = None,
        event_time: Any = None,
    ) -> StopPlan | None:
        """Deduplicate an ``agent_session_stopped`` event and select requests covered by its timestamp.

        Returns ``None`` when agent sessions are explicitly off, the event is missing channel/thread,
        or this Stop delivery was already processed or is currently cancelling.
        """
        if self._mode == "off":
            return None
        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or "")
        if not channel_id or not thread_ts:
            return None

        raw_event_ts = str(event.get("event_ts") or event.get("ts") or "").strip()
        stop_ts = parse_slack_ts(raw_event_ts)
        if stop_ts is None and event_time is not None:
            stop_ts = parse_slack_ts(event_time)

        dedupe_keys_list: list[tuple[str, ...]] = []
        clean_event_id = str(event_id or "").strip()
        if clean_event_id:
            dedupe_keys_list.append(("event_id", clean_event_id))
        if raw_event_ts:
            dedupe_keys_list.append(("event_ts", channel_id, thread_ts, raw_event_ts))
        dedupe_keys = tuple(dedupe_keys_list)

        key = (channel_id, thread_ts)
        token = object()
        with self._lock:
            if any(dk in self._seen_stops or dk in self._in_progress_stops for dk in dedupe_keys):
                logger.debug("[Slack agent] ignoring duplicate stop event channel=%s thread_ts=%s", channel_id, thread_ts)
                return None

            ids = list(self._in_flight.get(key, ()))
            covered: list[str] = []
            remaining: list[str] = []
            for message_id in ids:
                if self._request_covered_by_stop(message_id, stop_ts):
                    covered.append(message_id)
                else:
                    remaining.append(message_id)

            for dk in dedupe_keys:
                self._in_progress_stops.add(dk)
            for message_id in covered:
                msg_key = (channel_id, message_id)
                self._stopping_counts[msg_key] = self._stopping_counts.get(msg_key, 0) + 1
            if stop_ts is not None:
                self._pending_stop_watermarks.setdefault(key, []).append((token, stop_ts))

        return StopPlan(
            channel_id=channel_id,
            thread_ts=thread_ts,
            stop_ts=stop_ts,
            covered_ids=tuple(covered),
            remaining_ids=tuple(remaining),
            dedupe_keys=dedupe_keys,
            token=token,
        )

    @staticmethod
    def _request_covered_by_stop(message_id: str, stop_ts: Decimal | None) -> bool:
        if stop_ts is None:
            return True
        req_ts = parse_slack_ts(message_id)
        if req_ts is None:
            return True
        return req_ts <= stop_ts

    def complete_stop(self, web_client, plan: StopPlan, *, accepted: bool) -> bool:
        """Finalize a prepared Stop after Gateway cancellation succeeds or fails."""
        key = (plan.channel_id, plan.thread_ts)
        with self._lock:
            for dk in plan.dedupe_keys:
                self._in_progress_stops.discard(dk)
            for message_id in plan.covered_ids:
                msg_key = (plan.channel_id, message_id)
                count = self._stopping_counts.get(msg_key, 0) - 1
                if count <= 0:
                    self._stopping_counts.pop(msg_key, None)
                else:
                    self._stopping_counts[msg_key] = count
            pending_wms = self._pending_stop_watermarks.get(key)
            if pending_wms is not None:
                pending_wms = [(tok, ts) for tok, ts in pending_wms if tok is not plan.token]
                if pending_wms:
                    self._pending_stop_watermarks[key] = pending_wms
                else:
                    self._pending_stop_watermarks.pop(key, None)

            if not accepted:
                logger.warning(
                    "[Slack agent] cancellation was not accepted for channel=%s thread_ts=%s; leaving session unconfirmed",
                    plan.channel_id,
                    plan.thread_ts,
                )
                return False

            for dk in plan.dedupe_keys:
                _bounded_set(self._seen_stops, dk)
            if plan.stop_ts is not None:
                existing_wm = self._stop_watermarks.get(key)
                if existing_wm is None or plan.stop_ts > existing_wm:
                    _bounded_set(self._stop_watermarks, key, plan.stop_ts)
            for message_id in plan.covered_ids:
                _bounded_set(self._stopped, (plan.channel_id, message_id))

        covered_set = set(plan.covered_ids)
        stopped_ids: list[str] = list(plan.covered_ids)
        has_newer_in_flight = False
        has_newer_completed = False
        stop_pending_token: tuple[str, str] | None = None
        retry_terminal = False
        retry_after: float | None = None
        with self._thread_lock(key):
            with self._lock:
                ids = self._in_flight.get(key)
                if ids is not None:
                    kept: list[str] = []
                    for message_id in ids:
                        if message_id in covered_set or (plan.stop_ts is not None and self._request_covered_by_stop(message_id, plan.stop_ts)):
                            _bounded_set(self._stopped, (plan.channel_id, message_id))
                            if message_id not in covered_set:
                                covered_set.add(message_id)
                                stopped_ids.append(message_id)
                        else:
                            kept.append(message_id)
                    if kept:
                        _bounded_set(self._in_flight, key, kept)
                        has_newer_in_flight = True
                    else:
                        self._in_flight.pop(key, None)
                latest_completed = self._latest_completed_ts.get(key)
                has_newer_completed = plan.stop_ts is not None and latest_completed is not None and latest_completed > plan.stop_ts
                has_newer = has_newer_in_flight or has_newer_completed
                if not has_newer:
                    stop_pending_token = (f"__stop__:{id(plan.token)}", "active")
                    _bounded_set(self._pending_finish, key, stop_pending_token)
                    self._cancel_retry_timer_locked(key)
            if stopped_ids:
                logger.info(
                    "[Slack agent] user stopped %d request(s) in channel=%s thread_ts=%s (newer_remaining=%s)",
                    len(stopped_ids),
                    plan.channel_id,
                    plan.thread_ts,
                    has_newer,
                )
            elif has_newer:
                logger.info(
                    "[Slack agent] delayed stop ignored for newer turn in channel=%s thread_ts=%s",
                    plan.channel_id,
                    plan.thread_ts,
                )
            else:
                # Slack only shows Stop while the session is processing; after a restart this process
                # may not know the request, but the session must still leave processing.
                logger.info("[Slack agent] stop for a thread with no tracked request channel=%s thread_ts=%s", plan.channel_id, plan.thread_ts)
            if not has_newer and stop_pending_token is not None and web_client is not None:
                outcome, retry_after = self._attempt_terminal_status_locked(web_client, key, pending_token=stop_pending_token, status="active")
                retry_terminal = outcome == "retry"

        if retry_terminal and stop_pending_token is not None and web_client is not None:
            self._schedule_terminal_retry(
                web_client,
                key,
                pending_token=stop_pending_token,
                status="active",
                attempt=0,
                retry_after=retry_after,
            )

        if not has_newer_completed and (stopped_ids or not has_newer_in_flight) and web_client is not None:
            try:
                web_client.chat_postMessage(channel=plan.channel_id, text=self.stopped_text, thread_ts=plan.thread_ts)
            except Exception:
                logger.exception("[Slack agent] failed to confirm stop in channel=%s", plan.channel_id)
        return True

    def stopped(
        self,
        web_client,
        event: dict,
        *,
        event_id: str | None = None,
        event_time: Any = None,
        cancel_runs: Callable[[StopPlan], bool] | None = None,
    ) -> bool:
        """Handle ``agent_session_stopped`` synchronously (for callers without an async manager)."""
        plan = self.prepare_stop(event, event_id=event_id, event_time=event_time)
        if plan is None:
            return False
        accepted = True
        if cancel_runs is not None:
            try:
                accepted = bool(cancel_runs(plan))
            except Exception:
                logger.exception("[Slack agent] cancel_runs callback failed for channel=%s thread_ts=%s", plan.channel_id, plan.thread_ts)
                accepted = False
        return self.complete_stop(web_client, plan, accepted=accepted)

    def title_changed(self, event: dict) -> None:
        """Handle ``agent_session_title_changed``: remember the user's title for the session."""
        if self._mode == "off":
            return
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
        if self._mode == "off":
            return
        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        entities = context.get("entities") if isinstance(context.get("entities"), list) else []
        logger.debug("[Slack agent] app context changed: %d entities", len(entities))

    # -- welcome and suggested prompts ---------------------------------------

    def home_opened(self, web_client, event: dict) -> None:
        """Handle ``app_home_opened`` on the Messages tab: suggested prompts, then a one-time welcome.

        ``app_home_opened`` also reaches apps that are not agents, so nothing happens until
        sessions are active (``enabled: true``, or ``auto`` after an agent-only event).
        """
        if not self.active or not web_client:
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

    def _set_status(self, web_client, payload: dict[str, Any]) -> tuple[bool, str, float | None]:
        """Call ``agents.sessions.setStatus``. Returns (ok, Slack error code or "", retry_after)."""
        response, error, retry_after = self._api_call(web_client, "agents.sessions.setStatus", payload)
        if response is None:
            return False, error, retry_after
        warning = str(_response_get(response, "warning") or "")
        if "missing_agent_session_stopped_event_subscription" in warning and not self._warned_no_stop_subscription:
            self._warned_no_stop_subscription = True
            logger.warning("[Slack agent] app is not subscribed to agent_session_stopped; users get no Stop button")
        return True, "", None

    @staticmethod
    def _api_call(web_client, method: str, payload: dict[str, Any]) -> tuple[Any, str, float | None]:
        """POST a JSON Web API call (slack-sdk 3.41 has no typed wrapper for the agent methods).

        Returns (response, "", None) on success, or (None, error code, retry_after) on failure.
        slack-sdk raises ``SlackApiError`` for ``ok: false`` / 429; its response carries the code
        and ``Retry-After`` header.
        """
        try:
            response = web_client.api_call(method, json=payload)
        except Exception as exc:
            resp = getattr(exc, "response", None)
            error = str(_response_get(resp, "error") or "")
            if not error and getattr(resp, "status_code", None) == 429:
                error = "ratelimited"
            retry_after = _extract_retry_after(resp)
            logger.warning("[Slack agent] %s failed: %s", method, error or type(exc).__name__)
            return None, error, retry_after
        if _response_get(response, "ok") is not True:
            error = str(_response_get(response, "error") or "")
            retry_after = _extract_retry_after(response)
            logger.warning("[Slack agent] %s returned error=%s", method, error)
            return None, error, retry_after
        return response, "", None
