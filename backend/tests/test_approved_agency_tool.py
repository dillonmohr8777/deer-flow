"""Offline native SQLite phases and descriptor security; no provider calls."""

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from deerflow.config.app_config import AppConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.subagents.approved_packets import COORDINATOR, MODEL_ALIAS, PRODUCER, REVIEWER, PacketStop, directory, read_at
from deerflow.subagents.batch_service import SubagentBatchService

module = importlib.import_module("deerflow.tools.builtins.approved_agency_tool")
batch_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")


@pytest_asyncio.fixture
async def case(tmp_path, monkeypatch):
    operator = tmp_path / "operator"
    operator.mkdir()
    jobs = []
    for index in (1, 2):
        raw = json.dumps({"operator_source": f"exact source {index}"}).encode()
        name = f"source{index}.json"
        (operator / name).write_bytes(raw)
        jobs.append(
            {
                "id": f"job{index}",
                "source_file": name,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "output_name": "draft.md",
                "task": "Write a reviewable local draft.",
                "acceptance_criteria": ["The exact source is addressed; unexecuted checks remain unexecuted."],
            }
        )
    manifest = operator / "approved.json"
    manifest.write_text(json.dumps({"schema_version": 1, "cycle_id": "cycle1", "owner_user_id": "owner1", "thread_id": "thread1", "work_orders": jobs}))
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST", str(manifest))
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest())
    state = tmp_path / "state"
    outputs = state / "users" / "owner1" / "threads" / "thread1" / "user-data" / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setattr(module, "get_paths", lambda: SimpleNamespace(base_dir=state))
    app = AppConfig(
        models=[ModelConfig(name=MODEL_ALIAS, use="langchain_openai:ChatOpenAI", model="openai/gpt-6-luna", base_url="http://127.0.0.1:2042/v1", max_retries=0, max_tokens=2000, supports_vision=False)],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        subagents={
            "custom_agents": {
                role: {"description": role, "system_prompt": "Private source-only draft or independent review.", "model": MODEL_ALIAS, "tools": [], "skills": [], "max_turns": 2, "timeout_seconds": 600} for role in (PRODUCER, REVIEWER)
            }
        },
    )
    runtime = SimpleNamespace(
        context={"user_id": "owner1", "thread_id": "thread1", "run_id": "run1", "agent_name": COORDINATOR, "app_config": app, "user_role": "member", "authz_attributes": {"tenant": "private"}},
        config={"metadata": {"model_name": MODEL_ALIAS, "allowed_subagents": [PRODUCER, REVIEWER], "mcp_plugins": [], "available_skills": [], "tool_groups": ["agency-pilot"]}},
    )
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db")))
    sf = get_session_factory()
    assert sf is not None
    async with sf() as session:
        session.add(ThreadMetaRow(thread_id="thread1", user_id="owner1"))
        session.add(RunRow(run_id="run1", thread_id="thread1", user_id="owner1", status="success"))
        await session.commit()
    repository = SubagentBatchRepository(sf)
    service = SubagentBatchService(repository=repository, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=app)
    monkeypatch.setattr(batch_module, "get_subagent_batch_submitter", lambda: service)
    yield SimpleNamespace(operator=operator, manifest=manifest, state=state, outputs=outputs, runtime=runtime, app=app, sf=sf, repository=repository, service=service)
    await close_engine()


async def call(case, phase, call_id="call1"):
    result = await module.approved_agency_phase.coroutine(runtime=case.runtime, cycle_id="cycle1", phase=phase, tool_call_id=call_id)
    return json.loads(result.update["messages"][0].content)


async def complete(case, text="Exact saved producer draft", truncated=False):
    now = datetime.now(UTC)
    rows = await case.repository.claim_items(now=now, lease_owner="offline-worker", lease_seconds=60, limit=2)
    assert len(rows) == 2
    for row in rows:
        assert await case.repository.mark_item_running(row["id"], lease_owner="offline-worker", now=now)
        assert await case.repository.finalize_item(
            row["id"], lease_owner="offline-worker", succeeded=True, result=text, result_preview=text, result_truncated=truncated, error=None, stop_reason=None, token_usage=None, model_name=MODEL_ALIAS, completed_at=now
        )


