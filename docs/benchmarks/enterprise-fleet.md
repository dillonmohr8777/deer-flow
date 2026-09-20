# Enterprise fleet evidence evaluator

This is an offline repository evidence score, **not a SWE-bench or Terminal-Bench
model score**. A passing score does not approve deployment or establish production
readiness, tenant isolation, agent quality, or benchmark superiority. No model,
provider API, dataset download, Docker command, Helm command, or test command runs
inside the evaluator. It uses the Python standard library and reads only the
specified artifacts and receipts, its own source, and local Git metadata.

## Run locally

From `backend/`, using the existing Python environment:

```sh
python -m scripts.benchmark.enterprise_fleet
python -m scripts.benchmark.enterprise_fleet --receipt /local/docker.json --receipt /local/helm.json --receipt /local/tests.json --output /local/new-report.json
python -m pytest tests/test_enterprise_fleet_benchmark.py -q
```

`--root PATH` selects another local checkout. `--receipt PATH` is repeatable, and
each file contains one JSON object. Output defaults to stdout; `--output` requires
a new file in an existing directory and refuses to overwrite files. Exit code 0
means every required evidence gate passed, 1 means failure or incomplete evidence,
and 2 means a CLI/output error. Missing receipts are explicitly incomplete.

The fixed rubric contains 11 equally weighted checks:

| Evidence | Checks | What receives credit |
| --- | ---: | --- |
| Required artifacts | 6 | Nonempty files for the paths below, resolving inside the repository. |
| JSON syntax | 2 | Both fleet JSON files parse as UTF-8 JSON without duplicate keys or non-finite constants. |
| Docker receipts | 1 | At least one `docker` or `docker.*` receipt; every supplied receipt in the group passes. |
| Helm receipts | 1 | At least one `helm` or `helm.*` receipt; every supplied receipt in the group passes. |
| Test receipts | 1 | At least one `tests` or `tests.*` receipt; every supplied receipt in the group passes. |

Required artifacts:

- `fleet/manifest.json`
- `fleet/evals/role-evals.json`
- `docker/docker-compose.yaml`
- `docker/docker-compose-dev.yaml`
- `deploy/helm/deer-flow/Chart.yaml`
- `plans/momentum-enterprise-runtime-contract.md`

The score is `passed / 11 * 100`, rounded to two decimals. It measures presence of
evidence, not the percentage of application tests passed. JSON semantics and agent
configuration remain owned by the production validators and existing fleet tests;
this script does not duplicate them or introduce another agent runtime.

## Receipt contract

Example only; this is synthetic, not a claim that the command ran:

```json
{
  "name": "helm.lint",
  "command": "helm lint deploy/helm/deer-flow",
  "status": "skip",
  "exit_code": null,
  "timestamp_utc": "2026-09-20T00:00:00Z",
  "details": "Synthetic example: Helm has not been run."
}
```

Required fields are nonempty `name`, `command`, and `timestamp_utc` strings,
`status` (`pass`, `fail`, or `skip`), and `exit_code` (integer or null). A pass
requires exit code 0, failure requires a nonzero integer, and skip requires null.
Timestamps must include UTC (`Z` or `+00:00`). Contradictory or malformed receipts,
invalid JSON, and duplicate receipt names invalidate all receipt-group credit.
Use one final receipt per check; a later passing duplicate cannot conceal failure.
Every explicit failure blocks report status `pass`, including supplemental receipt
names outside the three scored prefixes. Supplemental names never add points.

Suggested receipt names are `docker.compose.prod`, `docker.compose.dev`,
`helm.lint`, `helm.template`, `tests.enterprise`, `tests.offline`, and
`tests.blocking-io`. Record the actual command and its exit status. A missing tool
is a skip; a static file inspection is not a Docker/Helm validation receipt. Run
both Compose validations and Helm lint/render during integration, then supply all
their receipts. The generic group scoring cannot detect a check an operator omits.

Receipts are operator assertions, not authenticated execution evidence. Reviewers
must reconcile commands, logs, tool versions, tested commit/tree, and timestamps.
Optional `details` may describe redacted evidence or its location; the evaluator
hashes the entire receipt but does not echo `details`. Keep credentials, environment
values, response headers, provider payloads, and unredacted logs out of every field.

## Reproducibility and dataset boundaries

