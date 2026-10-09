# Bounded AgentOS challenger

`workers/agno-team/agentos_probe.py --agentos` exercises the pinned Agno 3.0.11
AgentOS platform through its actual FastAPI ASGI routes. It is separate from the
existing individual Agno worker. It invokes one agreed specialist, persists the
native session/run in private async SQLite, closes the native application
lifespan, then constructs a fresh AgentOS instance and reads the output back.
It does not register another production framework or a permanent coordinator.

## Execute under the existing meter

Use the isolated interpreter and a dedicated private QA directory:

```sh
workers/agno-team/.venv/bin/python workers/agno-team/agentos_probe.py \
  --agentos --state-dir "$PROBE_STATE_DIR" --owner-scope "$TRUSTED_OWNER_SCOPE"
```

The parent sends the same version-1 JSON-line `invoke` frame used by the
individual worker: `call_id`, `worker_id`, `role`, `model`, `effort`, `prompt`, and
optional `continuation`, with the existing output-schema and token-budget fields
retained for parent admission. The agreed model is `gpt-6.1-sol`; effort is
`low`, `medium`, or `high`. The worker emits exactly one `model_request` with the
same `call_id` and the actual native messages. **The parent must reserve the
existing finite model budget, validate the requested schema, execute the admitted
call, journal actual/unknown usage, and reply with `model_result`.** No model key
is given to AgentOS. Use the parent worker environment allowlist rather than
forwarding credentials or proxies.

The final `result` frame retains `version`, `call_id` and `output`. Its extra
`native` receipt contains the actual `run_id`, `session_id`, compact-output
SHA-256, `persisted: true` and `restart_readback: true`. Those flags are emitted
only after native readback succeeds. Diagnostic logging goes to stderr because
Agno's import-time stdout handlers otherwise corrupt the framing.

The native run endpoint receives `stream=false`, `background=false`, the supplied
prompt, and a session ID derived from trusted owner scope plus `call_id`.
Continuation messages remain native `additional_input`, with history disabled
for this single-input comparison. A pre-existing session causes a fail-closed
exit before another model request; the probe does not silently retry uncertain
or completed work. This local preflight is not a distributed idempotency gate.

## Authentication and storage

The actual AgentOS JWT middleware uses a fresh in-memory signing key, audience
verification, an expiring token, and `AuthorizationConfig(user_isolation=True)`.
The internal caller receives only the particular agent's run scope and session
read scope, without admin access. Native middleware pins the JWT subject on
session reads and writes; client-supplied `user_id` cannot change it. The signing
key and JWTs are neither persisted nor emitted. This tests a local runtime
boundary, not integration with MomoBot's production token issuer.

The private state directory must belong to the current POSIX user and permit no
group/other access; the SQLite file is mode `0600`. Symlink paths, unsafe existing
files and invalid invocations fail before model dispatch. Database state is
retained; original QA stores are not imported, overwritten or deleted.

## Exact bounds and unverified capabilities

- One model handoff per specialist instance, without model/agent retries, tools,
  streaming, scheduler, MCP, telemetry or tracing.
- A 262,144-byte frame, 131,072-byte prompt, 200-byte role, at most four
  continuation messages, and a 48,000-byte JSON output. Usage must contain known
  nonnegative integer token counts. The parent owns token/spend admission.
- Pipe reads have a finite maximum 120-second deadline, including partial lines;
  the ASGI single-shot operation also has a 120-second deadline. The parent must
  retain its subprocess timeout/termination fence and uncertain-attempt journal.
- No TCP listener, cloud Control Plane, external console or additional serving
  process. This implementation is a Mac/POSIX probe, not a Windows release.
- Native durable queue, Redis coordination, multi-replica leases, distributed
  cancellation, approval continuation, platform teams/workflows and full
  production activation remain unverified. Session persistence alone does not
  establish these capabilities or comparative model quality/cost.

## Offline validation and official evidence

```sh
cd workers/agno-team
uv sync --frozen
uv run --no-sync pytest ../../docs/tests/test_agentos_probe.py -q
```

The tests run actual native ASGI endpoints and async SQLite. They deny external
HTTP/socket I/O, verify run/restart readback, JWT signature/audience/expiry/RBAC,
cross-tenant reads and append attempts, single-call framing, partial-pipe timeout,
replay refusal, and private storage safety. CLI tests use explicitly synthetic
model output and known fake usage. An inherited dummy model key never enters
wire output, diagnostics, or the custom model implementation. No live provider
acceptance is claimed by these tests.

The installed 3.0.11 source was inspected in `agno/os/app.py`,
`agno/os/routers/agents/router.py`, `agno/os/routers/session/session.py`,
`agno/os/middleware/user_scope.py`, `agno/os/config.py` and the async SQLite
implementation. Current official documentation was checked on 2026-09-30:

- [AgentOS introduction](https://docs.agno.com/agent-os/introduction) describes its
  FastAPI runtime and the separate platform services.
- [Using the API](https://docs.agno.com/agent-os/using-the-api) documents the native
  run/session interface and non-streaming JSON response.
- [AuthorizationConfig](https://docs.agno.com/reference/agent-os/authorization-config)
  identifies user isolation as opt-in and admin access as an exception.
- [Session persistence](https://docs.agno.com/sessions/persisting-sessions/overview)
  distinguishes durable session storage from identity labels.

`agno[os]`, async SQLite/SQLAlchemy and test dependencies are locked only in
`workers/agno-team/pyproject.toml` and `uv.lock`; the application environment is
unchanged. SQLAlchemy's asyncio extra supplies the required `greenlet` dependency
for the installed SQLite import path.
