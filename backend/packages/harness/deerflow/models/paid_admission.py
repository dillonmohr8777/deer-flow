"""Fail-closed paid-route admission gate (one $20/month Momo/Jevbox ceiling).

Reuses the mechanics of the "Shared admission candidate v3" (append-only fsynced
journal, reserve-before-call, settle-from-actual, unknown outcome keeps the full
hold) but swaps its qualification verifier for a plain holds file + kill switch.

State dir (``MOMO_ADMISSION_DIR``, default ``~/.momo/admission``):
  audit.jsonl   append-only ledger AND audit log (state is derived from it)
  holds.json    {"holds":[{"id":..,"resolved":bool}]}; missing/corrupt/any
                unresolved hold => every paid route is denied
  KILL          existing file (or MOMO_ADMISSION_KILL=1) => all paid routes denied
  registry.json optional {"subcaps":{route: micro_usd}}; can only name known routes

Everything is integer micro-USD. Unknown route = deny. ``MOMO_ADMISSION_GATE=off``
disables the LangChain wiring (default is ON).
"""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import threading
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

CEILING_MICRO = 20_000_000  # one monthly ceiling; subcaps below are NOT additive to it
# Default per-route subcaps (micro-USD). Their sum exceeds the ceiling on purpose:
# each route is capped alone AND the total of all routes is capped at CEILING_MICRO.
DEFAULT_SUBCAPS = {
    "jevbox_llm": 10_000_000,  # Jevbox / Momo LLM
    "openrouter": 10_000_000,
    "brain_forge": 5_000_000,  # Brain Forge GLM / HAI
    "agent_reach": 5_000_000,  # paid reads only
    "reddit": 2_000_000,  # Reddit providers
    "x": 0,  # frozen
    # Found by the Codex gap review. Subcap 0 = registered but denied until an owner raises it in registry.json.
    "cloud_spark_80h": 0,  # launchd com.dillon.cloud-spark-80h paid-key runner
    "glm_team_proxy": 0,  # launchd com.dillon.glm-team local proxy to paid HAI/Sol/Spark (loopback does NOT mean free)
    "dot_ultrafast": 0,  # Dot "Ultrafast" API route
}
FROZEN = frozenset({"x"})
LOCAL = frozenset({"local"})  # $0 routes: allowed, audited, never reserved
KNOWN_ROUTES = frozenset(DEFAULT_SUBCAPS) | LOCAL
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class AdmissionDenied(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _holds_unresolved(path: Path) -> str | None:
    try:
        holds = json.loads(path.read_text())["holds"]
        if not isinstance(holds, list) or not all(isinstance(h, dict) for h in holds):
            return "holds_unreadable"
    except (OSError, ValueError, KeyError, TypeError):
        return "holds_unreadable"
    return "unresolved_hold" if any(h.get("resolved") is not True for h in holds) else None


class AdmissionGate:
    def __init__(self, state_dir: str | Path | None = None, *, clock=time.time):
        self.dir = Path(state_dir or os.environ.get("MOMO_ADMISSION_DIR") or Path.home() / ".momo" / "admission")
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.audit, self.holds, self.kill_file = self.dir / "audit.jsonl", self.dir / "holds.json", self.dir / "KILL"
        self.clock = clock
        self._tlock = threading.RLock()

    # --- storage -----------------------------------------------------------
    @contextmanager
    def _tx(self):
        # ponytail: whole-file replay under one flock; fine at this call volume, snapshot if audit.jsonl > ~50 MB
        with self._tlock:
            lock_fd = os.open(self.dir / "audit.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(lock_fd)  # closing releases the flock

    def _period(self) -> str:
        t = time.gmtime(self.clock())
        return f"{t.tm_year:04d}-{t.tm_mon:02d}"

    def _append(self, row: dict, *, sync: bool = True) -> None:
        row = {"ts": self.clock(), "period": self._period(), **row}
        data = (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        fd = os.open(self.audit, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            if os.write(fd, data) != len(data):
                raise AdmissionDenied("audit_write_failed")
            if sync:
                os.fsync(fd)
        except OSError:
            raise AdmissionDenied("audit_write_failed") from None
        finally:
            os.close(fd)

    def _state(self) -> dict:
        """Replay the log. Held = reserved/unknown (any month); settled counts for the current month only."""
        rids: dict[str, dict] = {}
        keys: set[str] = set()
        try:
            lines = self.audit.read_text().splitlines() if self.audit.exists() else []
            for line in lines:
                row = json.loads(line)
                ev = row.get("ev")
                if ev == "reserve":
                    if row["rid"] in rids:
                        raise ValueError
                    rids[row["rid"]] = {"route": row["route"], "amount": row["amount"], "state": "reserved", "actual": 0, "period": None}
                    keys.add(row["key"])
                elif ev in ("settle", "unknown"):
                    r = rids[row["rid"]]
                    if r["state"] != "reserved":
                        raise ValueError
                    r["state"] = "settled" if ev == "settle" else "unknown"
                    if ev == "settle":
                        r["actual"], r["period"] = row["actual"], row["period"]
                elif ev not in ("deny", "local"):
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise AdmissionDenied("ledger_corrupt") from None
        now, used = self._period(), {}
        for r in rids.values():
            if r["state"] in ("reserved", "unknown"):
                used[r["route"]] = used.get(r["route"], 0) + r["amount"]
            elif r["period"] == now:
                used[r["route"]] = used.get(r["route"], 0) + r["actual"]
        return {"rids": rids, "keys": keys, "used": used, "total": sum(used.values())}

    def _subcaps(self) -> dict[str, int]:
        caps = dict(DEFAULT_SUBCAPS)
        reg = self.dir / "registry.json"
        if reg.exists():
            try:
                for route, cap in json.loads(reg.read_text())["subcaps"].items():
                    if route in caps and route not in FROZEN and type(cap) is int and 0 <= cap <= CEILING_MICRO:
                        caps[route] = cap
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                raise AdmissionDenied("registry_unreadable") from None
        return caps

    # --- public API --------------------------------------------------------
    def reserve(self, route: str, amount_micro: int, key: str) -> str | None:
        """Admit or raise AdmissionDenied. Returns a reservation id (None for $0 local routes)."""
        with self._tx():
            try:
                return self._admit(route, amount_micro, key)
            except AdmissionDenied as exc:
                self._audit_deny(route, exc.reason)
                raise

    def _audit_deny(self, route, reason: str) -> None:
        try:
            self._append({"ev": "deny", "route": str(route)[:64], "reason": reason})
        except AdmissionDenied:
            pass  # still denied; the audit failure is itself a denial

    def deny(self, route, reason: str):
        """Audit and raise a denial decided outside the gate (e.g. no usable pricing)."""
        with self._tx():
            self._audit_deny(route, reason)
        raise AdmissionDenied(reason)

    def _admit(self, route, amount, key) -> str | None:
        if route not in KNOWN_ROUTES:
            raise AdmissionDenied("unknown_route")
        if route in LOCAL:
            self._append({"ev": "local", "route": route}, sync=False)
            return None
        if os.environ.get("MOMO_ADMISSION_KILL") == "1" or self.kill_file.exists():
            raise AdmissionDenied("kill_switch")
        if route in FROZEN:
            raise AdmissionDenied("route_frozen")
        if reason := _holds_unresolved(self.holds):
            raise AdmissionDenied(reason)
        if type(amount) is not int or amount <= 0 or not isinstance(key, str) or not key or len(key) > 256:
            raise AdmissionDenied("request_invalid")
        state = self._state()
        if key in state["keys"]:
            raise AdmissionDenied("duplicate_key")
        if state["used"].get(route, 0) + amount > self._subcaps()[route]:
            raise AdmissionDenied("route_subcap")
        if state["total"] + amount > CEILING_MICRO:
            raise AdmissionDenied("monthly_ceiling")
        rid = uuid.uuid4().hex
        self._append({"ev": "reserve", "rid": rid, "route": route, "amount": amount, "key": key})
        return rid

    def settle(self, rid: str, actual_micro: int) -> bool:
        """Record actual spend. Idempotent: True if newly settled, False if already settled. Allowed under kill/holds."""
        if type(actual_micro) is not int or actual_micro < 0:
            raise AdmissionDenied("actual_invalid")
        with self._tx():
            r = self._state()["rids"].get(rid)
            if r is None:
                raise AdmissionDenied("unknown_reservation")
            if r["state"] == "settled":
                return False
            if r["state"] != "reserved":
                raise AdmissionDenied("settle_state_conflict")
            # An actual above the reservation is recorded as-is (real money); it can only tighten later admissions.
            self._append({"ev": "settle", "rid": rid, "route": r["route"], "actual": actual_micro, "reserved": r["amount"]})
            return True

    def mark_unknown(self, rid: str) -> None:
        """Outcome unknown (error/no usage): keep the full reservation held, never retried automatically."""
        with self._tx():
            r = self._state()["rids"].get(rid)
            if r and r["state"] == "reserved":
                self._append({"ev": "unknown", "rid": rid, "route": r["route"]})

    def status(self) -> dict:
        with self._tx():
            s = self._state()
        return {"ceiling_micro": CEILING_MICRO, "used_micro": s["total"], "by_route": s["used"]}


# --- model-call wiring ------------------------------------------------------
def cost_micro(pricing: dict | None, input_tokens: int, output_tokens: int, cache_read: int = 0) -> int | None:
    """USD-per-million price == micro-USD per token. None when pricing is unusable (caller denies)."""
    try:
        pin, pout = Decimal(str(pricing["input_per_million"])), Decimal(str(pricing["output_per_million"]))
        pcache = Decimal(str(pricing.get("input_cache_hit_per_million", pin)))
        if pricing.get("currency", "USD") != "USD" or min(pin, pout, pcache) < 0:
            return None
    except (TypeError, KeyError, ValueError, ArithmeticError):
        return None
    cache_read = min(cache_read, input_tokens)
    return math.ceil((input_tokens - cache_read) * pin + cache_read * pcache + output_tokens * pout)


def resolve_route(explicit: str | None, base_url: str | None) -> str | None:
    """Explicit `admission_route` wins; otherwise only openrouter.ai is inferable. None => deny.

    Loopback is deliberately NOT inferred as `local`: the glm-team proxy listens on loopback and is paid.
    A $0 model must say `admission_route: local` in config.
    """
    if explicit:
        return explicit
    host = (urlparse(base_url or "").hostname or "").lower()
    return "openrouter" if host == "openrouter.ai" or host.endswith(".openrouter.ai") else None


class AdmissionHandler(BaseCallbackHandler):
    """Reserve on model start (raising blocks the call), settle from actual usage on end."""

    raise_error = True
    run_inline = True

    def __init__(self, gate: AdmissionGate, route: str | None, pricing: dict | None, max_output_tokens: int | None):
        self.gate, self.route, self.pricing = gate, route, pricing
        self.max_out = max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
        self._open: dict[object, str | None] = {}
        self._lock = threading.Lock()

    def _begin(self, run_id, chars: int) -> None:
        amount = 1  # unknown/local routes: gate.reserve denies or ignores the amount
        if self.route in KNOWN_ROUTES - LOCAL:
            amount = cost_micro(self.pricing, chars // 2 + 1, self.max_out)  # conservative: 2 chars/token
            if amount is None:
                self.gate.deny(self.route, "pricing_unavailable")
        rid = self.gate.reserve(self.route, max(amount, 1), str(run_id))
        with self._lock:
            self._open[run_id] = rid

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._begin(run_id, sum(len(str(getattr(m, "content", m))) for batch in messages for m in batch))

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._begin(run_id, sum(len(p) for p in prompts))

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            rid = self._open.pop(run_id, None)
        if rid is None:
            return
        try:
            usage = None
            for gen in response.generations:
                for g in gen:
                    usage = getattr(getattr(g, "message", None), "usage_metadata", None) or usage
            usage = usage or (response.llm_output or {}).get("token_usage")
            if not usage:
                return self.gate.mark_unknown(rid)
            tin = usage.get("input_tokens", usage.get("prompt_tokens"))
            tout = usage.get("output_tokens", usage.get("completion_tokens"))
            cache = (usage.get("input_token_details") or {}).get("cache_read", 0)
            actual = cost_micro(self.pricing, tin, tout, cache) if type(tin) is int and type(tout) is int else None
            if actual is None:
                return self.gate.mark_unknown(rid)
            self.gate.settle(rid, actual)
        except AdmissionDenied:
            logger.exception("admission settle failed; reservation stays held")

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            rid = self._open.pop(run_id, None)
        if rid is not None:
            self.gate.mark_unknown(rid)


_gate: AdmissionGate | None = None
_gate_lock = threading.Lock()


def get_gate() -> AdmissionGate:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = AdmissionGate()
        return _gate


def attach_admission(model_instance, model_config, settings: dict) -> None:
    """Called once from create_chat_model. Default ON; MOMO_ADMISSION_GATE=off disables."""
    if os.environ.get("MOMO_ADMISSION_GATE", "on").strip().lower() in {"off", "0", "false", "no"}:
        return
    if not isinstance(model_instance, BaseChatModel):
        return  # factory only builds BaseChatModel subclasses; this skips bare test doubles
    base = settings.get("base_url") or settings.get("openai_api_base") or settings.get("api_base")
    route = resolve_route(getattr(model_config, "admission_route", None), base)
    pricing = (model_config.model_extra or {}).get("pricing")
    handler = AdmissionHandler(get_gate(), route, pricing, settings.get("max_tokens"))
    model_instance.callbacks = [*(model_instance.callbacks or []), handler]
