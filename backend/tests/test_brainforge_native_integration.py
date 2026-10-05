"""Admit unified Brain Forge packets through the actual native Momo catalog."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from app.channels.brainforge_project import WORKFLOW_LANES, BrainForgeProjectCompiler
from app.channels.brainforge_runtime import BrainForgeRuntime
from app.channels.brainforge_workflow import BRIEF_MODULES, SOURCE_FILES
from app.gateway.routers.workflows import WorkflowRequest
from deerflow.config.app_config import AppConfig
from deerflow.workflows.catalog import get_workflow, list_workflows, validate_inputs


def _pin(path: Path, value: object) -> dict[str, str]:
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_every_project_lane_admits_the_same_bytes_through_native_catalog(tmp_path):
    root = tmp_path.resolve()
    config = {
        "control": _pin(root / "CONTROL.md", "Synthetic Chief-owned fixture"),
        "catalog": _pin(root / "catalog.json", {"workflows": [row.model_dump() for row in list_workflows()]}),
        "inputs": {},
        "native_request_supervisor": True,
        "collector": {"total_budget_usd": 16, "ledger": None},
    }
    for lane, identifier in WORKFLOW_LANES.items():
        definition = get_workflow(identifier)
        config["inputs"][lane] = _pin(root / (lane + ".json"), {"clientId": "synthetic", "inputs": definition.example_inputs})
    snapshot = {"clients": [{"id": "synthetic", "status": "active"}], "workItems": []}
    result = BrainForgeProjectCompiler(config).compile(snapshot, client_id="synthetic")
    assert result["requestCount"] == len(WORKFLOW_LANES)
    for lane, packet in result["lanes"].items():
        request = WorkflowRequest.model_validate(json.loads(packet["requestJson"]))
        assert request.workflow_id == WORKFLOW_LANES[lane]
        assert request.framework == "langgraph"
        assert request.supervisor is True
        assert packet["supervisorRequested"] is True
        assert validate_inputs(get_workflow(request.workflow_id), request.inputs) == request.inputs
        assert request.model_dump() == packet["request"]
        assert hashlib.sha256(packet["requestJson"].encode()).hexdigest() == packet["requestSha256"]
        assert packet["sent"] is False
        assert packet["ownerScope"] is None
    assert result["canonicalWritten"] is False
    assert result["networkCalls"] == 0
    assert result["collector"]["status"] == "original_ledger_unresolved"


def test_native_closed_contract_rejects_project_packet_authority_fields():
    definition = get_workflow(WORKFLOW_LANES["crm"])
    with pytest.raises(ValueError):
        WorkflowRequest.model_validate(
            {
                "workflow_id": definition.id,
                "inputs": definition.example_inputs,
                "framework": "langgraph",
                "supervisor": True,
                "execution_authorized": True,
            }
        )


def test_operator_channel_config_preserves_project_mode_without_activation():
    value = {
        "enabled": False,
        "brain_forge": {
            "enabled": False,
            "workflow": {"project": {"catalog": {"path": "/synthetic/catalog.json", "sha256": "a" * 64}}},
        },
    }
    parsed = AppConfig.model_validate(
        {
            "models": [],
            "tools": [],
            "tool_groups": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "channels": {"slack": value},
        }
    )
    assert parsed.model_extra["channels"]["slack"] == value


@pytest.mark.asyncio
async def test_scoped_socket_brief_saves_native_project_and_recovers_without_duplicate(tmp_path):
    """Exercise native Slack identity hooks with synthetic transport and sources."""
    import asyncio

    from app.channels.brainforge_cli import verify
    from app.channels.message_bus import MessageBus
    from app.channels.slack import SlackChannel

    brief_source = Path(os.environ.get("BRAINFORGE_BRIEF_SOURCE", "/missing"))
    if not all((brief_source / name).is_file() for name in BRIEF_MODULES):
        pytest.skip("reviewed private brief source not restored")
    root = tmp_path.resolve()
    canonical = root / "synthetic-canonical"
    source = root / "reviewed-source"
    source.mkdir()
    for name in BRIEF_MODULES:
        shutil.copyfile(brief_source / name, source / name)
    (canonical / "registry").mkdir(parents=True)
    (canonical / "queue").mkdir()
    _pin(canonical / "registry/clients.json", {"clients": [{"id": "synthetic", "status": "active"}]})
    _pin(canonical / "queue/work-items.json", {"revision": 7, "updatedAt": "2026-10-02T00:00:00+00:00", "workItems": [{"id": "blocked", "clientId": "synthetic", "status": "blocked", "title": "Private fixture prose"}]})
    project = {
        "control": _pin(canonical / "CONTROL.md", "Synthetic Chief-owned fixture"),
        "catalog": _pin(root / "catalog.json", {"workflows": [row.model_dump() for row in list_workflows()]}),
        "native_request_supervisor": False,
        "inputs": {},
        "collector": {"total_budget_usd": 16, "ledger": None},
    }
    for lane, identifier in WORKFLOW_LANES.items():
        project["inputs"][lane] = _pin(root / (lane + ".json"), {"clientId": "synthetic", "inputs": get_workflow(identifier).example_inputs})
    workflow = {
        "brief_source": str(source),
        "canonical_root": str(canonical),
        "artifact_root": str(root / "private-output"),
        "project": project,
        "brief_source_hashes": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in BRIEF_MODULES},
        "source_hashes": {name: hashlib.sha256((canonical / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
    }
    event = {"type": "app_mention", "user": "U123", "channel": "C123", "ts": "100.000002", "text": "<@U999> brief"}
    sends = []
    acknowledgments = []

    class SyntheticTransport:
        retry_handlers = []

        def auth_test(self):
            return {"ok": True, "team_id": "T123", "user_id": "U999"}

        def conversations_replies(self, **kwargs):
            assert kwargs["channel"] == "C123"
            return {"ok": True, "messages": [event]}

        def chat_postMessage(self, **kwargs):
            sends.append(kwargs)
            return {"ok": True, "ts": "101.000001"}

    transport = SyntheticTransport()
    repo = SimpleNamespace(
        find_connection_by_external_identity=AsyncMock(return_value={"id": "synthetic-binding", "workspace_id": "T123", "owner_user_id": "synthetic-owner", "delegation_id": "synthetic-delegation"}),
        get_credentials=AsyncMock(return_value={"access_token": "SYNTHETIC_TRANSIENT_BINDING_TOKEN"}),
    )
    channel = SlackChannel(MessageBus(), {"connection_repo": repo, "web_client_factory": lambda **kwargs: transport})
    config = {
        "team_id": "T123",
        "bot_user_id": "U999",
        "allowed_users": ["U123"],
        "channel_clients": {"C123": "synthetic"},
        "owner_user_id": "U123",
        "connection_owner_id": "synthetic-owner",
        "require_connection": True,
        "ledger_path": str(root / "receipts.sqlite"),
        "workflow": workflow,
    }
    runtime = BrainForgeRuntime(channel, config)
    channel._web_client = transport
    channel._brainforge = runtime
    channel._loop = asyncio.get_running_loop()
    channel._running = True
    channel._SocketModeResponse = lambda **kwargs: kwargs
    scheduled = []
    channel._submit_threadsafe_coroutine = lambda coroutine, *args, **kwargs: scheduled.append(coroutine) or True
    envelope = SimpleNamespace(type="events_api", envelope_id="synthetic-envelope", payload={"team_id": "T123", "event": event})

    def ack(response):
        assert runtime.ledger.get("T123", "C123", event["ts"])["state"] == "queued"
        acknowledgments.append(response)

    try:
        await runtime.validate_transport()
        channel._on_socket_event(SimpleNamespace(send_socket_mode_response=ack), envelope)
        assert len(acknowledgments) == len(scheduled) == 1
        await scheduled.pop()
        assert runtime.ledger.get("T123", "C123", event["ts"])["state"] == "delivered"
        assert len(sends) == 1
        assert "Native workflow requests prepared: 8; sent: 0." in sends[0]["text"]
        assert "Private fixture prose" not in sends[0]["text"]
        assert repo.find_connection_by_external_identity.await_args_list == [call(provider="slack", external_account_id="U123", workspace_id="T123")] * 2
        assert repo.get_credentials.await_args_list == [call("synthetic-binding", owner_user_id="synthetic-owner")] * 2
        receipts = list((root / "private-output").rglob("workflow-*.json"))
        assert len(receipts) == 1
        receipt = json.loads(receipts[0].read_text())
        assert verify(str(receipts[0]), hashlib.sha256(receipts[0].read_bytes()).hexdigest(), workflow)["projectVerified"]
        prepared = json.loads(Path(receipt["project"]["path"]).read_text())
        for packet in prepared["lanes"].values():
            WorkflowRequest.model_validate(packet["request"])
        assert workflow["source_hashes"] == {name: hashlib.sha256((canonical / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    finally:
        channel._running = False
        for coroutine in scheduled:
            coroutine.close()
        await runtime.close()
    reopened = BrainForgeRuntime(channel, config)
    try:
        assert await reopened.recover() == 0
        assert reopened.prepare(event, team_id="T123") is None
        assert len(sends) == 1
    finally:
        await reopened.close()
