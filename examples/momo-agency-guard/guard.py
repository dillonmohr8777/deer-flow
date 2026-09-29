"""Opt-in text-only, per-cycle OpenRouter guard. No live routing changes on import.

Only requests actually routed here are protected. Do not expose this outside a
loopback/private network or claim a whole-gateway ceiling without egress proof.
"""

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Stop(Exception):
    """A safe, payload-free stop reason."""


class Policy:
    model = "openai/gpt-6-luna"
    cap = Decimal(1)
    credit_reserve = Decimal(8)
    max_calls = 16
    max_inflight = 2
    max_input_bound = 128000
    max_output = 2000
    max_response_bytes = 4000000
    input_ceiling = Decimal("0.00000025")
    output_ceiling = Decimal("0.00000075")
    tools = frozenset(
        {
            "agent_room_read",
            "agent_room_post",
            "task",
            "batch_task",
            "approved_agency_phase",
            "batch_status",
            "cancel_batch",
            "ls",
            "read_file",
            "glob",
            "grep",
            "write_file",
            "str_replace",
            "present_files",
            "write_todos",
            "think",
        }
    )


def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise Stop("cost_or_credit_unknown") from exc
    if not amount.is_finite() or amount < 0:
        raise Stop("cost_or_credit_invalid")
    return amount