@pytest.mark.asyncio
async def test_full_native_cycle_reuses_phase_on_new_run_and_persists_exact_bytes(case):
    first = await call(case, "produce")
    assert first["state"] == "native_phase_submitted_or_resumed"
    batch = await case.service.get_batch(batch_id=first["batch_id"], user_id="owner1")
    assert batch["max_running_items"] == 2 and batch["max_live_items"] == 2 and batch["max_attempts"] == 1
    async with case.sf() as session:
        session.add(RunRow(run_id="run2", thread_id="thread1", user_id="owner1", status="success"))
        await session.commit()
    case.runtime.context["run_id"] = "run2"
    resumed = await call(case, "produce", "different-call")
    assert resumed["batch_id"] == first["batch_id"] and resumed["parent_run_id"] == "run1"
    assert (await call(case, "review"))["reason"] == "native_phase_not_completed"
    await complete(case)
    review = await call(case, "review")
    rows = await case.service.list_items(batch_id=review["batch_id"], user_id="owner1")
    assert len(rows) == 2
    for row, artifact in zip(rows, review["artifacts"], strict=True):
        assert "Exact saved producer draft" in row["prompt"]
        assert artifact["artifact_sha256"] == hashlib.sha256(b"Exact saved producer draft").hexdigest()
        assert artifact["source_sha256"] in row["prompt"] and artifact["artifact_sha256"] in row["prompt"]
        assert artifact["item_id"] and artifact["batch_id"] == first["batch_id"] and row["acceptance_criteria"]
    assert (await call(case, "review"))["batch_id"] == review["batch_id"]
    await complete(case, text='{"verdict":"needs_evidence"}')
    closed = await call(case, "closeout")
    assert closed["state"] == "evidence_ready_for_independent_acceptance" and closed["acceptance_state"] == "not_evaluated" and closed["actual_cost_usd"] is None
    assert len(closed["reviews"]) == 2
    for receipt in closed["reviews"]:
        assert (case.outputs / "cycle1" / receipt["work_order_id"] / "independent-review.json").read_bytes() == b'{"verdict":"needs_evidence"}'
    assert (await call(case, "closeout"))["reviews"] == closed["reviews"]
    assert len(await case.repository.list_by_thread("thread1", user_id="owner1")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,reason",
    [
        ("owner", "operator_principal_or_thread_mismatch"),
        ("thread", "operator_principal_or_thread_mismatch"),
        ("role", "operator_principal_or_thread_mismatch"),
        ("model", "parent_route_or_policy_mismatch"),
        ("allowlist", "parent_route_or_policy_mismatch"),
        ("mcp", "parent_route_or_policy_mismatch"),
        ("missing_run", "native_parent_owner_unverified"),
        ("wrong_parent_owner", "native_parent_owner_unverified"),
        ("child_tools", "private_role_policy_mismatch"),
        ("child_model", "private_role_policy_mismatch"),
        ("sdk_retries", "guarded_model_profile_mismatch"),
    ],
)
async def test_admission_denies_changed_principal_policy_or_private_route(case, change, reason):
    if change == "owner":
        case.runtime.context["user_id"] = "other"
    elif change == "thread":
        case.runtime.context["thread_id"] = "other"
    elif change == "role":
        case.runtime.context["agent_name"] = "other"
    elif change == "model":
        case.runtime.config["metadata"]["model_name"] = "unguarded"
    elif change == "allowlist":
        case.runtime.config["metadata"]["allowed_subagents"] = None
    elif change == "mcp":
        case.runtime.config["metadata"]["mcp_plugins"] = ["vendor"]
    elif change == "missing_run":
        case.runtime.context["run_id"] = "absent"
    elif change == "wrong_parent_owner":
        async with case.sf() as session:
            await session.execute(update(RunRow).values(user_id="other"))
            await session.commit()
    elif change == "child_tools":
        case.app.subagents.custom_agents[PRODUCER].tools = ["read_file"]
    elif change == "child_model":
        case.app.subagents.custom_agents[REVIEWER].model = "public-muse"
    elif change == "sdk_retries":
        case.app.models[0].max_retries = 2
    assert (await call(case, "produce"))["reason"] == reason
    assert await case.repository.list_by_thread("thread1", user_id="owner1") == []


@pytest.mark.asyncio
async def test_disabled_changed_manifest_and_source_fail_closed(case, monkeypatch):
    monkeypatch.delenv("DEER_FLOW_AGENCY_PACKET_MANIFEST")
    assert (await call(case, "produce"))["reason"] == "operator_packet_manifest_disabled"
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST", str(case.manifest))
    case.manifest.write_bytes(case.manifest.read_bytes() + b" ")
    assert (await call(case, "produce"))["reason"] == "operator_manifest_digest_mismatch"
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256", hashlib.sha256(case.manifest.read_bytes()).hexdigest())
    (case.operator / "source1.json").write_bytes(b"changed")
    assert (await call(case, "produce"))["reason"] == "source_packet_digest_mismatch"


