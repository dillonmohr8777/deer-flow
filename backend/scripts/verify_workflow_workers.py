"""Offline smoke of packaged framework workers, with synthetic model responses.

Run in a disposable workflow-runtime container with --network none. This script
supplies no key, starts no Gateway and creates no workflow or provider session.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

from app.gateway.workflow_adapters import WORKERS, WorkflowModelAdapter


class SyntheticProvider:
    def __init__(self):
        self.responses = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(id="offline-worker-smoke", model=kwargs["model"], status="completed", output=[], output_text='{"answer":"Synthetic packaged worker receipt"}', usage=SimpleNamespace(input_tokens=12, output_tokens=8))


async def main():
    versions = {}
    for name, python in (("crewai", WORKERS / "python/.venv/bin/python"), ("agno", WORKERS.parent / "agno-team/.venv/bin/python")):
        result = subprocess.run([str(python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"], check=True, capture_output=True, text=True)
        versions[name] = result.stdout.strip()
        if versions[name] != "3.13":
            raise RuntimeError("worker_python_version_mismatch")
    versions["node"] = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if not versions["node"].startswith("v24."):
        raise RuntimeError("worker_node_version_mismatch")
    provider = SyntheticProvider()
    adapter = WorkflowModelAdapter(client=provider)
    frameworks = ("langgraph", "crewai", "deepagents", "mastra", "agno", "agentkit")
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
    try:
        capabilities = adapter.capabilities()
        if not all(capabilities[name]["available"] for name in (*frameworks, "stagehand")):
            raise RuntimeError("packaged_worker_unavailable")
        for framework in frameworks:
            try:
                result = await adapter.call(
                    framework=framework,
                    worker_id="offline-smoke",
                    call_id="offline-" + framework,
                    role="writer",
                    prompt="Return the requested synthetic JSON object; no actions or delegation.",
                    continuation=[],
                    output_schema=schema,
                    model="gpt-6.1-sol",
                    effort="low",
                    max_output_tokens=256,
                    input_token_limit=60000,
                )
            except Exception:
                raise RuntimeError("packaged_worker_failed_" + framework) from None
            if result["output"] != {"answer": "Synthetic packaged worker receipt"} or result["usage"]["input_tokens"] != 12:
                raise RuntimeError("packaged_worker_receipt_mismatch")
        if provider.calls != len(frameworks) or adapter.active_workers:
            raise RuntimeError("packaged_worker_lifecycle_mismatch")
        print(
            json.dumps(
                {"kind": "offline_packaged_worker_smoke", "frameworks": list(frameworks), "stagehand_installed": True, "synthetic_model_handoffs": provider.calls, "paid_provider_calls": 0, "live_browser_sessions": 0, "versions": versions},
                sort_keys=True,
            )
        )
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    asyncio.run(main())
