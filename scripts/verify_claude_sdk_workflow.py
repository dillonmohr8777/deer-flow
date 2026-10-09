"""Explicit one-job SDK pilot using isolated state and native bookkeeping.

This is a paid acceptance driver, not a scheduler or production launcher. The
caller supplies existing worker authentication in the environment. It performs
at most three worker requests at $0.03 each; an uncertain call cannot be retried.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "backend",
    "backend/packages/harness",
    "backend/packages/extension-api",
):
    sys.path.insert(0, str(ROOT / relative))


class SyntheticCaptureTransport(httpx.AsyncBaseTransport):
    """Driver-only bounded result capture; never records headers or prompts."""

    def __init__(self, directory: Path):
        self.directory = directory

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        job_id = payload.get("job_id")
        if (
            payload.get("data_class") != "synthetic"
            or payload.get("allowed_tools") != []
            or not isinstance(job_id, str)
            or not re.fullmatch(r"sdk_[0-9a-f]{64}", job_id)
        ):
            raise RuntimeError("diagnostic_capture_requires_synthetic_no_tool_job")
        async with httpx.AsyncHTTPTransport(retries=0, trust_env=False) as transport:
            response = await transport.handle_async_request(request)
            try:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 256 * 1024:
                        raise RuntimeError("diagnostic_response_too_large")
            finally:
                await response.aclose()
        token = os.environ.get("MOMOBOT_CLAUDE_SDK_TOKEN") or os.environ.get(
            "WORKER_AUTH_TOKEN", ""
        )
        if (token and token.encode() in raw) or re.search(
            rb"sk-(?:ant-|or-)|Bearer [A-Za-z0-9]", raw
        ):
            raise RuntimeError("diagnostic_response_secret_refused")
        content = bytes(raw)

        def save():
            target = self.directory / (job_id + ".json")
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            metadata = {
                "worker_job_id": job_id,
                "http_status": response.status_code,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "response": str(target),
                "data_class": "synthetic",
            }
            sidecar = target.with_suffix(".receipt.json")
            descriptor = os.open(
                sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, allow_nan=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())

        await asyncio.to_thread(save)
        return httpx.Response(response.status_code, content=content, request=request)


async def verify(state: Path) -> dict:
    from app.gateway.workflow_adapters import WorkflowModelAdapter
    from app.gateway.workflow_claude_sdk import SOURCE_WORKFLOW
    from app.gateway.workflow_claude_sdk import ClaudeSDKBridge
    from app.gateway.workflow_service import WorkflowService, WorkflowServiceError
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.workflows.catalog import get_workflow
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    events, store = MemoryRunEventStore(), MemoryRunStore()
    manager = RunManager(store=store, event_store=events)
    threads = MemoryThreadMetaStore(InMemoryStore())
    captures = state / "sdk-responses"
    captures.mkdir(mode=0o700)
    adapter = WorkflowModelAdapter(
        claude_sdk=ClaudeSDKBridge(transport=SyntheticCaptureTransport(captures))
    )
    if not adapter.capabilities()["claude_sdk"]["available"]:
        raise RuntimeError("claude_sdk_disabled_or_unconfigured")
    service = WorkflowService(
        state / "workflow.sqlite",
        checkpointer=InMemorySaver(),
        adapter=adapter,
        run_manager=manager,
        thread_store=threads,
        event_store=events,
    )
    await service.start()
    owner = "sdk-synthetic-pilot-owner"
    definition = get_workflow(SOURCE_WORKFLOW)
    actor = "sdk-synthetic-pilot-actor"
    try:
        created = await service.create(
            owner,
            definition.id,
            definition.example_inputs,
            "claude_sdk",
            "sdk-one-job-proof",
            actor=actor,
            organization=None,
            storage_user=actor,
        )
        async with asyncio.timeout(330):
            if service.pump_task is not None:
                await asyncio.shield(service.pump_task)
            tasks = list(service.tasks.values())
            if tasks:
                await asyncio.gather(*tasks)
        final = await service.snapshot(owner, created["id"])
        if final["status"] != "completed" or final.get("accepted") is not True:
            return {
                "accepted": False,
                "status": final["status"],
                "error": final.get("error"),
                "run_id": final["id"],
                "usage": final["usage"],
                "sdk_receipts": final.get("sdk_receipts", []),
                "synthetic_response_captures": str(captures),
                "automatic_retry": False,
            }
        artifact = await service.artifact(owner, created["id"])
        native_owner = (
            "wf_"
            + hashlib.sha256(("momo-workflow-native\0" + owner).encode()).hexdigest()[
                :60
            ]
        )
        native = await store.get(final["native_run_id"], user_id=native_owner)
        assert (
            native is not None
            and native["status"] == "success"
            and native["llm_call_count"] == 3
        )
        assert await store.get(final["native_run_id"], user_id=actor) is None
        assert await threads.get(final["thread_id"], user_id=native_owner) is not None
        replay = await service.create(
            owner,
            definition.id,
            definition.example_inputs,
            "claude_sdk",
            "sdk-one-job-proof",
            actor=actor,
            organization=None,
            storage_user=actor,
        )
        assert replay["id"] == created["id"] and replay["usage"] == final["usage"]
        try:
            await service.artifact("foreign-owner", created["id"])
        except WorkflowServiceError as error:
            assert error.code == "not_found"
        else:
            raise AssertionError("foreign_owner_artifact_visible")
        journal = await events.list_events(
            final["thread_id"], final["native_run_id"], user_id=native_owner
        )
        assert sum(row["event_type"] == "llm.ai.response" for row in journal) == 3
        return {
            "accepted": True,
            "verification": "synthetic_workflow_native_receipt_and_artifact_readback",
            "live_gateway_installed": False,
            "run_id": final["id"],
            "native_run_id": final["native_run_id"],
            "usage": final["usage"],
            "cost_is_estimate": True,
            "source": final["source"],
            "sdk_receipts": final["sdk_receipts"],
            "artifact": str(service.artifact_dir / (final["id"] + ".json")),
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "idempotent_admission_checked": True,
            "foreign_owner_denied": True,
            "native_state_backend": "isolated_memory",
            "workflow_state_backend": "isolated_sqlite",
        }
    finally:
        await service.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly permit this bounded paid pilot",
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--receipts",
        type=Path,
        required=True,
        help="Existing worker receipt journal, read-only",
    )
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; no worker request was sent")
    if (
        not args.state_dir.is_absolute()
        or args.state_dir.exists()
        or not args.receipts.is_absolute()
    ):
        parser.error(
            "use a new absolute state directory and an absolute existing receipt journal"
        )
    os.environ["MOMOBOT_WORKFLOWS_ENABLED"] = "true"
    os.environ["MOMOBOT_CLAUDE_SDK_ENABLED"] = "true"
    os.environ["MOMOBOT_CLAUDE_SDK_RECEIPTS"] = str(args.receipts)
    args.state_dir.mkdir(mode=0o700, parents=True)
    try:
        result = asyncio.run(verify(args.state_dir))
    except Exception:
        result = {
            "accepted": False,
            "error": "pilot_failed_or_uncertain",
            "automatic_retry": False,
        }
    raw = json.dumps(result, indent=2, allow_nan=False)
    target = args.state_dir / "acceptance.json"
    with target.open("x", encoding="utf-8") as handle:
        os.chmod(target, 0o600)
        handle.write(raw + "\n")
    print(raw)
    return 0 if result.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
