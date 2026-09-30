"""Compact operator-approved phases backed by the existing native batch queue."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.subagents.approved_packets import (
    COORDINATOR,
    MODEL_ALIAS,
    PRODUCER,
    REVIEWER,
    ApprovedCycle,
    PacketStop,
    WorkOrder,
    artifact_parts,
    directory,
    load_cycle,
    persist_readback,
    phase_key,
    producer_prompt,
    read_at,
    reviewer_prompt,
    source_bytes,
)
from deerflow.subagents.registry import get_subagent_config
from deerflow.subagents.report_contract import normalize_acceptance_criteria
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem, _batch_app_config, _batch_submitter, submit_native_batch
from deerflow.tools.types import Runtime


def _reply(call_id: str, value: dict, *, error: bool = False) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="approved_agency_phase",
                    tool_call_id=call_id,
                    content=json.dumps(value, sort_keys=True),
                    status="error" if error else "success",
                )
            ]
        }
    )


def _authorize(cycle: ApprovedCycle, runtime: Runtime) -> None:
    context = runtime.context if isinstance(runtime.context, dict) else {}
    metadata = runtime.config.get("metadata", {})
    if resolve_runtime_user_id(runtime) != cycle.owner_user_id or context.get("thread_id") != cycle.thread_id or context.get("agent_name") != COORDINATOR:
        raise PacketStop("operator_principal_or_thread_mismatch")
    if metadata.get("model_name") != MODEL_ALIAS or set(metadata.get("allowed_subagents") or []) != {PRODUCER, REVIEWER} or metadata.get("mcp_plugins") != []:
        raise PacketStop("parent_route_or_policy_mismatch")
    app_config = _batch_app_config(runtime)
    if app_config is None:
        raise PacketStop("caller_config_snapshot_missing")
    model = app_config.get_model_config(MODEL_ALIAS)
    if model is None or model.model != "openai/gpt-6-luna" or getattr(model, "base_url", None) != "http://127.0.0.1:2042/v1" or getattr(model, "max_retries", None) != 0 or getattr(model, "max_tokens", None) != 2000:
        raise PacketStop("guarded_model_profile_mismatch")
    for role in (PRODUCER, REVIEWER):
        config = get_subagent_config(role, app_config=app_config)
        if config is None or config.model != MODEL_ALIAS or config.tools != [] or config.skills != [] or not 1 <= config.max_turns <= 2 or not 1 <= config.timeout_seconds <= 600:
            raise PacketStop("private_role_policy_mismatch")


async def _existing(submitter, cycle: ApprovedCycle, phase: str) -> dict | None:
    batch = await submitter.get_batch_by_submission_key(submission_key=phase_key(cycle, phase), user_id=cycle.owner_user_id)
    if batch is not None and (
        batch.get("thread_id") != cycle.thread_id
        or batch.get("subagent_type") != (PRODUCER if phase == "produce" else REVIEWER)
        or batch.get("total_items") != 2
        or batch.get("max_running_items") != 2
        or batch.get("max_live_items") != 2
        or batch.get("max_attempts") != 1
        or not isinstance(batch.get("parent_run_id"), str)
        or not batch["parent_run_id"]
    ):
        raise PacketStop("native_phase_identity_mismatch")
    return batch


async def _completed_items(submitter, cycle: ApprovedCycle, batch: dict, expected: dict[str, str]) -> dict[str, dict]:
    if batch.get("status") != "completed":
        raise PacketStop("native_phase_not_completed")
    rows = await submitter.list_items(batch_id=batch["id"], user_id=cycle.owner_user_id)
    if not isinstance(rows, list) or len(rows) != 2 or {row.get("item_key") for row in rows} != set(expected):
        raise PacketStop("native_item_bindings_missing")
    results = {}
    criteria = {job.id: normalize_acceptance_criteria(job.acceptance_criteria) for job in cycle.work_orders}
    for row in rows:
        if (
            row.get("batch_id") != batch["id"]
            or row.get("prompt") != expected[row["item_key"]]
            or row.get("status") != "succeeded"
            or row.get("result_truncated") is not False
            or row.get("stop_reason") is not None
            or row.get("model_name") != MODEL_ALIAS
            or row.get("acceptance_criteria") != criteria[row["item_key"]]
            or not isinstance(row.get("result"), str)
            or not row["result"].strip()
            or not isinstance(row.get("id"), str)
            or not row["id"]
        ):
            raise PacketStop("native_result_unverified_or_incomplete")
        results[row["item_key"]] = row
    return results


def _artifact(cycle: ApprovedCycle, job: WorkOrder, row: dict, batch: dict, *, review: bool = False) -> dict:
    name = "independent-review.json" if review else job.output_name
    receipt = persist_readback(get_paths().base_dir, cycle, job, name, row["result"].encode("utf-8"))
    receipt.update({"batch_id": batch["id"], "item_id": row["id"], "parent_run_id": batch.get("parent_run_id"), "native_acceptance_verdict": row.get("acceptance_verdict")})
    return receipt


def _saved_bytes(cycle: ApprovedCycle, job: WorkOrder, receipt: dict) -> bytes:
    import hashlib

    with directory(get_paths().base_dir, artifact_parts(cycle, job)) as fd:
        actual = read_at(fd, job.output_name, ceiling=16000)
    if hashlib.sha256(actual).hexdigest() != receipt["artifact_sha256"]:
        raise PacketStop("artifact_changed_before_review")
    return actual


@tool("approved_agency_phase", parse_docstring=True)
async def approved_agency_phase(
    runtime: Runtime,
    cycle_id: str,
    phase: Literal["produce", "review", "closeout"],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Advance one fixed operator-approved native agency cycle.

    Use produce once, then poll its returned batch with batch_status. Review
    requires both stored successful producer results and persists their exact
    bytes before queuing two independent private reviewers. Closeout requires
    both reviewer results, persists their bytes and returns evidence paths.
    Repeating a phase resumes the same owner/thread/cycle identity. Counts and
    receipts never imply acceptance. No arbitrary prompts, paths, model or role.

    Args:
        cycle_id: Exact operator-approved cycle identifier.
        phase: produce, review, or closeout; never skip unfinished prior phases.
    """
    try:
        if phase not in {"produce", "review", "closeout"}:
            raise PacketStop("phase_not_operator_approved")
        cycle, root = load_cycle()
        if cycle_id != cycle.cycle_id:
            raise PacketStop("cycle_not_operator_approved")
        _authorize(cycle, runtime)
        submitter = _batch_submitter()
        if submitter is None:
            raise PacketStop("native_batch_runtime_unavailable")
        run_id = runtime.context.get("run_id")
        if not isinstance(run_id, str) or not run_id or await submitter.owns_parent(thread_id=cycle.thread_id, run_id=run_id, user_id=cycle.owner_user_id) is not True:
            raise PacketStop("native_parent_owner_unverified")
        sources = {job.id: source_bytes(root, job) for job in cycle.work_orders}
        producer_prompts = {job.id: producer_prompt(cycle, job, sources[job.id]) for job in cycle.work_orders}
        producer = await _existing(submitter, cycle, "produce")
        artifacts = []
        if phase != "produce":
            if producer is None:
                raise PacketStop("producer_phase_missing")
            rows = await _completed_items(submitter, cycle, producer, producer_prompts)
            artifacts = [_artifact(cycle, job, rows[job.id], producer) for job in cycle.work_orders]
            review_prompts = {job.id: reviewer_prompt(cycle, job, sources[job.id], _saved_bytes(cycle, job, receipt), receipt) for job, receipt in zip(cycle.work_orders, artifacts, strict=True)}
        selected = producer if phase == "produce" else await _existing(submitter, cycle, "review")
        if phase == "closeout":
            if selected is None or producer is None:
                raise PacketStop("review_phase_missing")
            rows = await _completed_items(submitter, cycle, selected, review_prompts)
            reviews = [_artifact(cycle, job, rows[job.id], selected, review=True) for job in cycle.work_orders]
            return _reply(
                tool_call_id,
                {
                    "state": "evidence_ready_for_independent_acceptance",
                    "cycle_id": cycle.cycle_id,
                    "producer_batch_id": producer["id"],
                    "review_batch_id": selected["id"],
                    "artifacts": artifacts,
                    "reviews": reviews,
                    "acceptance_state": "not_evaluated",
                    "actual_cost_usd": None,
                },
            )
        if selected is None:
            prompts = producer_prompts if phase == "produce" else review_prompts
            # Preliminary local ceiling reserves room for the native system
            # and middleware framing. The request guard still checks the
            # actual assembled request before any provider dispatch.
            if any(len(prompt.encode("utf-8")) > 88000 for prompt in prompts.values()):
                raise PacketStop("native_packet_prompt_admission_ceiling")
            result = await submit_native_batch(
                runtime=runtime,
                title=f"{cycle.cycle_id} {phase}",
                items=[BatchTaskItem(key=job.id, prompt=prompts[job.id], acceptance_criteria=job.acceptance_criteria) for job in cycle.work_orders],
                subagent_type=PRODUCER if phase == "produce" else REVIEWER,
                tool_call_id=tool_call_id,
                max_live_items=2,
                max_running_items=2,
                submission_key=phase_key(cycle, phase),
                max_attempts=1,
            )
            updates = result.update
            if not isinstance(updates, dict):
                raise PacketStop("native_submission_response_invalid")
            messages = updates.get("messages")
            if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], ToolMessage):
                raise PacketStop("native_submission_response_invalid")
            if messages[0].status == "error":
                raise PacketStop("native_submission_refused")
            selected = await _existing(submitter, cycle, phase)
            if selected is None:
                raise PacketStop("native_submission_readback_missing")
        # Verify the existing persisted input binding on every resume, even
        # while pending, so a revised manifest cannot reuse unrelated work.
        rows = await submitter.list_items(batch_id=selected["id"], user_id=cycle.owner_user_id)
        expected = producer_prompts if phase == "produce" else review_prompts
        if not isinstance(rows, list) or len(rows) != 2 or {row.get("item_key") for row in rows} != set(expected) or any(row.get("prompt") != expected[row["item_key"]] for row in rows):
            raise PacketStop("native_phase_source_changed")
        return _reply(
            tool_call_id,
            {
                "state": "native_phase_submitted_or_resumed",
                "cycle_id": cycle.cycle_id,
                "phase": phase,
                "batch_id": selected["id"],
                "parent_run_id": selected.get("parent_run_id"),
                "status": selected["status"],
                "artifacts": artifacts,
                "acceptance_state": "not_evaluated",
            },
        )
    except PacketStop as exc:
        return _reply(tool_call_id, {"state": "stopped", "reason": str(exc), "acceptance_state": "not_evaluated"}, error=True)
    except Exception:
        return _reply(tool_call_id, {"state": "stopped", "reason": "approved_phase_unavailable", "private_error_withheld": True, "acceptance_state": "not_evaluated"}, error=True)
