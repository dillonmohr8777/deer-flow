"""Pluggable verifiers.

Two kinds, one answer shape:

* deterministic -- a command's exit code, a file on disk, an HTTP status, a
  schema match. Cheap, repeatable, and the thing a worker can learn to game.
* judge-style -- a model handed the spec and the evidence and asked to refute
  the result. This is the guard against a run whose tests are green but whose
  intent was not met: `JudgeCheck` fails when the judge can refute, and also
  fails closed when the judge is unavailable or answers off-contract.

Every check is a small frozen dataclass with `name`, `layer` and `__call__`, so
adding one is a class, not a framework change.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import CheckResult, RunOutput, TaskSpec, canonical_json

DETAIL_LIMIT = 400
EVIDENCE_TEXT_LIMIT = 4000
EVIDENCE_FILE_LIMIT = 8


def _clip(text: str, limit: int = DETAIL_LIMIT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _paths_from(output: RunOutput, literal: tuple[str, ...], output_key: str) -> list[str]:
    paths = list(literal)
    if output_key:
        value = output.output.get(output_key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, (list, tuple)):
            paths.extend(str(item) for item in value)
    return paths


@dataclass(frozen=True)
class CommandCheck:
    """Exit code of a real command. The default is `0` means pass."""

    name: str
    argv: tuple[str, ...]
    layer: str = "tested"
    cwd: str | None = None
    expect_code: int = 0
    timeout_s: float = 300.0

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        try:
            done = subprocess.run(self.argv, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout_s, check=False)  # noqa: S603
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CheckResult(self.name, self.layer, False, _clip(f"command_failed: {exc}"))
        ok = done.returncode == self.expect_code
        tail = done.stderr.strip() or done.stdout.strip()
        return CheckResult(self.name, self.layer, ok, _clip(f"exit={done.returncode} {tail}"))


@dataclass(frozen=True)
class FileExistsCheck:
    """Non-empty files on disk. `output_key` reads the list from the worker."""

    name: str
    paths: tuple[str, ...] = ()
    layer: str = "tested"
    output_key: str = ""
    allow_empty: bool = False

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        wanted = _paths_from(output, self.paths, self.output_key)
        if not wanted:
            return CheckResult(self.name, self.layer, False, "no_paths_declared")
        missing = [p for p in wanted if not Path(p).is_file() or (not self.allow_empty and Path(p).stat().st_size == 0)]
        ok = not missing
        return CheckResult(self.name, self.layer, ok, "ok" if ok else _clip(f"missing_or_empty: {missing}"), evidence=tuple(wanted))


@dataclass(frozen=True)
class HttpStatusCheck:
    """Status code of a URL. `fetch` is injectable so tests stay offline."""

    name: str
    url: str
    expect: int = 200
    layer: str = "installed"
    timeout_s: float = 15.0
    fetch: Callable[[str, float], int] | None = None

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        fetch = self.fetch or _urllib_status
        try:
            status = fetch(self.url, self.timeout_s)
        except Exception as exc:  # any transport problem is a failed check, not a crash
            return CheckResult(self.name, self.layer, False, _clip(f"fetch_failed: {exc}"))
        ok = status == self.expect
        return CheckResult(self.name, self.layer, ok, f"status={status} expected={self.expect}", evidence=(self.url,))


def _urllib_status(url: str, timeout_s: float) -> int:
    import urllib.request  # noqa: PLC0415 - only needed when no fetch is injected

    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
        return int(response.status)


@dataclass(frozen=True)
class SchemaCheck:
    """Shape of the worker's output: required fields, types, no extras."""

    name: str
    fields: Mapping[str, type] = field(default_factory=dict)
    layer: str = "tested"
    closed: bool = True

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        problems: list[str] = []
        for key, kind in self.fields.items():
            if key not in output.output:
                problems.append(f"missing:{key}")
            elif not isinstance(output.output[key], kind):
                problems.append(f"type:{key}")
        if self.closed:
            problems.extend(f"extra:{key}" for key in output.output if key not in self.fields)
        ok = not problems
        return CheckResult(self.name, self.layer, ok, "ok" if ok else _clip(str(sorted(problems))))


@dataclass(frozen=True)
class PredicateCheck:
    """Escape hatch for a workflow-specific rule. `fn` returns (ok, detail)."""

    name: str
    fn: Callable[[TaskSpec, RunOutput], tuple[bool, str]]
    layer: str = "tested"

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        try:
            ok, detail = self.fn(spec, output)
        except Exception as exc:
            return CheckResult(self.name, self.layer, False, _clip(f"predicate_failed: {exc}"))
        return CheckResult(self.name, self.layer, bool(ok), _clip(detail))


def judge_prompt(spec: TaskSpec, output: RunOutput) -> str:
    """The refutation prompt: spec, stop rule, output and the evidence itself."""
    lines = [
        "You are verifying another agent's work. Try to REFUTE it.",
        "",
        f"Task id: {spec.id}",
        f"Client: {spec.client_id}",
        f"Goal: {spec.goal}",
        f"Stop rule: {spec.stop_rule or '(none stated)'}",
        f"Declared inputs: {canonical_json(dict(spec.inputs))}",
        "",
        f"Worker output: {canonical_json(dict(output.output))}",
        f"Worker claimed done: {output.done}",
        "",
        "Evidence files:",
    ]
    for path in output.evidence[:EVIDENCE_FILE_LIMIT]:
        lines.append(f"--- {path}")
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            lines.append(f"(unreadable: {exc})")
            continue
        lines.append(text[:EVIDENCE_TEXT_LIMIT])
        if len(text) > EVIDENCE_TEXT_LIMIT:
            lines.append("(truncated)")
    lines += [
        "",
        "Green tests do not settle this. Refute if the goal was not actually met,",
        "if a figure or claim is not supported by the evidence, if the work was",
        "shaped to satisfy the checks rather than the goal, or if a declared",
        "constraint was broken.",
        'Answer with JSON only: {"verdict": "refuted" | "upheld", "why": "<one sentence>"}',
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class JudgeCheck:
    """A model asked to refute the result.

    `judge(prompt) -> {"verdict": "upheld"|"refuted", "why": str}`. Anything
    else -- an exception, a missing verdict, an unknown verdict -- fails the
    check, so an unavailable judge can never wave a run through.
    """

    name: str
    judge: Callable[[str], Mapping[str, Any]]
    layer: str = "accepted"

    def __call__(self, spec: TaskSpec, output: RunOutput) -> CheckResult:
        try:
            answer = self.judge(judge_prompt(spec, output))
        except Exception as exc:
            return CheckResult(self.name, self.layer, False, _clip(f"judge_unavailable: {exc}"))
        if not isinstance(answer, Mapping):
            return CheckResult(self.name, self.layer, False, "judge_answer_malformed")
        verdict = str(answer.get("verdict", "")).strip().lower()
        why = _clip(answer.get("why", ""))
        if verdict == "upheld":
            return CheckResult(self.name, self.layer, True, f"upheld: {why}")
        if verdict == "refuted":
            return CheckResult(self.name, self.layer, False, f"refuted: {why}")
        return CheckResult(self.name, self.layer, False, _clip(f"judge_verdict_unknown: {verdict!r}"))
