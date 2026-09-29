"""Opt-in Responses multi-agent transport preflight; never wired into auto routing.

This is a protocol adapter and a single-cycle spending receipt journal, not a
worker queue. The existing coordinator owns scheduling, room posts and artifact
acceptance. Native hosted collaboration items are evidence, never local tools.
Local reservations alone cannot cap a provider's unbounded descendant tree.
Activation requires an operator-verified external aggregate budget contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

ENDPOINT = "https://openrouter.ai/api/v1/responses"
MODEL = "openai/gpt-6.1-sol"
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_ITEM_TYPES = frozenset({"message", "reasoning", "multi_agent_call", "multi_agent_call_output", "agent_message"})
_HOSTED_ACTIONS = frozenset({"spawn_agent", "send_message", "followup_task", "wait_agent", "interrupt_agent", "list_agents"})


class ActivationError(ValueError):
    """Non-retriable local admission/protocol failure; no automatic fallback."""


class UnknownOutcome(RuntimeError):
    """A dispatched request needs receipt reconciliation, never blind retry."""


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _identifier(value: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ActivationError("Use a nonempty bounded cycle/receipt/response identifier.")


@dataclass(frozen=True)
class RequestLimits:
    max_input_bytes: int = 65536
    max_output_tokens: int = 2048
    max_concurrent_subagents: int = 2


@dataclass(frozen=True)
class PreparedRequest:
    body: bytes
    route_mode: str = "native_multi_agent"

    @property
    def url(self) -> str:
        return ENDPOINT

    @property
    def headers(self) -> dict[str, str]:
        # Return a fresh mapping so another caller cannot alter a reserved call.
        headers = {"Content-Type": "application/json"}
        if self.route_mode == "native_multi_agent":
            headers["OpenAI-Beta"] = "responses_multi_agent=v1"
        return headers

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def build_request(prompt: str, *, instructions: str, receipt_id: str, cycle_id: str, limits: RequestLimits = RequestLimits(), previous_response_id: str | None = None) -> PreparedRequest:
    """Build a bounded text-only request with an intentionally empty tool list."""
    _identifier(receipt_id)
    _identifier(cycle_id)
    if previous_response_id is not None:
        raise ActivationError("HTTP continuation is disabled with store=false until a stateless replay contract is independently verified.")
    if type(limits.max_input_bytes) is not int or not 1 <= limits.max_input_bytes <= 65536:
        raise ActivationError("Invalid input byte limit; maximum is 65536.")
    if type(limits.max_output_tokens) is not int or not 1 <= limits.max_output_tokens <= 2048:
        raise ActivationError("Invalid output token limit; maximum is 2048.")
    if type(limits.max_concurrent_subagents) is not int or not 1 <= limits.max_concurrent_subagents <= 2:
        raise ActivationError("Invalid subagent concurrency; this pilot permits one or two.")
    if not isinstance(prompt, str) or not isinstance(instructions, str) or not prompt.strip() or not instructions.strip():
        raise ActivationError("A source packet and explicit developer instructions are required.")
    if len(prompt.encode("utf-8")) + len(instructions.encode("utf-8")) > limits.max_input_bytes:
        raise ActivationError("Source packet and instructions exceed the input byte limit.")
    payload: dict[str, Any] = {
        "model": MODEL,
        "input": [{"role": "developer", "content": instructions}, {"role": "user", "content": prompt}],
        "multi_agent": {"enabled": True, "max_concurrent_subagents": limits.max_concurrent_subagents},
        "max_output_tokens": limits.max_output_tokens,
        "reasoning": {"effort": "low"},
        "tools": [],
        "store": False,
        "stream": False,
        "provider": {"only": ["OpenAI"], "allow_fallbacks": False, "data_collection": "deny", "require_parameters": True},
        "metadata": {"cycle_id": cycle_id, "receipt_id": receipt_id},
    }
    return PreparedRequest(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def build_ordinary_tool_probe(packet_id: str, *, receipt_id: str, cycle_id: str) -> PreparedRequest:
    """Stage one synthetic read-only function-call probe, without executing it.

    This uses ordinary Responses, not hosted multi-agent. Passing this probe
    does not authorize a worker, continuation, source upload or loop activation.
    No arbitrary tool names, functions, URLs or extra parameters are accepted.
    """
    _identifier(packet_id)
    request = build_request(
        f"Request the supplied synthetic packet {packet_id} using get_source_packet. Do not claim its contents or perform another action.",
        instructions="This is a public compatibility fixture. Emit exactly one get_source_packet function call for the specified packet and stop. No function is executed by this test.",
        receipt_id=receipt_id,
        cycle_id=cycle_id,
        limits=RequestLimits(max_output_tokens=256),
    )
    payload = json.loads(request.body)
    del payload["multi_agent"]
    payload["tools"] = [
        {
            "type": "function",
            "name": "get_source_packet",
            "description": "Read the single explicitly supplied source packet; no writes or external actions.",
            "strict": True,
            "parameters": {"type": "object", "properties": {"packet_id": {"type": "string", "enum": [packet_id]}}, "required": ["packet_id"], "additionalProperties": False},
        }
    ]
    payload["tool_choice"] = {"type": "function", "name": "get_source_packet"}
    return PreparedRequest(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"), "ordinary_tool_probe")


@dataclass(frozen=True)
class OrdinaryToolProbe:
    response_id: str | None
    function_call_id: str | None
    actual_cost_usd: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    errors: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.errors


def parse_ordinary_tool_probe(response: Mapping[str, Any], *, packet_id: str) -> OrdinaryToolProbe:
    """Verify actual Sol function serialization independently of native beta."""
    _identifier(packet_id)
    errors: list[str] = []
    response_id = response.get("id")
    if not isinstance(response_id, str) or _IDENTIFIER.fullmatch(response_id) is None:
        response_id = None
        errors.append("missing_response_id")
    if response.get("model") not in (MODEL, "gpt-6.1-sol"):
        errors.append("unexpected_resolved_model")
    if response.get("status") != "completed" or response.get("error") is not None:
        errors.append("provider_rejected_or_incomplete")
    output = response.get("output")
    output = output if isinstance(output, list) else []
    calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
    call_id = None
    if len(calls) != 1:
        errors.append("exactly_one_real_function_call_required")
    else:
        call = calls[0]
        try:
            arguments = json.loads(call.get("arguments", "null"))
        except (TypeError, ValueError):
            arguments = None
        if call.get("name") != "get_source_packet" or arguments != {"packet_id": packet_id}:
            errors.append("function_not_in_read_only_allowlist")
        candidate = call.get("call_id")
        if isinstance(candidate, str) and _IDENTIFIER.fullmatch(candidate):
            call_id = candidate
        else:
            errors.append("missing_function_call_id")
    if any(not isinstance(item, dict) or item.get("type") not in {"function_call", "message", "reasoning"} for item in output):
        errors.append("unapproved_output_or_tool_call")
    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cost = _money(usage.get("cost"))
    if cost is None:
        errors.append("cost_unknown")
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if type(input_tokens) is not int or input_tokens < 0:
        input_tokens = None
        errors.append("input_usage_unknown")
    if type(output_tokens) is not int or output_tokens < 0:
        output_tokens = None
        errors.append("output_usage_unknown")
    return OrdinaryToolProbe(response_id, call_id, cost, input_tokens, output_tokens, tuple(errors))


@dataclass(frozen=True)
class AgentEvent:
    item_id: str | None
    item_type: str
    agent_name: str | None
    phase: str | None = None
    text: str | None = None
    call_id: str | None = None
    action: str | None = None
    author: str | None = None
    recipient: str | None = None


@dataclass(frozen=True)
class ParsedResponse:
    response_id: str | None
    root_final: str | None
    events: tuple[AgentEvent, ...]
    spawned_agents: tuple[str, ...]
    actual_cost_usd: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    errors: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        """Protocol/accounting acceptance only; artifact quality is separate."""
        return not self.errors


def _text(parts: Any) -> str | None:
    if not isinstance(parts, list):
        return None
    texts = [part["text"] for part in parts if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str)]
    return "".join(texts) if texts else None


def parse_response(response: Mapping[str, Any]) -> ParsedResponse:
    """Refuse successful plain Responses answers when native beta was ignored.

    Require a paired successful hosted spawn plus actual child-attributed output,
    and an explicit /root final_answer. Do not flatten worker text into that final.
    Encrypted agent messages retain direction only; this adapter cannot read them.
    """
    errors: list[str] = []
    response_id = response.get("id")
    if not isinstance(response_id, str) or _IDENTIFIER.fullmatch(response_id) is None:
        response_id = None
        errors.append("missing_response_id")
    if response.get("status") != "completed":
        errors.append("response_not_completed")
    if response.get("model") not in (MODEL, "gpt-6.1-sol"):
        errors.append("unexpected_resolved_model")
    if response.get("error") is not None:
        errors.append("provider_rejected_request")
    output = response.get("output")
    if not isinstance(output, list):
        output = []
        errors.append("missing_output_items")
    events: list[AgentEvent] = []
    spawned: set[str] = set()
    children: set[str] = set()
    finals: list[str] = []
    spawn_calls: set[str] = set()
    item_ids: set[str] = set()
    for item in output:
        if not isinstance(item, dict):
            errors.append("invalid_output_item")
            continue
        kind = item.get("type")
        if kind not in _ITEM_TYPES:
            errors.append("unapproved_output_or_tool_call")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or _IDENTIFIER.fullmatch(item_id) is None or item_id in item_ids:
            errors.append("missing_or_duplicate_item_identity")
        else:
            item_ids.add(item_id)
        if kind in {"multi_agent_call", "multi_agent_call_output"} and item.get("action") not in _HOSTED_ACTIONS:
            errors.append("unknown_hosted_action")
        agent = item.get("agent")
        name = agent.get("agent_name") if isinstance(agent, dict) else None
        if not isinstance(name, str) or not (name == "/root" or name.startswith("/root/")):
            name = None
            errors.append("missing_or_invalid_agent_attribution")
        elif name != "/root":
            children.add(name)
        text = _text(item.get("content")) if kind == "message" else None
        events.append(AgentEvent(item.get("id"), kind, name, item.get("phase"), text, item.get("call_id"), item.get("action"), item.get("author"), item.get("recipient")))
        if kind == "message" and name == "/root" and item.get("phase") == "final_answer" and text:
            finals.append(text)
        if kind == "multi_agent_call" and item.get("action") == "spawn_agent" and isinstance(item.get("call_id"), str):
            spawn_calls.add(item["call_id"])
    # Pair by call_id without depending on provider item ordering.
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "multi_agent_call_output" or item.get("action") != "spawn_agent" or item.get("call_id") not in spawn_calls:
            continue
        try:
            result = json.loads(_text(item.get("output")) or "null")
        except (ValueError, TypeError):
            continue
        if isinstance(result, dict) and isinstance(result.get("task_name"), str) and result["task_name"].startswith("/root/"):
            spawned.add(result["task_name"])
    if not spawned or not spawned.intersection(children):
        errors.append("native_spawn_and_child_output_not_verified")
    if not finals:
        errors.append("missing_root_final_answer")
    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cost = _money(usage.get("cost"))
    if cost is None:
        errors.append("aggregate_cost_unknown")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if type(input_tokens) is not int or input_tokens < 0:
        input_tokens = None
        errors.append("aggregate_input_usage_unknown")
    if type(output_tokens) is not int or output_tokens < 0:
        output_tokens = None
        errors.append("aggregate_output_usage_unknown")
    return ParsedResponse(response_id, "".join(finals) or None, tuple(events), tuple(sorted(spawned)), cost, input_tokens, output_tokens, tuple(dict.fromkeys(errors)))


@dataclass(frozen=True)
class BudgetPolicy:
    cycle_id: str
    approved: bool
    pilot_usd: Decimal
    account_remaining_usd: Decimal
    account_reserve_usd: Decimal
    max_requests: int = 16


@dataclass(frozen=True)
class BudgetProof:
    """Trusted operator attestation, not a model/caller-supplied assertion.

    Requires both an independently checked capability receipt and an external
    provider aggregate ceiling covering the entire cycle, all descendants and
    all HTTP continuations. No such OpenRouter beta guarantee is assumed.
    """

    capability_response_id: str | None
    aggregate_limit_usd: Decimal | None
    covers_descendants_and_continuations: bool
    evidence_reference: str


def _validate_activation(policy: BudgetPolicy, proof: BudgetProof) -> str:
    _identifier(policy.cycle_id)
    pilot, remaining, reserve, ceiling = map(_money, (policy.pilot_usd, policy.account_remaining_usd, policy.account_reserve_usd, proof.aggregate_limit_usd))
    if policy.approved is not True or pilot is None or pilot <= 0 or remaining is None or reserve is None or pilot > remaining - reserve:
        raise ActivationError("Pilot approval and a finite budget preserving the account reserve are required.")
    if type(policy.max_requests) is not int or not 1 <= policy.max_requests <= 16:
        raise ActivationError("Pilot permits at most 16 explicit HTTP requests.")
    if not proof.capability_response_id or not proof.evidence_reference or proof.covers_descendants_and_continuations is not True or ceiling is None or ceiling <= 0 or ceiling > pilot:
        raise ActivationError("Native capability and externally enforced aggregate descendant/continuation budget semantics remain unverified.")
    # Immutable on reopen; this prevents changing limits halfway through a cycle.
    return json.dumps(
        {
            "cycle_id": policy.cycle_id,
            "pilot": str(pilot),
            "remaining": str(remaining),
            "reserve": str(reserve),
            "max_requests": policy.max_requests,
            "capability": proof.capability_response_id,
            "aggregate_limit": str(ceiling),
            "evidence": proof.evidence_reference,
        },
        sort_keys=True,
    )


class CycleJournal:
    """Private durable receipt journal; synchronous methods must run off-loop.

    SQLite BEGIN IMMEDIATE serializes admission across processes. Inflight or
    unknown outcomes block new calls until reconciled by receipt ID. A crash
    before dispatch may conservatively hold a reservation; do not auto-release.
    Append-only events preserve all reservations/outcomes/accounting corrections;
    receipts are their mutable current-state projection. This state is not the
    application's database, worker queue or account limit.
    """

    def __init__(self, path: Path, *, policy: BudgetPolicy, proof: BudgetProof):
        config = _validate_activation(policy, proof)
        self.path = Path(path)
        self.policy = policy
        # Normalize even callers supplying numeric strings; validation ran first.
        self._budget_limit = min(Decimal(str(policy.pilot_usd)), Decimal(str(proof.aggregate_limit_usd)))
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_mode & 0o077:
                raise ActivationError("Receipt journal must be a private regular file, mode 0600.") from None
        else:
            os.close(fd)
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cycle (id TEXT PRIMARY KEY, policy TEXT NOT NULL, halted TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, reservation TEXT NOT NULL, "
                "status TEXT NOT NULL, response_id TEXT UNIQUE, response_json TEXT, cost TEXT, input_tokens INTEGER, output_tokens INTEGER)"
            )
            row = db.execute("SELECT policy FROM cycle WHERE id = ?", (policy.cycle_id,)).fetchone()
            if row is None:
                if db.execute("SELECT 1 FROM cycle").fetchone() is not None:
                    raise ActivationError("A receipt journal belongs to exactly one cycle.")
                db.execute("INSERT INTO cycle (id, policy) VALUES (?, ?)", (policy.cycle_id, config))
            elif row[0] != config:
                raise ActivationError("Receipt journal policy cannot change on restart.")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous = FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, receipt_id: str, request: PreparedRequest, amount: Decimal) -> None:
        _identifier(receipt_id)
        reservation = _money(amount)
        if reservation is None or reservation <= 0:
            raise ActivationError("A finite positive call reservation is required.")
        payload = json.loads(request.body)
        if request.route_mode != "native_multi_agent":
            raise ActivationError("This journal admits native multi-agent requests only; ordinary tool probes are separate preflight evidence.")
        try:
            messages = payload["input"]
            canonical = build_request(
                messages[1]["content"],
                instructions=messages[0]["content"],
                receipt_id=receipt_id,
                cycle_id=self.policy.cycle_id,
                limits=RequestLimits(max_output_tokens=payload["max_output_tokens"], max_concurrent_subagents=payload["multi_agent"]["max_concurrent_subagents"]),
                previous_response_id=payload.get("previous_response_id"),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ActivationError("Invalid request; use the bounded request builder.") from None
        if request.body != canonical.body:
            raise ActivationError("Invalid request; route, privacy, tool list and limits must match the bounded builder.")
        if payload.get("metadata") != {"cycle_id": self.policy.cycle_id, "receipt_id": receipt_id}:
            raise ActivationError("Request must bind to the same cycle and receipt.")
        with self._transaction() as db:
            if db.execute("SELECT halted FROM cycle").fetchone()[0]:
                raise ActivationError("Cycle halted; inspect and reconcile its receipts.")
            rows = db.execute("SELECT * FROM receipts").fetchall()
            if any(row["id"] == receipt_id for row in rows):
                raise ActivationError("Receipt already exists; recover it instead of retrying.")
            if any(row["status"] != "settled" for row in rows):
                raise ActivationError("An inflight or unknown receipt must be recovered before dispatch.")
            if len(rows) >= self.policy.max_requests:
                raise ActivationError("Cycle HTTP request limit reached.")
            committed = sum((Decimal(row["cost"]) for row in rows), Decimal(0))
            if committed + reservation > self._budget_limit:
                raise ActivationError("Insufficient cycle budget for this reservation.")
            db.execute("INSERT INTO receipts (id, request_sha256, reservation, status) VALUES (?, ?, ?, 'inflight')", (receipt_id, request.sha256, str(reservation)))
            db.execute("INSERT INTO events (receipt_id, kind, payload) VALUES (?, 'reserved', ?)", (receipt_id, json.dumps({"request_sha256": request.sha256, "reservation_usd": str(reservation)}, sort_keys=True)))

    def mark_unknown(self, receipt_id: str) -> None:
        with self._transaction() as db:
            changed = db.execute("UPDATE receipts SET status = 'unknown' WHERE id = ? AND status = 'inflight'", (receipt_id,))
            if changed.rowcount:
                db.execute("INSERT INTO events (receipt_id, kind, payload) VALUES (?, 'unknown_outcome', '{}')", (receipt_id,))

    def recover(self, receipt_id: str, response: Mapping[str, Any]) -> ParsedResponse:
        """Reconcile a retrieved response, without making any provider request."""
        _identifier(receipt_id)
        metadata = response.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("cycle_id") != self.policy.cycle_id or metadata.get("receipt_id") != receipt_id:
            raise ActivationError("Response metadata must bind to the reserved cycle and receipt before accounting can be released.")
        result = parse_response(response)
        serialized = json.dumps(dict(response), sort_keys=True, ensure_ascii=False)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
            if row is None:
                raise ActivationError("Unknown receipt; no dispatched reservation exists.")
            if row["response_json"] is not None:
                if row["response_json"] == serialized:
                    if result.actual_cost_usd is not None and result.actual_cost_usd > Decimal(row["reservation"]):
                        result = replace(result, errors=(*result.errors, "call_reservation_exceeded"))
                    return result
                previous = json.loads(row["response_json"])
                previous.pop("usage", None)
                current = dict(response)
                current.pop("usage", None)
                # Cost/usage may arrive from an authoritative receipt lookup.
                # The actual result and identity can never be replaced/replayed.
                if row["status"] != "unknown" or previous != current or not result.accepted:
                    raise ActivationError("Recovery cannot change a recorded response.")
            if result.response_id and db.execute("SELECT 1 FROM receipts WHERE response_id = ? AND id != ?", (result.response_id, receipt_id)).fetchone():
                raise ActivationError("Response ID is already accounted under another receipt.")
            overrun = result.actual_cost_usd is not None and result.actual_cost_usd > Decimal(row["reservation"])
            if overrun:
                result = replace(result, errors=(*result.errors, "call_reservation_exceeded"))
            known = result.actual_cost_usd is not None
            db.execute("INSERT INTO events (receipt_id, kind, payload) VALUES (?, ?, ?)", (receipt_id, "response_recorded" if row["response_json"] is None else "accounting_reconciled", serialized))
            db.execute(
                "UPDATE receipts SET status = ?, response_id = ?, response_json = ?, cost = ?, input_tokens = ?, output_tokens = ? WHERE id = ?",
                ("settled" if known else "unknown", result.response_id, serialized, str(result.actual_cost_usd) if known else None, result.input_tokens, result.output_tokens, receipt_id),
            )
            failures: list[str] = []
            for saved in db.execute("SELECT response_json, cost, reservation FROM receipts WHERE response_json IS NOT NULL"):
                saved_result = parse_response(json.loads(saved["response_json"]))
                failures.extend(saved_result.errors)
                if saved["cost"] is not None and Decimal(saved["cost"]) > Decimal(saved["reservation"]):
                    failures.append("call_reservation_exceeded")
            db.execute("UPDATE cycle SET halted = ?", (",".join(dict.fromkeys(failures)) or None,))
        return result

    def receipt(self, receipt_id: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
            if row is None:
                raise ActivationError("Unknown receipt.")
            return dict(row)

    def history(self, receipt_id: str) -> tuple[dict[str, Any], ...]:
        """Read append-only evidence; callers must offload this synchronous API."""
        with self._transaction() as db:
            return tuple(dict(row) for row in db.execute("SELECT * FROM events WHERE receipt_id = ? ORDER BY seq", (receipt_id,)))

    def totals(self) -> dict[str, Any]:
        with self._transaction() as db:
            rows = db.execute("SELECT cost, input_tokens, output_tokens FROM receipts").fetchall()
        known = sum((Decimal(row["cost"]) for row in rows if row["cost"] is not None), Decimal(0))
        return {
            "actual_cost_usd": known if all(row["cost"] is not None for row in rows) else None,
            "known_cost_usd": known,
            "input_tokens": sum(row["input_tokens"] for row in rows) if all(row["input_tokens"] is not None for row in rows) else None,
            "output_tokens": sum(row["output_tokens"] for row in rows) if all(row["output_tokens"] is not None for row in rows) else None,
            "requests": len(rows),
        }


class Pilot:
    """Single explicit stateless call; no continuations, scheduling or retries."""

    def __init__(self, journal: CycleJournal, post: Callable[[PreparedRequest], Awaitable[Mapping[str, Any]]]):
        self.journal = journal
        self.post = post

    async def submit(self, prompt: str, *, instructions: str, receipt_id: str, reservation_usd: Decimal, limits: RequestLimits = RequestLimits(), previous_response_id: str | None = None) -> ParsedResponse:
        request = build_request(prompt, instructions=instructions, receipt_id=receipt_id, cycle_id=self.journal.policy.cycle_id, limits=limits, previous_response_id=previous_response_id)
        # A cancellation while a durable worker runs must not start a new call.
        # Conservative inflight receipt recovery covers the crash/cancel window.
        await asyncio.to_thread(self.journal.reserve, receipt_id, request, reservation_usd)
        try:
            response = await self.post(request)
            return await asyncio.to_thread(self.journal.recover, receipt_id, response)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self.journal.mark_unknown, receipt_id))
            raise
        except Exception:
            await asyncio.to_thread(self.journal.mark_unknown, receipt_id)
            raise UnknownOutcome(f"Receipt {receipt_id} needs reconciliation; do not retry or fall back.") from None


class OpenRouterTransport:
    """Real HTTP seam; explicit caller supplies key, no env/config discovery.

    No automatic retries or redirects. Test transports are injected offline.
    Never log keys, payloads or provider exceptions. A non-2xx or malformed body
    becomes an unknown dispatched outcome through Pilot, requiring reconciliation.
    """

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"}, follow_redirects=False, timeout=30, transport=transport or httpx.AsyncHTTPTransport(retries=0))

    async def __call__(self, request: PreparedRequest) -> Mapping[str, Any]:
        if request.url != ENDPOINT:
            raise ActivationError("Only the pinned OpenRouter Responses endpoint is permitted.")
        response = await self._client.post(ENDPOINT, content=request.body, headers=request.headers)
        response.raise_for_status()
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ActivationError("Provider response must be an object.")
        return parsed

    async def aclose(self) -> None:
        await self._client.aclose()
