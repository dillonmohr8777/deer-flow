"""Disabled-by-default bridge to the original owner's retained JPY ledger.

This is infrastructure configuration, never a workflow request field. It creates
no allowance, refunds no hold, and records accepted usage separately from bills.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import NoReturn

MODEL = "glm-5.3-uncensored"
ROUTE = "hai-glm-5.3-uncensored"
SECTION = "workflow_hai_budget_bridge"
QUANTUM = Decimal("0.000001")
MAX_LEDGER_BYTES = 4 * 1024 * 1024
LOCK_SECONDS = 2.0
SHA = re.compile(r"[0-9a-f]{64}\Z")
CONTEXT = {"owner_scope", "actor", "organization", "storage_user", "run_id", "workflow_id"}
REQUEST = CONTEXT | {"provider", "model", "call_id", "effort", "input_token_limit", "max_output_tokens", "request_sha256", "serialized_payload_bytes"}
PURPOSES = {
    "qualification": ("qualification_reservation_cap_jpy", "hai-test-reservations.jsonl", Decimal(150)),
    "real_work_comparison": ("real_work_comparison_cap_jpy", "hai-real-work-reservations.jsonl", Decimal(300)),
}


class BudgetBridgeError(RuntimeError):
    """Secret-safe, fixed error; no file content or exception text escapes."""

    def __init__(self):
        super().__init__("provider_allowance_unverified")


def _deny() -> NoReturn:
    raise BudgetBridgeError()


def _closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        _deny()
    return value


def _decimal(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _deny()
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        _deny()
    if not result.is_finite() or result < 0:
        _deny()
    return result


def _bound(payload_bytes, output_tokens):
    for value, lower, upper in ((payload_bytes, 1, 262144), (output_tokens, 32, 2048)):
        if type(value) is not int or not lower <= value <= upper:
            _deny()
    return ((Decimal(payload_bytes) + 16384) * 600 / 1_000_000 + Decimal(output_tokens) * 1000 / 1_000_000 + 1).quantize(QUANTUM, rounding=ROUND_CEILING)


def _hash(value) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        _deny()
    return value


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _deny()
            result[key] = value
        return result

    return json.loads(raw, parse_float=Decimal, parse_constant=lambda _: _deny(), object_pairs_hook=pairs)


def _path(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        _deny()
    path = Path(value)
    if path.resolve(strict=True) != path:
        _deny()
    return path


def _safe_stat(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
        _deny()
    return info


def _pinned_raw(pin):
    _closed(pin, {"path", "sha256"})
    path = _path(pin["path"])
    _safe_stat(path)
    if path.stat().st_size > 131072:
        _deny()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _hash(pin["sha256"]):
        _deny()
    return raw


def _pinned_file(pin):
    result = _json(_pinned_raw(pin))
    if not isinstance(result, dict):
        _deny()
    return result


def _fresh(value):
    if not isinstance(value, str):
        _deny()
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = datetime.now(UTC) - stamp
    except (ValueError, TypeError):
        _deny()
    if stamp.tzinfo is None or age < timedelta(minutes=-5) or age > timedelta(hours=24):
        _deny()


class OriginalOwnerJPYBridge:
    """One selected original ledger; all legacy and native reservations stay held."""

    def __init__(self, configuration: dict, *, credential_sha256: str):
        self.configuration = configuration
        self.credential_sha256 = _hash(credential_sha256)
        try:
            self._validate_evidence()
        except Exception:
            raise BudgetBridgeError() from None

    def _validate_evidence(self):
        cfg = _closed(self.configuration, {"enabled", "purpose", "approved_budget", "read_metadata", "billing_readback", "pricing", "owner_binding", "source_acceptance", "related_owner_ledger", "ledger"})
        if cfg["enabled"] is not True or cfg["purpose"] not in PURPOSES:
            _deny()
        approved = _pinned_file(cfg["approved_budget"])
        purpose_field, filename, original_cap = PURPOSES[cfg["purpose"]]
        if _decimal(approved.get(purpose_field)) != original_cap or _decimal(approved.get("new_cash_spend_cap")) != 10:
            _deny()
        if approved.get("currency") != "USD" or approved.get("automatic_recharge") is not False or approved.get("subscription") is not False:
            _deny()
        source_owner = approved.get("source_thread")
        if not isinstance(source_owner, str) or not source_owner:
            _deny()
        ledger = _closed(cfg["ledger"], {"path", "prefix_bytes", "prefix_sha256", "device", "inode"})
        ledger_path = _path(ledger["path"])
        if ledger_path != Path(cfg["approved_budget"]["path"]).parent / filename:
            _deny()
        for key in ("prefix_bytes", "device", "inode"):
            if type(ledger[key]) is not int or ledger[key] <= 0:
                _deny()
        _hash(ledger["prefix_sha256"])
        if ledger["prefix_bytes"] > MAX_LEDGER_BYTES:
            _deny()
        info = _safe_stat(ledger_path)
        if (info.st_dev, info.st_ino) != (ledger["device"], ledger["inode"]):
            _deny()
        price = _pinned_file(cfg["pricing"])
        if (price.get("kind"), price.get("provider"), price.get("model"), price.get("currency")) != ("brain_forge_hai_price_evidence", "hai", MODEL, "JPY"):
            _deny()
        _fresh(price.get("observed_at_utc"))
        if _decimal(price.get("input_jpy_per_million_tokens")) != 600 or _decimal(price.get("output_jpy_per_million_tokens")) != 1000 or _decimal(price.get("billing_quantum_jpy")) != QUANTUM:
            _deny()
        for key in ("prices_tax_inclusive", "reasoning_included_in_output_tokens", "responses_input_includes_cache_tokens", "cache_discount_not_assumed_for_reservations"):
            if price.get(key) is not True:
                _deny()
        if price.get("provider_minimum_charge") is not False or _decimal(price.get("credit_jpy")) != 1:
            _deny()
        sources = price.get("sources")
        urls = {"https://hai.hcloud.ltd/models/glm-5.3-uncensored", "https://hai.hcloud.ltd/pricing", "https://hai.hcloud.ltd/docs/billing/", "https://hai.hcloud.ltd/docs/reasoning/"}
        if not isinstance(sources, list) or len(sources) != len(urls) or {item.get("url") for item in sources if isinstance(item, dict)} != urls:
            _deny()
        for item in sources:
            if item.get("status_code") != 200 or item.get("required_terms_verified") is not True:
                _deny()
            _hash(item.get("body_sha256"))
        metadata = _pinned_file(cfg["read_metadata"])
        billing = _pinned_file(cfg["billing_readback"])
        for receipt, kind in ((metadata, "brain_forge_hai_protected_read_metadata"), (billing, "brain_forge_hai_billing_readback")):
            if (
                receipt.get("kind") != kind
                or receipt.get("provider") != "hai"
                or receipt.get("source_owner_thread") != source_owner
                or receipt.get("credential_reference") != "Keychain:hai.primary"
                or receipt.get("fixed_origin") != "https://hai-api.hcloud.ltd"
            ):
                _deny()
            _fresh(receipt.get("observed_at_utc"))
        account = billing["requests"]["account"]
        observed_account = _hash(account.get("owner_account_sha256"))
        if account.get("status_code") != 200 or metadata["requests"]["me"].get("status_code") != 200 or metadata["requests"]["me"].get("owner_account_sha256") != observed_account:
            _deny()
        billed = billing["requests"]["billing"]
        if billed.get("status_code") != 200 or type(billed.get("rows")) is not int or not 0 <= billed["rows"] < billed.get("pagination_limit", 0):
            _deny()
        total_debited = _decimal(billed.get("returned_rows_debitedJpy_sum"))
        if _decimal(account.get("balance_jpy")) < original_cap:
            _deny()
        related_pin = cfg["related_owner_ledger"]
        if _path(related_pin.get("path")) != Path(cfg["approved_budget"]["path"]).parent / "glm_team/state/budget.jsonl":
            _deny()
        related_rows = [_json(row) for row in _pinned_raw(related_pin).splitlines()]
        if not related_rows or any(not isinstance(row, dict) or set(row) != {"amount", "event", "id", "route", "time"} or row["event"] not in {"reserve", "settle"} or row["route"] not in {"hai", "sol", "spark"} for row in related_rows):
            _deny()
        related_holds, related_settled = {}, set()
        for row in related_rows:
            if not isinstance(row["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["id"]):
                _deny()
            amount = _decimal(row["amount"])
            _decimal(row["time"])
            if row["event"] == "reserve":
                if row["id"] in related_holds:
                    _deny()
                related_holds[row["id"]] = (row["route"], amount)
            else:
                original = related_holds.get(row["id"])
                if not original or row["id"] in related_settled or row["route"] != original[0] or amount > original[1]:
                    _deny()
                related_settled.add(row["id"])
        unresolved_hai = sum((amount for identity, (route, amount) in related_holds.items() if route == "hai" and identity not in related_settled), Decimal(0))
        if Path(related_pin["path"]).parent.joinpath("STOP").exists():
            _deny()
        binding = _pinned_file(cfg["owner_binding"])
        fields = {
            "kind",
            "accepted",
            "accepted_at_utc",
            "source_acceptance_sha256",
            "source_owner_thread",
            "owner_account_sha256",
            "credential_sha256",
            "purpose",
            "approved_budget_sha256",
            "ledger_path",
            "ledger_prefix_bytes",
            "ledger_prefix_sha256",
            "cap_jpy",
            "pricing_sha256",
            "read_metadata_sha256",
            "billing_readback_sha256",
            "current_activity_reconciled",
            "activity_allocation",
            "observed_billing_total_debited_jpy",
            "original_request_cost_attribution",
            "retained_original_holds",
            "new_cash_spend_cap_usd",
            "automatic_recharge",
            "native_workflows_authorized",
            "accepted_workflow_ids",
            "expires_at_utc",
            "owner_scope",
            "actor",
            "organization",
            "storage_user",
        }
        _closed(binding, fields)
        if binding["kind"] != "brain_forge_hai_owner_bridge_acceptance" or any(binding[key] is not True for key in ("accepted", "current_activity_reconciled", "retained_original_holds", "native_workflows_authorized")):
            _deny()
        _fresh(binding["accepted_at_utc"])
        try:
            accepted_at = datetime.fromisoformat(binding["accepted_at_utc"].replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(binding["expires_at_utc"].replace("Z", "+00:00"))
            if not accepted_at < expires_at <= accepted_at + timedelta(hours=24) or datetime.now(UTC) >= expires_at:
                _deny()
        except (ValueError, TypeError, AttributeError):
            _deny()
        if accepted_at > datetime.now(UTC):
            _deny()
        observed = [datetime.fromisoformat(receipt["observed_at_utc"].replace("Z", "+00:00")) for receipt in (price, metadata, billing)]
        if any(accepted_at < stamp for stamp in observed):
            _deny()
        proof = _pinned_file(cfg["source_acceptance"])
        _closed(proof, {"kind", "source_thread", "source_role", "source_actor", "source_message_id", "source_message_sha256", "accepted_mapping_sha256", "verification_method"})
        if (
            proof["kind"] != "brain_forge_hai_original_owner_acceptance_proof"
            or proof["source_thread"] != source_owner
            or proof["source_role"] != "user"
            or proof["source_actor"] != binding["actor"]
            or proof["verification_method"] != "operator_attested_original_owner_user_record"
        ):
            _deny()
        if not isinstance(proof["source_message_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", proof["source_message_id"]):
            _deny()
        _hash(proof["source_message_sha256"])
        mapping = {key: value for key, value in binding.items() if key != "source_acceptance_sha256"}
        if binding["source_acceptance_sha256"] != cfg["source_acceptance"]["sha256"] or proof["accepted_mapping_sha256"] != hashlib.sha256(_encode(mapping)).hexdigest():
            _deny()
        identifiers = binding["accepted_workflow_ids"]
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 10 or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_-]{1,128}", item) for item in identifiers) or len(set(identifiers)) != len(identifiers):
            _deny()
        if binding["source_owner_thread"] != source_owner or binding["owner_account_sha256"] != observed_account or binding["credential_sha256"] != self.credential_sha256 or binding["purpose"] != cfg["purpose"]:
            _deny()
        if binding["ledger_path"] != str(ledger_path) or binding["ledger_prefix_bytes"] != ledger["prefix_bytes"] or binding["ledger_prefix_sha256"] != ledger["prefix_sha256"] or _decimal(binding["cap_jpy"]) != original_cap:
            _deny()
        for name in ("approved_budget", "pricing", "read_metadata", "billing_readback"):
            if binding[f"{name}_sha256"] != cfg[name]["sha256"]:
                _deny()
        if (
            _decimal(binding["new_cash_spend_cap_usd"]) != 10
            or binding["automatic_recharge"] is not False
            or _decimal(binding["observed_billing_total_debited_jpy"]) != total_debited
            or binding["original_request_cost_attribution"] != "unverified"
        ):
            _deny()
        for key in ("owner_scope", "actor", "storage_user"):
            if not isinstance(binding[key], str) or not 1 <= len(binding[key]) <= 2048:
                _deny()
        if binding["organization"] is not None and (not isinstance(binding["organization"], str) or not 1 <= len(binding["organization"]) <= 2048):
            _deny()
        allocation = _closed(
            binding["activity_allocation"],
            {
                "policy",
                "selected_ledger_path",
                "purpose",
                "cap_jpy",
                "amount_jpy",
                "billing_component_jpy",
                "related_unsettled_hai_component_jpy",
                "billing_readback_sha256",
                "related_owner_ledger_sha256",
                "related_owner_ledger_disposition",
            },
        )
        if allocation["policy"] != "conservative_billing_and_unsettled_holds" or allocation["selected_ledger_path"] != str(ledger_path) or allocation["purpose"] != cfg["purpose"] or _decimal(allocation["cap_jpy"]) != original_cap:
            _deny()
        if (
            _decimal(allocation["amount_jpy"]) != total_debited + unresolved_hai
            or _decimal(allocation["billing_component_jpy"]) != total_debited
            or _decimal(allocation["related_unsettled_hai_component_jpy"]) != unresolved_hai
            or allocation["billing_readback_sha256"] != cfg["billing_readback"]["sha256"]
            or allocation["related_owner_ledger_sha256"] != related_pin["sha256"]
            or allocation["related_owner_ledger_disposition"] != "overlap_unverified_all_unsettled_holds_retained"
        ):
            _deny()
        if any(accepted_at.timestamp() < float(_decimal(row["time"])) for row in related_rows):
            _deny()
        self.activity_amount = (total_debited + unresolved_hai).quantize(QUANTUM, rounding=ROUND_CEILING)
        self.activity_identity = hashlib.sha256(_encode({"billing": cfg["billing_readback"]["sha256"], "related": related_pin["sha256"], "owner": cfg["owner_binding"]["sha256"]})).hexdigest()
        self.path, self.cap, self.binding, self.source_owner = ledger_path, original_cap, binding, source_owner

    def _request(self, request):
        _closed(request, REQUEST)
        if request["provider"] != "hai" or request["model"] != MODEL or request["effort"] != "low":
            _deny()
        for key in CONTEXT - {"run_id", "workflow_id"}:
            if request[key] != self.binding[key]:
                _deny()
        if request["workflow_id"] not in self.binding["accepted_workflow_ids"]:
            _deny()
        for key in ("run_id", "call_id"):
            if not isinstance(request[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request[key]):
                _deny()
        _hash(request["request_sha256"])
        for key, lower, upper in (("input_token_limit", 1, 60000), ("max_output_tokens", 32, 2048), ("serialized_payload_bytes", 1, 262144)):
            if type(request[key]) is not int or not lower <= request[key] <= upper:
                _deny()
        identity = hashlib.sha256(_encode({key: request[key] for key in sorted(CONTEXT | {"call_id"})})).hexdigest()
        # Original protocol: full serialized request byte ceiling + 16,384
        # framing tokens, output ceiling, then JPY1 margin. Never assume cache.
        bound = _bound(request["serialized_payload_bytes"], request["max_output_tokens"])
        return identity, bound

    async def __call__(self, request):
        await self._operation(request, None)
        return True

    async def record_usage(self, request, result):
        """Append an accepted-output/usage audit; actual billed JPY stays unknown."""
        _closed(result, {"model", "response_id", "input_tokens", "output_tokens", "output_sha256"})
        if result["model"] != MODEL:
            _deny()
        for key in ("input_tokens", "output_tokens"):
            if type(result[key]) is not int or result[key] < 0:
                _deny()
        if not isinstance(result["response_id"], str) or not 1 <= len(result["response_id"]) <= 2048:
            _deny()
        _hash(result["output_sha256"])
        await self._operation(request, result)

    async def _operation(self, request, result):
        canceled = threading.Event()
        deadline = time.monotonic() + LOCK_SECONDS
        task = asyncio.create_task(asyncio.to_thread(self._append, request, result, canceled, deadline))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            canceled.set()
            # Drain the bounded lock worker before returning cancellation. A
            # reservation that raced cancellation remains held; never dispatch.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    canceled.set()
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            raise
        except Exception:
            raise BudgetBridgeError() from None

    def _append(self, request, result, canceled, deadline):
        self._validate_evidence()
        identity, bound = self._request(request)
        pin = self.configuration["ledger"]

        def active():
            if canceled.is_set() or time.monotonic() >= deadline:
                _deny()

        active()
        descriptor = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
        try:
            while True:
                active()
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    canceled.wait(0.01)
            info = os.fstat(descriptor)
            current = _safe_stat(self.path)
            if (info.st_dev, info.st_ino) != (pin["device"], pin["inode"]) or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino) or not pin["prefix_bytes"] <= info.st_size <= MAX_LEDGER_BYTES:
                _deny()
            raw = os.pread(descriptor, info.st_size, 0)
            if len(raw) != info.st_size or not raw.endswith(b"\n") or hashlib.sha256(raw[: pin["prefix_bytes"]]).hexdigest() != pin["prefix_sha256"]:
                _deny()
            total, checks, holds, audited = Decimal(0), set(), {}, set()
            activity_seen = False
            for line in raw.splitlines():
                row = _json(line)
                if not isinstance(row, dict) or set(row) not in ({"check", "reserved_jpy", "cap_jpy"}, {"check", "reserved_jpy", "cap_jpy", "brainforge_native"}):
                    _deny()
                if not isinstance(row["check"], str) or not row["check"] or row["check"] in checks or _decimal(row["cap_jpy"]) != self.cap:
                    _deny()
                checks.add(row["check"])
                if any(isinstance(row[key], (str, bool)) or not isinstance(row[key], (int, float, Decimal)) for key in ("reserved_jpy", "cap_jpy")):
                    _deny()
                amount = _decimal(row["reserved_jpy"])
                total += amount
                if "brainforge_native" in row:
                    metadata = row["brainforge_native"]
                    if not isinstance(metadata, dict) or metadata.get("version") != 1 or metadata.get("source_owner_thread") != self.source_owner or metadata.get("owner_binding_sha256") != self.configuration["owner_binding"]["sha256"]:
                        _deny()
                    row_identity = _hash(metadata.get("identity"))
                    common = {"version", "event", "source_owner_thread", "owner_binding_sha256", "identity"}
                    event = metadata.get("event")
                    if event == "reserve":
                        _closed(metadata, common | {"request_sha256", "serialized_payload_bytes", "max_output_tokens", "protocol_allowance_tokens", "pricing_sha256"})
                        if (
                            metadata["protocol_allowance_tokens"] != 16384
                            or metadata["pricing_sha256"] != self.configuration["pricing"]["sha256"]
                            or amount != _bound(metadata["serialized_payload_bytes"], metadata["max_output_tokens"])
                            or row["check"] != "brainforge-native-reserve-" + row_identity
                        ):
                            _deny()
                        _hash(metadata["request_sha256"])
                    elif event == "accepted_usage_audit":
                        _closed(metadata, common | {"request_sha256", "accepted_usage_proof_sha256", "input_tokens", "output_tokens", "served_model", "actual_billed_cost_jpy", "reservation_released"})
                        if metadata["served_model"] != MODEL or row["check"] != "brainforge-native-usage-" + row_identity or any(type(metadata[key]) is not int or metadata[key] < 0 for key in ("input_tokens", "output_tokens")):
                            _deny()
                        _hash(metadata["accepted_usage_proof_sha256"])
                    elif event == "source_approved_activity_hold":
                        _closed(metadata, common | {"billing_readback_sha256", "related_owner_ledger_sha256"})
                        if row["check"] != "brainforge-native-account-activity-" + row_identity:
                            _deny()
                    if metadata.get("event") == "source_approved_activity_hold":
                        if (
                            activity_seen
                            or row_identity != self.activity_identity
                            or amount != self.activity_amount
                            or metadata.get("billing_readback_sha256") != self.configuration["billing_readback"]["sha256"]
                            or metadata.get("related_owner_ledger_sha256") != self.configuration["related_owner_ledger"]["sha256"]
                        ):
                            _deny()
                        activity_seen = True
                    elif metadata.get("event") == "reserve":
                        if row_identity in holds or amount <= 0:
                            _deny()
                        holds[row_identity] = metadata
                    elif metadata.get("event") == "accepted_usage_audit":
                        if (
                            amount != 0
                            or row_identity not in holds
                            or metadata["request_sha256"] != holds[row_identity]["request_sha256"]
                            or row_identity in audited
                            or metadata.get("actual_billed_cost_jpy") is not None
                            or metadata.get("reservation_released") is not False
                        ):
                            _deny()
                        audited.add(row_identity)
                    else:
                        _deny()
            if total > self.cap:
                _deny()
            metadata = {"version": 1, "source_owner_thread": self.source_owner, "owner_binding_sha256": self.configuration["owner_binding"]["sha256"], "identity": identity, "request_sha256": request["request_sha256"]}
            if result is None:
                activity_needed = Decimal(0) if activity_seen else self.activity_amount
                if identity in holds or total + activity_needed + bound > self.cap:
                    _deny()
                metadata.update(
                    event="reserve", serialized_payload_bytes=request["serialized_payload_bytes"], max_output_tokens=request["max_output_tokens"], protocol_allowance_tokens=16384, pricing_sha256=self.configuration["pricing"]["sha256"]
                )
                amount, check = bound, "brainforge-native-reserve-" + identity
            else:
                hold = holds.get(identity)
                if not activity_seen or not hold or hold.get("request_sha256") != request["request_sha256"] or identity in audited:
                    _deny()
                if result["output_tokens"] > request["max_output_tokens"] or result["input_tokens"] > request["serialized_payload_bytes"] + 16384:
                    _deny()
                metadata.update(
                    event="accepted_usage_audit",
                    accepted_usage_proof_sha256=hashlib.sha256(_encode(result)).hexdigest(),
                    input_tokens=result["input_tokens"],
                    output_tokens=result["output_tokens"],
                    served_model=MODEL,
                    actual_billed_cost_jpy=None,
                    reservation_released=False,
                )
                amount, check = Decimal(0), "brainforge-native-usage-" + identity
            row = {"check": check, "reserved_jpy": float(amount), "cap_jpy": int(self.cap), "brainforge_native": metadata}
            encoded = _encode(row) + b"\n"
            if result is None and not activity_seen:
                # This exact additional retained hold requires the source-approved
                # allocation mapping. Unknown allocation never reaches this path.
                activity = {
                    "check": "brainforge-native-account-activity-" + self.activity_identity,
                    "reserved_jpy": float(self.activity_amount),
                    "cap_jpy": int(self.cap),
                    "brainforge_native": {
                        "version": 1,
                        "event": "source_approved_activity_hold",
                        "identity": self.activity_identity,
                        "source_owner_thread": self.source_owner,
                        "owner_binding_sha256": self.configuration["owner_binding"]["sha256"],
                        "billing_readback_sha256": self.configuration["billing_readback"]["sha256"],
                        "related_owner_ledger_sha256": self.configuration["related_owner_ledger"]["sha256"],
                    },
                }
                encoded = _encode(activity) + b"\n" + encoded
            active()
            # Recheck same path identity immediately before the append. Atomic
            # local serialization is shared with the original helper's flock.
            current = _safe_stat(self.path)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                _deny()
            if os.write(descriptor, encoded) != len(encoded):
                _deny()  # Partial/uncertain records fail closed on the next read.
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def create_workflow_model_adapter(startup_config):
    """Wire only server startup extras; absent/disabled preserves OpenAI behavior."""
    from app.gateway.workflow_adapters import ROUTE_ENV, WorkflowModelAdapter

    # Only a real validated dictionary can carry bridge infrastructure.
    # Duck-typed/default startup fixtures cannot accidentally enable a route.
    extras = getattr(startup_config, "model_extra", None)
    configuration = extras.get(SECTION) if isinstance(extras, dict) else None
    bridge = None
    if configuration is not None:
        if not isinstance(configuration, dict) or type(configuration.get("enabled")) is not bool:
            _deny()
        if configuration["enabled"] is False:
            _closed(configuration, {"enabled"})
        else:
            if os.environ.get(ROUTE_ENV, "openai") != ROUTE:
                _deny()
            key = os.environ.get("HAI_API_KEY")
            if not key:
                _deny()
            bridge = OriginalOwnerJPYBridge(configuration, credential_sha256=hashlib.sha256(key.encode()).hexdigest())
    return WorkflowModelAdapter(provider_admission=bridge) if bridge is not None else WorkflowModelAdapter()
