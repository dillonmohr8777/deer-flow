"""Momo task harness: spec -> worker -> verifier -> receipt.

The thinnest thing that can hold a client workflow accountable. A workflow is a
`TaskSpec` plus a worker callable plus checks; `run_task` runs it with bounded
retries, stops on evidence, and appends one receipt saying which layer it
reached. See `AGENTS.md` beside this file, and `weekly_reports.py` for a real
workflow ported onto it.
"""

from .budget import AdmissionGateAdapter, BudgetDenied, BudgetGate, FakeGate, FreeGate
from .contract import (
    CHECK_LAYERS,
    DATA_CLASSES,
    LAYERS,
    Check,
    CheckResult,
    HarnessError,
    Receipt,
    ReceiptLog,
    RunOutput,
    TaskSpec,
    layer_reached,
)
from .runner import Worker, run_task
from .swarm import CONTRIBUTOR_TIERS, DataClassRefused, ScaleGuard, ScaleRefused, SwarmPick, SwarmResult, fan_out
from .verify import CommandCheck, FileExistsCheck, HttpStatusCheck, JudgeCheck, PredicateCheck, SchemaCheck, judge_prompt

__all__ = [
    "CHECK_LAYERS",
    "CONTRIBUTOR_TIERS",
    "DATA_CLASSES",
    "LAYERS",
    "AdmissionGateAdapter",
    "BudgetDenied",
    "BudgetGate",
    "Check",
    "CheckResult",
    "CommandCheck",
    "DataClassRefused",
    "FakeGate",
    "FileExistsCheck",
    "FreeGate",
    "HarnessError",
    "HttpStatusCheck",
    "JudgeCheck",
    "PredicateCheck",
    "Receipt",
    "ReceiptLog",
    "RunOutput",
    "ScaleGuard",
    "ScaleRefused",
    "SchemaCheck",
    "SwarmPick",
    "SwarmResult",
    "TaskSpec",
    "Worker",
    "fan_out",
    "judge_prompt",
    "layer_reached",
    "run_task",
]
