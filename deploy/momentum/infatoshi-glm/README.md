# Infatoshi GLM connection for MomoBot

Status on 2026-10-02: prepared locally, disabled, no inference run, no GPU rented.

Local validation: all five offline regression tests passed; Ruff lint and formatting passed; the profile passed the current DeerFlow `ModelConfig` schema; server/profile model ID and context size match; `git diff --check` passed. No application runtime code changed, so the full frontend build was not run. Live probe and workload evaluation remain pending an endpoint.

The screenshot links to [Infatoshi/GLM-5.3-UNCENSORED-EXL3-3.0bpw](https://huggingface.co/Infatoshi/GLM-5.3-UNCENSORED-EXL3-3.0bpw), a model repository rather than an institute. It is an EXL3 conversion of a weight-edited GLM checkpoint. Verified Hugging Face revision: `d06b4f42db97c8bb7a8f72e819b979f132e4a721`. Pin that revision for any later download.

The model card reports 273 GiB of weights and testing on eight A100 40GB GPUs. This Mac has 48 GiB unified memory, insufficient for these weights. Hugging Face lists no inference provider for the checkpoint. The public OpenRouter catalog checked today contains stock GLM-5.3 variants, but no Infatoshi/dealign uncensored checkpoint. Stock GLM is not a substitute for the requested artifact.

## Prepared integration

`model-profile.yaml` is an opt-in model-list fragment for the existing DeerFlow config and ChatOpenAI adapter. It uses the exact server model ID, bounded output, no SDK retries, and process-local admission limits. Do not replace the whole workspace config with it. Append its single model entry to the existing `models` list only after server acceptance and activation approval; do not make it the first/default model. Both YAML files use JSON syntax, which is valid YAML.

`tabby-config.yaml` is a server template based on the model author's serving settings and [TabbyAPI's official sample](https://github.com/theroyallab/tabbyAPI/blob/main/config_sample.yml). It binds loopback, requires authentication, disables prompt logging, and limits generation concurrency. The template alone does not provision hardware, install TabbyAPI, download weights, or fix its tool parser. Pin and review the actual server revision before installation.

Set `INFATOSHI_TABBY_BASE_URL` and `INFATOSHI_TABBY_API_KEY` in the existing runtime secret environment, using the Credential Master Orchestrator and existing credential stores. The profile uses DeerFlow's documented `$VARIABLE` resolution syntax. Do not place key values in this package. Remote access should use HTTPS or an SSH tunnel exposed at loopback. Inside Docker, `127.0.0.1` refers to the container, so choose a reachable authenticated endpoint appropriate to the gateway.

## Acceptance before activation

The card warns that an affected TabbyAPI parser converts numeric-looking string arguments to integers. Its reported agent benchmark used a fix. Require a server revision that preserves schema-declared strings; verify the real response rather than assuming the fix is present. The model card's benchmark claims are author-reported, not independently reproduced here.

Run `python3 deploy/momentum/infatoshi-glm/probe.py` with the two environment variables. It makes one model-list request and one synthetic completion, with no retries. It requires the exact model ID and rejects numeric coercion or lost leading zeros. It never executes a returned tool. Server listing alone cannot establish weight provenance: retain the pinned download revision and loaded model path in a sanitized server receipt. Probe success establishes only this narrow tool-call contract, not general agent quality.

Run the offline regression checks with `python3 -m unittest discover -s deploy/momentum/infatoshi-glm -p 'test_*.py'`. Before broader use, evaluate multi-step tool calls, streaming, cancellation, reasoning output, and useful results on the same held-out MomoBot workload as existing models. Use synthetic inputs initially. Thinking and vision UI flags remain disabled pending endpoint verification; server-side reasoning may still run.

No default route, running MomoBot config, provider hold, credentials, or deployed service was changed. No client data was sent. Live activation requires a suitable existing GPU endpoint or separately approved provisioning and spend, followed by the acceptance probe and a bounded workload evaluation. Removing the model entry after later activation restores the prior routing; these prepared files can remain as evidence.
