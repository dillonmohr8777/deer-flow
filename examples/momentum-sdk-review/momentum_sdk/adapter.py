"""Minimal source snapshot of the reviewed local SDK adapter's typed draft path.
Only HandoffPacket, Limits and draft are reused; no live model constructors.
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from agents import Agent, RunConfig, Runner, ModelSettings


class HandoffPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1)
    status: Literal["draft", "blocked", "needs_approval"]
    found: str
    proposed_change: str
    evidence: list[str] = Field(min_length=1)
    next_move: str
    # This packet never grants permission or changes the canonical commitment queue.


@dataclass(frozen=True)
class Limits:
    max_turns: int = 3
    timeout_seconds: float = 30.0

    def __post_init__(self):
        if not 1 <= self.max_turns <= 6 or not 0 < self.timeout_seconds <= 60:
            raise ValueError("Bounded caller limits required")


async def draft(
    agent: Agent,
    request: str,
    *,
    limits: Limits = Limits(),
    live_budget_approved: bool = False,
):
    """Does make inference calls when given a live model: caller must grant a budget first."""
    from agents.testing import ScriptedModel

    if not isinstance(agent.model, ScriptedModel) and not live_budget_approved:
        raise PermissionError(
            "A finite provider budget must be approved before live inference"
        )
    if len(request) > 8000:
        raise ValueError("Bounded request exceeds 8000 characters")
    async with asyncio.timeout(limits.timeout_seconds):
        return await Runner.run(
            agent,
            request,
            max_turns=limits.max_turns,
            run_config=RunConfig(
                tracing_disabled=True,
                trace_include_sensitive_data=False,
                model_settings=ModelSettings(max_tokens=1000),
            ),
        )
