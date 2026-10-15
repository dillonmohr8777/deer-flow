"""CLI: `run` calls a model (needs an API key env var); `report` builds the static HTML offline."""

import argparse
from pathlib import Path

from .report import build_report
from .runner import TASKS_PATH, load_tasks, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="command", required=True)
    r = cmds.add_parser("run", help="Send every task to the model and write results JSON")
    r.add_argument("--model", required=True)
    r.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    r.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--tasks", type=Path, default=TASKS_PATH)
    r.add_argument("--limit", type=int, default=0, help="Only the first N tasks (smoke runs)")
    r.add_argument("--price-in", type=float, default=0.0, help="USD per 1M prompt tokens, used only if the endpoint reports no cost")
    r.add_argument("--price-out", type=float, default=0.0, help="USD per 1M completion tokens")
    r.add_argument("--max-tokens", type=int, default=1200)
    r.add_argument("--reasoning-effort", default="", help="Optional: low, medium or high, sent as reasoning.effort")
    h = cmds.add_parser("report", help="Render results JSON files (oldest to newest) into one static HTML page")
    h.add_argument("results", type=Path, nargs="+")
    h.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "report":
        build_report(args.results, args.out)
        print(f"wrote {args.out}")
        return
    tasks = load_tasks(args.tasks)
    if args.limit:
        tasks = tasks[: args.limit]
    doc = run(args.model, args.base_url, args.api_key_env, args.out, tasks, args.price_in, args.price_out, args.max_tokens, reasoning_effort=args.reasoning_effort)
    t = doc["totals"]
    print(f"{doc['model']}: {t['passed']}/{t['tasks']} passed ({t['pass_rate']:.0%}), cost ${t['cost']:.4f}, ${t['cost_per_task']:.4f}/task, errors {t['errors']}")


if __name__ == "__main__":
    main()