The report records the evaluator and configuration SHA-256, all required artifact
SHA-256 values (including the fleet manifest), receipt SHA-256 values, Git HEAD,
and the working-tree dirty flag. Git fields are null if Git metadata is unavailable.
The artifact digests do not fingerprint uncommitted production code; preserve the
reviewed patch or integration tree with the execution receipts for that purpose.
No wall clock or randomness participates in grading. Receipt order is normalized;
fixed input bytes and Git state produce the same report. Output is local evidence
and should not be committed as a machine-specific benchmark result.

No external dataset or model prompt participates here: `external_datasets` and
`prompts` are empty, and model/inference settings are null. The regression fixture
is synthetic. Public benchmark links below are context, not loaded evaluation data.

Any future external-dataset evaluation must follow `backend/AGENTS.md`: accept an
explicit local dataset path, pin an immutable revision **and SHA-256**, fail on a
digest mismatch, and never silently download. Record dataset/config/manifest/prompt
and Git revisions, fixed clocks/seeds, exact model IDs, inference parameters, and
retry rules. Read credentials/endpoints only from named environment variables in
an explicitly authorized live runner. Do not commit upstream questions, reference
answers, memory content, credentials, full provider requests, or response headers;
retain those only in ignored local run directories. Reuse production functions
when measuring runtime behavior.

## Official benchmark context

Sources below were accessed **2026-09-20**. Scores describe their named source's
reported configuration; none was reproduced by this repository evaluator. Model,
harness, safeguards, effort, dataset revision, attempts, and resource limits must
match before comparing scores. Percentages from different benchmarks are not a
common scale.

| Benchmark or claim | Verified official context | Source and interpretation |
| --- | --- | --- |
| SWE-bench Verified | The maintained official site describes 500 human-filtered issue-resolution instances. Its default Bash Only view uses the same mini-SWE-agent environment across models. | [SWE-bench team leaderboard](https://www.swebench.com/). `% Resolved` is task success under the named harness; artifact presence is not an equivalent metric. |
| SWE-Bench Pro, public | Scale lists 731 public tasks, alongside separate private and held-out sets. A resolved task must pass both fail-to-pass and pass-to-pass tests. | [Scale's official public benchmark](https://labs.scale.com/leaderboard/swe_bench_pro_public). Its launch-era prose/scores are not a current universal model ranking; keep public and private results distinct. |
| Terminal-Bench, current official release | **Terminal-Bench 4.0 exists.** The official repository marks `v4.0.0` latest; the release points to `terminal-bench/terminal-bench@4.0.0`. The update changes resources and tasks, requiring new trials. | [Official 4.0 announcement](https://www.tbench.ai/news/terminal-bench-4-0), [official GitHub release](https://github.com/harbor-framework/terminal-bench/releases/tag/v4.0.0). The announcement lists 4.1 and 5.0 as upcoming; 2.0/2.1/3.0 results are not interchangeable with 4.0. |
| OpenAI vendor-reported coding results | OpenAI reports GPT-6 Astra at **57.9%** on Terminal-Bench 4.0, with GPT-5.6 Sol at **37.3%** in its comparison. Its coding table also reports Astra **74.1%** on DeepSWE v1.1. | [OpenAI's Astra announcement](https://openai.com/index/gpt-6-astra/). The page says scores use the best effort setting and research/API environments, which may differ from production ChatGPT. These are vendor claims, not local measurements. |
| Anthropic vendor-reported coding results | Anthropic reports Claude Fable 5.1 **55.8%** and Mythos 5.1 **60.9%** on Terminal-Bench 4.0. | [Anthropic's Fable/Mythos 5.1 announcement](https://www.anthropic.com/claude-fable-and-mythos-5-1). It identifies the same underlying model with different safeguards and attributes the reported gap to safeguard intervention; do not merge those rows into one model score. |
| OpenRouter model-page claims | OpenRouter lists `openai/gpt-6-astra`; its benchmark section labels a **76.9 Coding Index** for GPT-6 Astra (max) as sourced from Artificial Analysis. | [Official OpenRouter model page](https://openrouter.ai/openai/gpt-6-astra). This verifies what OpenRouter displays, not an independent OpenRouter benchmark run, and an index value is not a SWE/Terminal task-resolution percentage. |

For Terminal-Bench source provenance, the release links to commit
[`452bf305c6daa62fc59061d22133a7cbc7c1572e`](https://github.com/harbor-framework/terminal-bench/commit/452bf305c6daa62fc59061d22133a7cbc7c1572e).
That identifies source revision only. No dataset archive was downloaded or hashed,
so this document does **not** supply a runnable pinned external-dataset manifest.