def validate_payload(payload, policy):
    allowed = {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "max_tokens",
        "max_completion_tokens",
        "stream",
        "stream_options",
        "temperature",
        "top_p",
        "seed",
        "frequency_penalty",
        "presence_penalty",
        "reasoning_effort",
        "reasoning",
        "response_format",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise Stop("unsupported_payload_field")
    if payload.get("model") != policy.model:
        raise Stop("private_model_not_allowed")
    if type(payload.get("stream", False)) is not bool:
        raise Stop("invalid_stream")
    if "stream_options" in payload and (
        not isinstance(payload["stream_options"], dict)
        or set(payload["stream_options"]) - {"include_usage"}
        or type(payload["stream_options"].get("include_usage", True)) is not bool
    ):
        raise Stop("invalid_stream_options")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 256:
        raise Stop("invalid_messages")
    for message in messages:
        if not isinstance(message, dict) or set(message) - {
            "role",
            "content",
            "name",
            "tool_calls",
            "tool_call_id",
            "reasoning",
            "reasoning_content",
        }:
            raise Stop("unsupported_message_field")
        if message.get("role") not in {
            "system",
            "developer",
            "user",
            "assistant",
            "tool",
        }:
            raise Stop("invalid_role")
        if message.get("content") is not None and not isinstance(
            message.get("content"), str
        ):
            raise Stop("multimodal_or_file_payload_refused")
    tools = payload.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 32:
        raise Stop("invalid_tools")
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if (
            not isinstance(tool, dict)
            or tool.get("type") != "function"
            or not isinstance(function, dict)
            or function.get("name") not in policy.tools
            or not isinstance(function.get("parameters", {}), dict)
        ):
            raise Stop("hosted_or_unapproved_tool_refused")
    for key in ("max_tokens", "max_completion_tokens"):
        if key in payload and (
            type(payload[key]) is not int or not 1 <= payload[key] <= policy.max_output
        ):
            raise Stop("output_ceiling_exceeded")
    if not any(k in payload for k in ("max_tokens", "max_completion_tokens")):
        raise Stop("explicit_output_ceiling_required")
    if "reasoning" in payload and (
        not isinstance(payload["reasoning"], dict)
        or set(payload["reasoning"]) - {"effort", "exclude"}
    ):
        raise Stop("unsupported_reasoning_budget")
    # UTF-8 bytes plus conservative message framing is an admission estimate,
    # not the billing guarantee. Full-context price reservation is below.
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Stop("payload_encoding_invalid") from exc
    input_bound = len(encoded) + 4096 + 128 * (len(messages) + len(tools))
    if input_bound > policy.max_input_bound:
        raise Stop("text_input_bound_exceeded")
    return input_bound


def full_context_reservation(catalog, policy):
    if catalog.get("id") != policy.model:
        raise Stop("catalog_model_mismatch")
    context = catalog.get("context_length")
    if type(context) is not int or not 1 <= context <= 2000000:
        raise Stop("catalog_context_unknown")
    pricing = catalog.get("pricing", {})
    rates = [pricing] + pricing.get("overrides", [])
    input_rate = max(
        money(x[k]) for x in rates for k in ("prompt", "input_cache_write") if k in x
    )
    output_rate = max(money(x["completion"]) for x in rates if "completion" in x)
    if input_rate > policy.input_ceiling or output_rate > policy.output_ceiling:
        raise Stop("catalog_price_ceiling_exceeded")
    # Reserve the full documented context, including all hidden framing and
    # the highest cache-write/long-context price. Never rely on byte estimates
    # to promise a monetary cap or on a cache discount to admit a request.
    return input_rate * context + output_rate * policy.max_output


class Ledger:
    def __init__(self, path, cycle_id):
        self.path = Path(path)
        self.cycle_id = cycle_id
        self.boot_id = uuid.uuid4().hex
        self.mutex = threading.RLock()
        self.failed_closed = False

    @contextmanager
    def transaction(self):
        with self.mutex:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink():
                raise Stop("linked_ledger_refused")
            lock = self.path.with_suffix(self.path.suffix + ".lock")
            fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                rows = []
                if self.path.exists():
                    try:
                        rows = [
                            json.loads(line)
                            for line in self.path.read_text(
                                encoding="utf-8"
                            ).splitlines()
                            if line
                        ]
                    except (OSError, ValueError) as exc:
                        raise Stop("ledger_corrupt_or_unreadable") from exc
                if any(x.get("cycle_id") != self.cycle_id for x in rows):
                    raise Stop("ledger_cycle_mismatch")
                yield rows
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def append(self, event):
        event = dict(event, cycle_id=self.cycle_id)
        fd = os.open(
            self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        try:
            data = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
            if os.write(fd, data) != len(data):
                raise Stop("ledger_write_incomplete")
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def state(rows):
        requests = {}
        for row in rows:
            requests.setdefault(row["request_id"], {}).update(row)
        held = sum(
            (
                money(x["reserved_usd"])
                for x in requests.values()
                if x["event"] in {"reserved", "uncertain"}
            ),
            Decimal(0),
        )
        settled = sum(
            (money(x["actual_usd"]) for x in requests.values() if "actual_usd" in x),
            Decimal(0),
        )
        return {"requests": requests, "held_usd": held, "settled_usd": settled}

    def snapshot(self):
        with self.transaction() as rows:
            return self.state(rows)

    def reserve(self, request_id, amount, remaining, policy):
        amount, remaining = money(amount), money(remaining)
        with self.transaction() as rows:
            if self.failed_closed:
                raise Stop("guard_stopped_after_uncertain_outcome")
            state = self.state(rows)
            requests = state["requests"]
            if request_id in requests:
                raise Stop("duplicate_request_no_retry")
            if any(
                x["event"] in {"uncertain", "overrun"}
                or (x["event"] == "reserved" and x["boot_id"] != self.boot_id)
                for x in requests.values()
            ):
                raise Stop("unsettled_or_overrun_request")
            active = sum(x["event"] == "reserved" for x in requests.values())
            if active >= policy.max_inflight:
                raise Stop("concurrency_ceiling")
            if len(requests) >= policy.max_calls:
                raise Stop("call_ceiling")
            if state["settled_usd"] + state["held_usd"] + amount > policy.cap:
                raise Stop("cycle_spend_ceiling")
            if remaining - state["held_usd"] - amount < policy.credit_reserve:
                raise Stop("account_credit_reserve")
            self.append(
                {
                    "event": "reserved",
                    "request_id": request_id,
                    "boot_id": self.boot_id,
                    "reserved_usd": str(amount),
                }
            )
            return amount

    def settle(self, request_id, actual, generation_id):
        actual = money(actual)
        with self.transaction() as rows:
            item = self.state(rows)["requests"].get(request_id)
            if not item or item["event"] != "reserved":
                raise Stop("settlement_without_reservation")
            overrun = actual > money(item["reserved_usd"])
            if overrun:
                self.failed_closed = True
            self.append(
                {
                    "event": "overrun" if overrun else "settled",
                    "request_id": request_id,
                    "actual_usd": str(actual),
                    "generation_id": generation_id,
                }
            )

    def uncertain(self, request_id, reason):
        self.failed_closed = True
        with self.transaction() as rows:
            if request_id not in self.state(rows)["requests"]:
                raise Stop("unknown_reservation")
            self.append(
                {"event": "uncertain", "request_id": request_id, "reason": reason}
            )


def response_cost(body, stream, policy):
    try:
        if stream:
            frames = []
            data_lines = []
            for line in body.decode("utf-8").splitlines():
                if not line:
                    if data_lines:
                        frames.append("\n".join(data_lines))
                        data_lines = []
                elif line.startswith("event:") and line[6:].strip() == "error":
                    raise Stop("stream_error_envelope")
                elif line.startswith("data:"):
                    value = line[5:]
                    data_lines.append(value.removeprefix(" "))
                elif not line.startswith(":"):
                    raise Stop("unsupported_sse_field")
            if (
                data_lines
                or not frames
                or frames[-1] != "[DONE]"
                or "[DONE]" in frames[:-1]
            ):
                raise Stop("stream_incomplete")
            events = [json.loads(frame) for frame in frames[:-1]]
        else:
            events = [json.loads(body)]
        if not events or any(not isinstance(x, dict) or "error" in x for x in events):
            raise Stop("stream_error_envelope")
        models = {x["model"] for x in events if x.get("model")}
        if models != {policy.model}:
            raise Stop("resolved_model_unverified")
        ids = {x.get("id") for x in events}
        if len(ids) != 1:
            raise Stop("generation_id_inconsistent")
        gid = next(iter(ids))
        if not isinstance(gid, str) or not gid.strip() or len(gid) > 200:
            raise Stop("generation_id_missing")
        final = events[-1]
        if final.get("model") != policy.model or not isinstance(
            final.get("usage"), dict
        ):
            raise Stop("final_usage_model_binding_missing")
        cost = money(final["usage"].get("cost"))
        return cost, gid
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise Stop("usage_unparseable") from exc


def hash_artifact(root, cycle_id, work_order_id, filename, source_sha256):
    if not all(
        re.fullmatch(r"[A-Za-z0-9_-]{1,128}", x) for x in (cycle_id, work_order_id)
    ) or not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        raise Stop("unsafe_artifact_binding")
    if Path(filename).name != filename or filename in {".", ".."}:
        raise Stop("unsafe_artifact_filename")
    # Canonicalize the configured root (macOS /var is itself a platform link),
    # then refuse links in any operator artifact path beneath that root.
    root = Path(root).resolve(strict=True)
    handles = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        handles.append(os.open(root, directory_flags))
        handles.append(os.open(cycle_id, directory_flags, dir_fd=handles[-1]))
        handles.append(os.open(work_order_id, directory_flags, dir_fd=handles[-1]))
        handles.append(
            os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=handles[-1])
        )
        before = os.fstat(handles[-1])
        if not stat.S_ISREG(before.st_mode) or before.st_size > 1048576:
            raise Stop("artifact_size_or_type_ceiling")
        chunks = []
        size = 0
        while True:
            chunk = os.read(handles[-1], 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > 1048576:
                raise Stop("artifact_size_ceiling")
            chunks.append(chunk)
        after = os.fstat(handles[-1])
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise Stop("artifact_changed_during_readback")
        data = b"".join(chunks)
    except OSError as exc:
        raise Stop("missing_or_linked_artifact") from exc
    finally:
        for fd in reversed(handles):
            os.close(fd)
    return {
        "cycle_id": cycle_id,
        "work_order_id": work_order_id,
        "filename": filename,
        "source_sha256": source_sha256,
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "nonempty": bool(data.strip()),
        "acceptance_state": "not_evaluated",
    }


class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Stop("upstream_redirect_refused")


def no_redirect_opener():
    return build_opener(RefuseRedirect())


def upstream(path, key, payload=None, limit=4000000):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    data = (
        json.dumps(payload, allow_nan=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request("https://openrouter.ai/api/v1" + path, data=data, headers=headers)
    with no_redirect_opener().open(request, timeout=300 if data else 20) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise Stop("upstream_response_size_ceiling")
        return body


def make_server(
    ledger: Ledger, key: str, port: int, client_token: str | None = None
) -> ThreadingHTTPServer:
    policy = Policy()
    auth_token = client_token if client_token is not None else key
    if not isinstance(auth_token, str) or not auth_token:
        raise Stop("client_auth_token_missing")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # no URLs, keys, prompts, exception strings or response bodies

        def send_json(self, status, value):
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            reserved = False
            rid = uuid.uuid4().hex
            try:
                if self.path != "/v1/chat/completions" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + auth_token
                ):
                    raise Stop("route_or_auth_refused")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= policy.max_input_bound:
                    raise Stop("request_size_ceiling")
                payload = json.loads(self.rfile.read(size))
                validate_payload(payload, policy)
                # Read fresh account funds, not key allowance; any failure stops.
                credits = json.loads(upstream("/credits", key))["data"]
                remaining = money(credits["total_credits"]) - money(
                    credits["total_usage"]
                )
                models = json.loads(upstream("/models", key))["data"]
                catalog = next(x for x in models if x.get("id") == policy.model)
                amount = full_context_reservation(catalog, policy)
                ledger.reserve(rid, amount, remaining, policy)
                reserved = True
                payload["provider"] = {
                    "only": ["openai"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "data_collection": "deny",
                    "max_price": {
                        "prompt": float(policy.input_ceiling * 1000000),
                        "completion": float(policy.output_ceiling * 1000000),
                    },
                }
                if payload.get("stream"):
                    payload["stream_options"] = {"include_usage": True}
                body = upstream(
                    "/chat/completions", key, payload, policy.max_response_bytes
                )
                cost, generation_id = response_cost(
                    body, bool(payload.get("stream")), policy
                )
                ledger.settle(rid, cost, generation_id)
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/event-stream"
                    if payload.get("stream")
                    else "application/json",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (
                Stop,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                StopIteration,
            ) as exc:
                reason = (
                    str(exc) if isinstance(exc, Stop) else "guard_or_upstream_failure"
                )
                if reserved:
                    try:
                        ledger.uncertain(rid, reason)
                    except (OSError, ValueError, Stop):
                        # Preserve durable reservation and stop even if receipt
                        # append fails; never log private transport exceptions.
                        ledger.failed_closed = True
                self.send_json(
                    429,
                    {
                        "error": {
                            "message": reason,
                            "type": "momo_guard_stopped",
                            "request_id": rid,
                        },
                        "retry": False,
                    },
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--port", type=int, default=2042)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.cycle_id):
        parser.error("Unsafe cycle identifier")
    ledger = Ledger(args.ledger, args.cycle_id)
    if not args.serve:
        state = ledger.snapshot()
        print(json.dumps({k: str(v) for k, v in state.items() if k != "requests"}))
        return
    key = os.environ.get("MOMO_GUARD_UPSTREAM_API_KEY") or os.environ.get(
        "OPENROUTER_API_KEY"
    )
    client_token = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        parser.error("Existing OPENROUTER_API_KEY required; no new key is created")
    make_server(ledger, key, args.port, client_token).serve_forever()


if __name__ == "__main__":
    main()