@pytest.mark.asyncio
async def test_revised_task_on_resume_does_not_create_second_batch(case, monkeypatch):
    first = await call(case, "produce")
    data = json.loads(case.manifest.read_text())
    data["work_orders"][0]["task"] = "Changed approved task"
    case.manifest.write_text(json.dumps(data))
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256", hashlib.sha256(case.manifest.read_bytes()).hexdigest())
    assert (await call(case, "produce"))["reason"] == "native_phase_source_changed"
    batches = await case.repository.list_by_thread("thread1", user_id="owner1")
    assert len(batches) == 1 and batches[0]["id"] == first["batch_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["truncated", "prompt", "failed", "missing", "model", "blank", "oversized"])
async def test_review_requires_exact_complete_native_result(case, mutation):
    await call(case, "produce")
    await complete(case, truncated=mutation == "truncated")
    if mutation != "truncated":
        changes = {"prompt": {"prompt": "other"}, "failed": {"status": "failed"}, "model": {"model_name": "public"}, "blank": {"result": " "}, "oversized": {"result": "x" * 16001}}
        async with case.sf() as session:
            row = (await session.execute(select(SubagentBatchItemRow))).scalars().first()
            if mutation == "missing":
                await session.delete(row)
            else:
                for key, val in changes[mutation].items():
                    setattr(row, key, val)
            await session.commit()
    assert (await call(case, "review"))["state"] == "stopped"
    assert len(await case.repository.list_by_thread("thread1", user_id="owner1")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["different", "file_link", "directory_link", "fifo"])
async def test_review_never_overwrites_or_follows_existing_artifact(case, replacement):
    await call(case, "produce")
    await complete(case)
    parent = case.outputs / "cycle1" / "job1"
    parent.mkdir(parents=True)
    artifact = parent / "draft.md"
    external = case.state / "external"
    external.write_bytes(b"outside original")
    if replacement == "different":
        artifact.write_bytes(b"owner original")
    elif replacement == "file_link":
        artifact.symlink_to(external)
    elif replacement == "fifo":
        os.mkfifo(artifact)
    else:
        parent.rename(case.state / "detached")
        parent.symlink_to(case.state / "detached")
    assert (await call(case, "review"))["state"] == "stopped"
    assert external.read_bytes() == b"outside original"
    if replacement == "different":
        assert artifact.read_bytes() == b"owner original"
    assert len(await case.repository.list_by_thread("thread1", user_id="owner1")) == 1


def test_no_follow_read_rejects_leaf_replacement_and_in_place_change(tmp_path):
    for action in ("replace", "modify"):
        file = tmp_path / "artifact.md"
        file.write_bytes(b"original bytes")
        actual_read = os.read
        changed = False

        def racing_read(fd, size):
            nonlocal changed
            chunk = actual_read(fd, size)
            if chunk and not changed:
                changed = True
                if action == "replace":
                    other = tmp_path / "replacement.md"
                    other.write_bytes(b"other bytes")
                    other.replace(file)
                else:
                    file.write_bytes(b"other bytes")
            return chunk

        with directory(tmp_path) as parent, patch("deerflow.subagents.approved_packets.os.read", racing_read):
            with pytest.raises(PacketStop, match="file_changed_during_readback"):
                read_at(parent, file.name, ceiling=16000)


@pytest.mark.asyncio
async def test_concurrent_phase_calls_use_one_native_submission(case):
    import asyncio

    results = await asyncio.gather(call(case, "produce", "call-a"), call(case, "produce", "call-b"))
    assert results[0]["batch_id"] == results[1]["batch_id"]
    assert len(await case.repository.list_by_thread("thread1", user_id="owner1")) == 1


@pytest.mark.asyncio
async def test_phase_ids_cannot_expand_and_prior_phase_is_required(case):
    result = await module.approved_agency_phase.coroutine(runtime=case.runtime, cycle_id="cycle1", phase="arbitrary", tool_call_id="call1")
    assert json.loads(result.update["messages"][0].content)["reason"] == "phase_not_operator_approved"
    assert (await call(case, "review"))["reason"] == "producer_phase_missing"
    assert (await call(case, "closeout"))["reason"] == "producer_phase_missing"


@pytest.mark.asyncio
async def test_largest_source_review_is_refused_locally_before_second_batch(case, monkeypatch):
    # Individually permitted source/checklist/output ceilings can exceed the
    # stricter assembled review prompt admission ceiling. Refuse before queue.
    raw = b"x" * 64000
    (case.operator / "source1.json").write_bytes(raw)
    data = json.loads(case.manifest.read_text())
    data["work_orders"][0]["source_sha256"] = hashlib.sha256(raw).hexdigest()
    data["work_orders"][0]["task"] = "t" * 2000
    data["work_orders"][0]["acceptance_criteria"] = ["c" * 500 for _ in range(20)]
    case.manifest.write_text(json.dumps(data))
    monkeypatch.setenv("DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256", hashlib.sha256(case.manifest.read_bytes()).hexdigest())
    assert (await call(case, "produce"))["state"] == "native_phase_submitted_or_resumed"
    await complete(case, text="a" * 16000)
    assert (await call(case, "review"))["reason"] == "native_packet_prompt_admission_ceiling"
    assert len(await case.repository.list_by_thread("thread1", user_id="owner1")) == 1
