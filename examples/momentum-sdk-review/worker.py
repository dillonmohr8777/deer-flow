"""Fixed isolated worker: ScriptedModel only, no provider credentials or network."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Never


# Fail closed before importing any SDK; no provider transport is authorized.
def denied(*args: Any, **kwargs: Any) -> Never:
    raise RuntimeError("Network is disabled in the offline SDK worker")


# These are intentional process-local runtime guards, not static API replacements.
for target, name in (
    (socket, "create_connection"),
    (socket, "getaddrinfo"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
):
    setattr(target, name, denied)
if any(key.endswith("API_KEY") or key.endswith("TOKEN") for key in os.environ):
    raise SystemExit(2)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents import Agent  # noqa: E402
from agents.testing import ScriptedModel, assistant_message  # noqa: E402
from momentum_sdk.adapter import HandoffPacket, Limits, draft  # noqa: E402


async def main():
    raw = sys.stdin.buffer.read(32769)
    if len(raw) > 32768:
        raise ValueError("Input limit")
    payload = json.loads(raw)
    client_id = payload["client_id"]
    status = payload["canonical_status"]
    if status["client_id"] != client_id:
        raise ValueError("Identity mismatch")
    packet = HandoffPacket(
        client_id=client_id,
        status="draft",
        found="Synthetic offline SDK plumbing verified; engagement remains unknown.",
        proposed_change="Synthetic draft only; no operational recommendation generated.",
        evidence=["host-verified canonical registry and aggregate queue status"],
        next_move="Review this synthetic packet; live reasoning is not enabled.",
    )
    agent = Agent(
        name="Synthetic offline review",
        model=ScriptedModel([[assistant_message(packet.model_dump_json())]]),
        output_type=HandoffPacket,
    )
    result = await draft(agent, payload["request"], limits=Limits())
    sys.stdout.write(result.final_output.model_dump_json())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        sys.stderr.write("Offline SDK worker failed")
        raise SystemExit(2)
