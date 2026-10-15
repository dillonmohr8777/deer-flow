"""Run the agency eval set against an OpenAI-compatible endpoint and write results JSON.

Offline pieces (task loading, prompt building, totals) are pure and unit tested.
The key is read from a named env var (default OPENROUTER_API_KEY) and never written out.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .scorers import run_checks

TASKS_PATH = Path(__file__).with_name("tasks.jsonl")
SYSTEM_PROMPT = (
    "You are Dillon's marketing agency assistant. Write like a sharp, casual human: short sentences, no corporate or AI phrasing. "
    "Never use em dashes or en dashes. Never add an AI signature, footer or disclaimer. Only use numbers that appear in the data you are given. "
    "Do not use placeholders like [Name]. Follow the format and length limits in the task exactly."
)


def load_tasks(path: Path = TASKS_PATH) -> list[dict]:
    tasks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids")
    return tasks


def build_messages(task: dict) -> list[dict]:
    user = task["prompt"]
    if task.get("fixture"):
        user += "\n\nDATA:\n" + task["fixture"]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def task_cost(usage: dict, price_in: float, price_out: float) -> float:
    """Prefer the provider-reported cost (OpenRouter usage.cost); else per-million-token prices."""
    if usage.get("cost") is not None:
        return float(usage["cost"])
    return (usage.get("prompt_tokens", 0) * price_in + usage.get("completion_tokens", 0) * price_out) / 1_000_000


def score_task(task: dict, output: str) -> dict:
    checks = run_checks(output, task)
    return {"passed": bool(checks) and all(c["passed"] for c in checks), "checks": checks}


def compute_totals(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    cost = sum(r.get("cost", 0.0) for r in results)
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"n": 0, "passed": 0, "cost": 0.0})
        c["n"] += 1
        c["passed"] += int(r["passed"])
        c["cost"] += r.get("cost", 0.0)
    for c in by_cat.values():
        c["pass_rate"] = c["passed"] / c["n"] if c["n"] else 0.0
    return {
        "tasks": n,
        "passed": passed,
        "errors": sum(1 for r in results if r.get("error")),
        "pass_rate": passed / n if n else 0.0,
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in results),
        "completion_tokens": sum(r.get("completion_tokens", 0) for r in results),
        "cost": cost,
        "cost_per_task": cost / n if n else 0.0,
        "by_category": by_cat,
    }


def call_model(client, base_url: str, api_key: str, model: str, task: dict, max_tokens: int, reasoning_effort: str = "") -> tuple[str, dict]:
    body = {"model": model, "messages": build_messages(task), "temperature": 0, "max_tokens": max_tokens, "usage": {"include": True}}
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.post(f"{base_url.rstrip('/')}/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"].get("content") or ""), data.get("usage", {})
        except Exception as exc:  # retry transient failures, report the last one
            last = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"{type(last).__name__}: {str(last)[:200]}")


def run(model: str, base_url: str, api_key_env: str, out: Path, tasks: list[dict], price_in: float = 0.0, price_out: float = 0.0, max_tokens: int = 1200, workers: int = 4, client=None, reasoning_effort: str = "") -> dict:
    import httpx

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise SystemExit(f"{api_key_env} is not set")
    client = client or httpx.Client()

    def one(task: dict) -> dict:
        row = {"id": task["id"], "category": task["category"], "passed": False, "checks": [], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "output": ""}
        try:
            output, usage = call_model(client, base_url, api_key, model, task, max_tokens, reasoning_effort)
            row.update(score_task(task, output))
            row.update(output=output, prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0), cost=task_cost(usage, price_in, price_out))
        except Exception as exc:
            row["error"] = str(exc)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, tasks))
    doc = {"model": model, "base_url": base_url, "started_at": datetime.now(UTC).isoformat(timespec="seconds"), "totals": compute_totals(rows), "results": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
