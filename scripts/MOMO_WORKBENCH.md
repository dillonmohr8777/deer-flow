# MomoBot Mac workbench

`momo_workbench.py` is a Python3.12+ standard-library client for the existing authenticated `/api/workflows` service. It creates no local execution queue, scheduler, provider account or model/browser key. Installing it does not execute work. The operator installs the wrapper separately after QA; source is runnable with `python3 scripts/momo_workbench.py --help`.

The endpoint defaults to the native MomoBot app's private `~/Library/Application Support/MomoBot/connection.json`, or `MOMO_WORKBENCH_SERVER`; `--server` overrides it. Accepted installed `/workspace/openai` and `/workspace/workflows` paths normalize to the origin. HTTPS is required except HTTP loopback development. Redirects and environment proxies are disabled, so authentication never migrates to another server. Every response is bounded and verified against the original origin.

`login --email OWNER_EMAIL` reads the password with `getpass` and uses the existing password+MFA routes. If MFA is required, enter the six-digit authenticator code privately. No credential, challenge or cookie is printed. There is no Keychain prompt or new credential creation. Subsequent invocations reuse `~/.local/state/momo-workbench/auth.json`, verified as owner-owned, nonsymlink,0600; its directory is0700. Only MomoBot's fixed `momo_agent_` session cookies and the CSRF cookie are retained, scoped to that exact origin. A saved actor or organization/storage-scope change blocks work until another explicit login. Cookie expiry/revocation still applies.

Read-only commands:

```sh
momo-workbench doctor
momo-workbench catalog
momo-workbench status
momo-workbench status RUN_ID
```

`doctor` reads direct gateway health, or the existing public auth setup probe when the installed frontend returns404for `/health`; it never exposes another gateway route. If a private session is already saved, it reads actual workflow capabilities/limits; otherwise it reports `sign_in_required`. `catalog` lists recipe metadata; no run is admitted. `status` reads the actual server-owned run, usage and admission state. Never equate installation, health or worker availability with accepted useful output.

Explicit execution and verified download:

```sh
momo-workbench run WORKFLOW_ID --inputs /absolute/private/inputs.json --framework langgraph --idempotency-key cli_reviewed_1 --wait
momo-workbench artifact RUN_ID
```

Inputs must be a JSON object <=48000bytes. `run` appends a private admission receipt with the stable idempotency key and request hash before making exactly one POST; it never retries automatically. If transport becomes ambiguous, reuse the reported same key with identical input to read back the existing server admission. Do not invent a fresh key to replace an uncertain paid attempt. Waiting is bounded and does not stop the durable server run on timeout. Artifacts require a completed, accepted run and exact server-receipted SHA256/byte count. Files are saved0600 under the private workbench directory and existing different contents are never overwritten. `--output` requires a private0700parent.

Finite same-input framework comparison:

```sh
momo-workbench benchmark WORKFLOW_ID --inputs /absolute/private/held-out.json --framework langgraph --framework crewai --framework mastra --max-model-calls 18 --max-output-tokens 24576
```

This admits at most three sequential runs of one recipe against the same input, using available framework workers. It checks server per-run ceilings before admission; the existing gateway still owns global daily caps, queued work, browser quotas, actor/org authorization, metered model calls and cancellation. It stores private receipts, actual per-run usage, acceptance and verified artifact hashes. Input text is omitted from the benchmark report. It does not benchmark the full Agno AgentOS platform, an Inngest cloud scheduler, or every recipe in the catalog. Unknown actual costs remain unavailable; list prices cannot establish a cost winner.

Offline QA: `backend/tests/test_momo_workbench.py` covers safe origins, private file permissions/symlinks, CSRF/scope headers, redirects/error privacy, MFA/saved-cookie reuse, changed-owner rejection, single ambiguous admission, digest readback/non-overwrite, finite same-input comparison and no-action help. Live login and useful output acceptance are separate operator checks.
