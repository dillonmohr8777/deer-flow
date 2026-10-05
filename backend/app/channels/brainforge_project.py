"""Compile one private Brain Forge project through existing native contracts.

This joins a protected brief snapshot, reviewed research and marketing inputs.
It prepares requests for Momo's existing workflow service; it cannot dispatch,
create an allowance, write canonical work or interpret evidence as authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

WORKFLOW_LANES = {
    "research": "personal-research-note",
    "offers": "landing-page-wireframe",
    "seo": "seo-aeo-answer-plan",
    "social": "social-caption-drafts",
    "crm": "lead-quality-analysis",
    "reporting": "monthly-marketing-report",
    "developer_blockers": "project-dependency-map",
    "security_review": "security-boundary-review",
}
MAX_INPUT_BYTES = 48_000
MAX_FILE_BYTES = 2_000_000
_SECRET = re.compile(
    r"\b(?:password|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)[\"']?\s*[:=]\s*\S+"
    r"|\bxox[baprs]-[A-Za-z0-9-]+|\bsk-[A-Za-z0-9_-]{16,}|\b(?:xpl|hai)_[A-Za-z0-9_-]{12,}",
    re.IGNORECASE,
)


def _credential_shaped(value: Any) -> bool:
    if isinstance(value, str):
        return _SECRET.search(value) is not None
    if isinstance(value, dict):
        return _SECRET.search(json.dumps(value, ensure_ascii=False)) is not None or any(_credential_shaped(child) for child in value.values())
    if isinstance(value, list):
        return any(_credential_shaped(child) for child in value)
    return False


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _pinned(pin: dict) -> bytes:
    path = Path(pin["path"]).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("project input must not traverse a symlink")
    expected = pin.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("project input requires a complete SHA256 pin")
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("project input missing or oversized")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES or _digest(raw) != expected:
        raise ValueError("project source drift; reviewed hash no longer matches")
    return raw


def _json(pin: dict) -> dict:
    value = json.loads(_pinned(pin), object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError("project input must be a JSON object")
    return value


def _reject_refs(value: Any) -> None:
    if isinstance(value, dict):
        if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
            raise ValueError("native schema references are not permitted in offline project compilation")
        for child in value.values():
            _reject_refs(child)
    elif isinstance(value, list):
        for child in value:
            _reject_refs(child)


class BrainForgeProjectCompiler:
    """Deterministic projection. Missing inputs stay missing; nothing is sent."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.native_supervisor = config.get("native_request_supervisor", True)
        if not isinstance(self.native_supervisor, bool):
            raise ValueError("native supervisor mode must match the reviewed API contract")
        self.inputs = config.get("inputs", {})
        if not isinstance(self.inputs, dict) or set(self.inputs) - set(WORKFLOW_LANES):
            raise ValueError("unknown project lane")
        research = config.get("research")
        if research is not None:
            if self._research_mode(research) == "original_x_pilot":
                from app.channels.brainforge_research_handoff import original_source_pins

                original_source_pins(research)
                if "research" in self.inputs:
                    raise ValueError("original research cannot be overridden by a lane packet")
        _pinned(config["control"])
        self.catalog = self._catalog()
        collector = config.get("collector", {})
        if collector.get("total_budget_usd") != 16:
            raise ValueError("existing X pilot has one $16 total ceiling")

    @staticmethod
    def _research_mode(config: Any) -> str:
        if not isinstance(config, dict):
            raise ValueError("unknown research mode")
        mode = config.get("kind", "reviewed_js")
        if not isinstance(mode, str) or mode not in {"reviewed_js", "original_x_pilot"}:
            raise ValueError("unknown research mode")
        return mode

    def _catalog(self) -> dict:
        rows = _json(self.config["catalog"]).get("workflows")
        if not isinstance(rows, list):
            raise ValueError("native catalog must contain workflow definitions")
        result = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in result:
                raise ValueError("native catalog has invalid or duplicate IDs")
            schema = row.get("input_schema")
            if not isinstance(schema, dict):
                raise ValueError("native input schema missing")
            _reject_refs(schema)
            Draft202012Validator.check_schema(schema)
            result[row["id"]] = schema
        return result

    def _request(self, lane: str, inputs: dict) -> dict:
        workflow_id = WORKFLOW_LANES[lane]
        schema = self.catalog.get(workflow_id)
        if schema is None:
            raise ValueError("selected workflow is unavailable in pinned native catalog")
        try:
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(inputs)
            raw_inputs = json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode()
        except (ValidationError, TypeError, ValueError):
            raise ValueError("native input schema rejected project inputs") from None
        if len(raw_inputs) > MAX_INPUT_BYTES or _credential_shaped(inputs):
            raise ValueError("native request oversized or credential-shaped")
        request = {"workflow_id": workflow_id, "inputs": inputs, "framework": "langgraph"}
        if self.native_supervisor:
            request["supervisor"] = True
        body = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(body.encode()) > MAX_INPUT_BYTES:
            raise ValueError("native request oversized")
        digest = _digest(body.encode())
        return {
            "status": "prepared_request",
            "request": request,
            "requestJson": body,
            "requestSha256": digest,
            "idempotencyKey": "brainforge-" + digest,
            "endpoint": "/api/workflows/runs",
            "sent": False,
            "supervisorRequested": self.native_supervisor,
            "ownerScope": None,
            "dispatchBlockers": ["authenticated owner/workspace scope", "existing reconciled finite allowance", "reviewed dispatch", "installed catalog readback"],
        }

    def _research(self, client_id: str) -> dict | None:
        config = self.config.get("research")
        if not config:
            return None
        mode = self._research_mode(config)
        if mode == "original_x_pilot" and "research" in self.inputs:
            raise ValueError("original research cannot be overridden by a lane packet")
        # Personal research evidence never routes to a client lane implicitly.
        if client_id != "__owner__":
            return {"status": "different_client_scope"}
        if mode == "original_x_pilot":
            from app.channels.brainforge_research_handoff import prepare_original_handoff

            prepared = prepare_original_handoff(config, _pinned, _credential_shaped)
            if prepared["inputs"] is None:
                return {"status": "needs_reviewed_inputs", "workflowId": WORKFLOW_LANES["research"], "reason": "empty_original_evidence", "researchOrigin": prepared["origin"]}
            result = self._request("research", prepared["inputs"])
            result["researchOrigin"] = prepared["origin"]
            return result
        pins = config.get("source_files", [])
        if not pins:
            raise ValueError("complete reviewed research program pins required")
        for pin in pins:
            _pinned(pin)
        source_root = Path(config["source_root"]).absolute()
        # Pin the complete recovered JS tree, including transitive requires.
        actual_files = {str(path.absolute()) for path in source_root.rglob("*.js") if path.is_file()}
        pinned_files = {str(Path(pin["path"]).absolute()) for pin in pins}
        if not actual_files or actual_files != pinned_files or source_root.is_symlink() or any(parent.is_symlink() for parent in source_root.parents):
            raise ValueError("complete reviewed research program pins required")
        evidence = config["reviewed_evidence"]
        _pinned(evidence)
        entrypoint = Path(config["entrypoint"]).absolute()
        if str(entrypoint) not in {str(Path(pin["path"]).absolute()) for pin in pins}:
            raise ValueError("research entrypoint must be hash pinned")
        node = Path(config["node_binary"])
        if not node.is_absolute() or not node.is_file():
            raise ValueError("existing absolute Node runtime required")
        run = subprocess.run(
            [str(node), str(entrypoint), "--reviewed-evidence", evidence["path"], "--no-network"],
            capture_output=True,
            timeout=30,
            check=False,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        if run.returncode or len(run.stdout) > MAX_FILE_BYTES:
            raise ValueError("reviewed research compiler failed")
        prepared = json.loads(run.stdout, object_pairs_hook=_unique)
        request = prepared.get("request", {})
        if request.get("workflow_id") != WORKFLOW_LANES["research"] or prepared.get("context", {}).get("sent") is not False:
            raise ValueError("research output is not an unsent native request")
        result = self._request("research", request["inputs"])
        result["researchOrigin"] = prepared["origin"]
        return result

    def _model(self) -> dict:
        pin = self.config.get("model")
        if not pin:
            return {"required": "full abliterated GLM 5.3", "status": "callable_authenticated_endpoint_unverified", "fallbackEnabled": False}
        route = _json(pin)
        if route.get("kind") != "brain_forge_model_route" or route.get("provider") != "hai" or route.get("model") != "glm-5.3-uncensored" or route.get("base_url") != "https://hai-api.hcloud.ltd/v1":
            raise ValueError("model receipt does not bind the reviewed full GLM route")
        if route.get("route_status") != "tested_provider_route" or route.get("transport") != "responses" or route.get("tested_reasoning_effort") != "low":
            raise ValueError("model qualification does not match the tested transport and effort")
        evidence = route.get("evidence_files", [])
        if not evidence:
            raise ValueError("model qualification requires existing acceptance receipts")
        for proof in evidence:
            _pinned(proof)
        return {
            "required": "full abliterated GLM 5.3",
            "provider": "hai",
            "model": route["model"],
            "status": "tested_provider_route; Momo live installation unverified",
            "testedReasoningEffort": "low",
            "transport": "responses",
            "routeReceiptSha256": pin["sha256"],
            "servingRevision": route.get("serving_revision"),
            "costPerRequest": route.get("actual_cost"),
            "lineage": "provider-linked full edited checkpoint; exact served revision unreported",
            "fallbackEnabled": False,
        }

    def compile(self, snapshot: dict, *, client_id: str) -> dict:
        _pinned(self.config["control"])
        self.catalog = self._catalog()
        known = {row["id"]: row for row in snapshot["clients"]}
        if client_id != "__owner__" and client_id not in known:
            raise ValueError("project route not in pinned registry")
        lanes = {lane: {"status": "needs_reviewed_inputs", "workflowId": identifier} for lane, identifier in WORKFLOW_LANES.items()}
        research = self._research(client_id)
        if research:
            lanes["research"] = research
        for lane, pin in self.inputs.items():
            packet = _json(pin)
            if set(packet) != {"clientId", "inputs"} or not isinstance(packet["inputs"], dict):
                raise ValueError("reviewed lane input requires clientId and inputs only")
            scope = packet["clientId"]
            if scope != client_id:
                lanes[lane] = {"status": "different_client_scope"}
                continue
            if scope != "__owner__" and known[scope].get("status") != "active":
                lanes[lane] = {"status": "inactive_client_scope"}
                continue
            lanes[lane] = self._request(lane, packet["inputs"])
        actions, held = [], 0
        for index, row in enumerate(snapshot["workItems"]):
            if row.get("status") in {"done", "cancelled"} or (client_id != "__owner__" and row.get("clientId") != client_id):
                continue
            route = known.get(row.get("clientId"))
            if route is None or route.get("status") != "active":
                held += 1
                continue
            actions.append(
                {
                    "workId": row["id"],
                    "clientId": row.get("clientId"),
                    "recordedStatus": row.get("status"),
                    "title": row.get("title"),
                    "owner": row.get("owner"),
                    "nextAction": row.get("nextAction"),
                    "sourceRef": f"queue/work-items.json#/workItems/{index}",
                    "approval": row.get("approval"),
                    "freshness": "pinned queue evidence; no live verification",
                    "executionAuthorized": False,
                }
            )
        order = {"blocked": 0, "needs_approval": 1, "deferred": 2}
        actions.sort(key=lambda row: (order.get(row["recordedStatus"], 3), row["workId"]))
        collector = self.config["collector"]
        ledger = collector.get("ledger")
        if ledger:
            _pinned(ledger)
        result = {
            "kind": "brain_forge_unified_project",
            "status": "prepared_private_project",
            "clientId": client_id,
            "lanes": lanes,
            "prioritizedActions": actions,
            "heldRoutes": held,
            "requestCount": sum(row["status"] == "prepared_request" for row in lanes.values()),
            "collector": {"totalBudgetUsd": 16, "recurringBudget": False, "status": "existing_ledger_referenced" if ledger else "original_ledger_unresolved", "dispatchEnabled": False},
            "model": self._model(),
            "networkCalls": 0,
            "canonicalWritten": False,
            "sourceAccepted": False,
            "sent": False,
            "acceptance": "Prepared inputs and source projections. Runtime, useful resulting artifacts and one Momentum fix still require verification.",
        }
        # Detect source/program changes during compilation before publishing output.
        _pinned(self.config["control"])
        self._catalog()
        for pin in self.inputs.values():
            _pinned(pin)
        if self.config.get("research"):
            research_config = self.config["research"]
            if self._research_mode(research_config) == "original_x_pilot":
                from app.channels.brainforge_research_handoff import validate_original_pins

                validate_original_pins(research_config, _pinned, _credential_shaped)
            else:
                for pin in research_config["source_files"]:
                    _pinned(pin)
                _pinned(research_config["reviewed_evidence"])
        if self.config.get("model"):
            self._model()
        return result
