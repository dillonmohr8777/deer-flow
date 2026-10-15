# Optional Momentum SDK review worker

This is a **synthetic offline integration**, disabled by default. It connects an
existing MomoBot LangChain tool to the installed OpenAI Agents SDK in a separate
process and validates a typed draft packet. It does not generate actual client
recommendations, call a model provider, send messages, export private traces,
write the canonical queue, install itself into production, or replace LangGraph.

The bundled `momentum_sdk/adapter.py` is a minimal source snapshot of the local
reviewed workbench: its HandoffPacket, Limits and draft functions. Live provider,
voice/realtime and unrelated canonical helpers are intentionally absent. The
worker uses ScriptedModel assistant fixtures, not real inference. All socket
connects/DNS resolution are blocked before the SDK imports; tracing is disabled.

Prepare a separate optional Python environment with the pinned requirements
only when dependencies are desired; do not add SDK dependencies to the main
Gateway lockfile. A host Mac virtualenv is not available automatically inside
Docker. Production Docker installation and authenticated activation need a
separate reviewed change; no automatic setup/download/startup hooks are added.

Trusted host code can call `app.gateway.momentum_sdk_access.prepare_sdk_reviewer`
with `enabled=True`, effective storage owner, exact thread/run IDs, authorized
canonical IDs, the existing canonical root, and an absolute WorkerSpec. Attach
the returned capability to `RunContext(momentum_sdk_reviewer=...)`. This factory
is not invoked by the HTTP router, and no public request field grants it. The
host must already authenticate and authorize that owner/scope; constructing the
factory directly is privileged programmatic access. Default returns None.

A custom lead agent must explicitly list the `momentum_sdk` tool group. Its
operator-controlled tool entry is:

```yaml
- name: momentum_sdk_draft
  group: momentum_sdk
  use: deerflow.community.momentum_sdk.tools:momentum_sdk_draft
```

Do not enable this in live config as part of the offline build. Default agents,
bootstrap, ordinary discovery, and subagents withhold the tool; the tool itself
also rejects subagents. Worker-injected context is authoritative; forged keys
in context/configurable are stripped and terminal cleanup drops the reference.

Only exact authorized canonical IDs are read. Reads use existing
`registry/clients.json` and `queue/work-items.json`, read-only no-follow file and
directory descriptors, 10 MB source bounds, and no alternate queue. Missing
identity fails closed; verified zero matches and unknown engagement remain
separate facts. Only ID/status/revision/count metadata reaches the SDK worker.
The model-facing request is bounded to 8000 characters and 32 KiB encoded input;
stdout/stderr are independently limited to 16 KiB; default execution deadline
is 35 seconds (max 60), within the worker SDK draft's 30 seconds/3 turns.

The subprocess uses a fixed interpreter/script, isolated Python mode, a minimal
environment without inherited credentials, and no shell. Script symlinks and
changes since host grant preparation are rejected. The interpreter may be a
normal virtualenv symlink. Apple/Python can add locale/encoding environment
metadata; tests distinguish those from inherited credentials. Source/package
installation remains operator-trusted; these measures are not an OS sandbox.
POSIX cancellation kills/drains the owned process group; Windows kills the
worker itself and is not a descendant sandbox. The fixed worker launches none.
Errors stay sanitized; packet validation rejects wrong identity, invalid status,
extra fields, empty evidence, and oversize output. Evidence strings are not truth
verification. Successful synthetic output is marked synthetic and draft.

Offline test, using an already prepared pinned SDK environment:

```sh
cd backend
PYTHONPATH=packages/harness:. MOMENTUM_SDK_TEST_PYTHON=/absolute/sdk-venv/bin/python \
  python -m pytest tests/test_momentum_sdk_bridge.py -q
```

If the optional interpreter is absent, SDK-specific tests explicitly skip; the
host admission tests still run. No environment installation is performed by the
tests. Full backend offline and blocking-I/O checks remain required before merge.
