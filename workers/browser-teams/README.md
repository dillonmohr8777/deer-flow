# MomoBot isolated browser/framework workers

Installed exact pins: Stagehand4.1.0, Mastra1.72.0, BrowserbaseSDK2.16.0, AI SDK provider2.0.3, Zod4.4.3 under Node24+. The isolated Python3.13 environment pins CrewAI1.15.23 and DeepAgents0.7.20. Lockfiles live here; the shared gateway Python websockets override is untouched. Root-owned Agno/Inngest AgentKit workers use the same gateway admission relay in sibling directories.

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run check
npm test
uv sync --project python --frozen
```

The complete offline backend suite also exercises the sibling Agno and AgentKit
workers. From the repository root, install their committed locks before testing:

```sh
uv sync --project workers/agno-team --python 3.13 --frozen
cd workers/inngest-team
npm ci --ignore-scripts --no-audit --no-fund
npm run check
```

Backend CI installs all isolated workers in every duration-balanced shard using
Python3.13 and Node24.21.0. Real framework tests still assert availability and
one admitted native relay; missing workers fail rather than being skipped.
These tests use synthetic offline responses and never enable paid providers.
## Optional private container image

The normal Gateway image excludes these worker environments. Build the opt-in
`workflow-runtime` from a reviewed local Gateway image; no provider key, private
config, host environment or runtime state belongs in the build context:

```sh
docker build -f workers/Dockerfile --target workflow-runtime \
  --build-arg MOMOBOT_GATEWAY_IMAGE=YOUR_REVIEWED_LOCAL_GATEWAY_IMAGE \
  --build-arg MOMOBOT_WORKER_SOURCE_REVISION=YOUR_REVIEWED_WORKER_COMMIT \
  -t momobot-private-workers:local .
cd backend
MOMOBOT_WORKER_SMOKE_IMAGE=momobot-private-workers:local \
  PYTHONPATH=. uv run pytest tests/test_workflow_worker_image.py -q
```

Use the selected Docker context for both operations (the test accepts
`MOMOBOT_WORKER_SMOKE_CONTEXT`). The smoke runs a disposable container with
network disabled and a read-only root, real credential-free framework handoffs,
synthetic model responses and no Gateway/server startup. It also verifies the
Gateway retains Python3.12/OpenAI3.22.1. Worker dependencies remain isolated in
Python3.13 environments and Node24; frozen lockfiles are installed and TypeScript
is compiled inside the Linux builder. Adding this image does not enable workflows,
schedules, keys, provider calls or another controller. Stagehand availability
proves packaging only; browser connections and useful artifacts need their own
admission and downstream acceptance. Production installation is a separate step.

CrewAI1.15.23 imports its cloud-trace token manager even when tracing is disabled.
The disposable Python worker installs version-checked hooks before importing
CrewAI: cloud-auth lookup is denied, import/settings paths use a private temporary
directory and trace consent is explicitly disabled there. That directory is
removed on success or error. The real Flow/Crew and existing network/SQLite bans
remain active; no host-home credential or settings directory is read or created.
Regression traps verify real auth/storage access is absent and fail when the guard
is removed. Image labels distinguish Gateway base from worker source revision;
an `unrecorded` worker label is not source-provenance evidence.

Mastra executes its real `Agent.generate` with a standard AI SDK custom provider, one step, no tools/memory/retries. CrewAI executes a real `Flow.kickoff` with one `@start` department step that calls one real `Crew.kickoff`, custom `BaseLLM`, one iteration, no delegation/code/tools/retries and an ephemeral task-output handler. Flow persistence/checkpoint/tracing are disabled; the pinned1.15.23 source hook `_skip_auto_memory` prevents `memory=None` from creating its default LLM-backed Memory. Each final receipt reports actual step/crew/model counts; output must exactly equal the parent response. Python workers deny socket and SQLite connections before framework import, preventing default stores or telemetry transport. Deep Agents uses real `create_deep_agent` with an admitted custom model, bounded recursion and no external memory/store/checkpointer. No model worker receives provider keys. Native LangGraph/gateway owns durable run state, history, continuation, call IDs, schema validation, actual usage and budgets.

The gateway native Responses adapter accepts only server-selected `gpt-6.1-sol` with explicit low/medium/high reasoning, strict JSON schema, finite output ceilings, `store:false`, retries0 and deterministic call IDs. It validates actual framework-expanded input headroom before dispatch, then resolved model, completed status, refusals, original schema and actual input/output tokens. Missing billed cost remainsnull. Failed responses keep known usage via `AdapterError.usage`. Final worker output must equal the native admitted result. Availability does not establish useful output acceptance.

Stagehand observe/extract are actual AI APIs routed through the gateway's metered callback with cache disabled. The shipped capability analyzes validated public text snapshots, with screenshots; it does not expose target-origin scripts, arbitrary code, forms, login or actions. Actual extract uses two model requests (extract and completion assessment). The default runner extracts only the first snapshot so plan/draft/verification can fit the shared6-call run ceiling; up to3pages retain validated text/screenshots. See [PROTOCOL.md](PROTOCOL.md) for exact bounded frames, source/lease restrictions and remote release behavior.

## Fixed extension setup

`node dist/src/extension-setup.js --inspect` is entirely offline. The pinned SDK archive is440798bytes, SHA256`8efc7d171a625cca95c02d02d369b59435fae776cae6c7dd2f6fe72eb19785c0`, at `node_modules/@browserbasehq/stagehand/dist/assets/stagehand-extension.zip`.

An authorized operator can run `node dist/src/extension-setup.js` with the existing server `BROWSERBASE_API_KEY` privately injected. It uploads only this archive, disables retries, creates no session/model call, and GETs the returned extension ID. ID/project/file-name must match before `readback_confirmed:true`; the receipt also includes local SHA256, bytes and SDK version. The provider metadata API does not return archive bytes/checksum, so metadata readback and the local upload hash are separate evidence. On failure inspect the account receipt before another upload; no automatic retry is permitted.

The canonical verified UUID is server-private `MOMOBOT_STAGEHAND_EXTENSION_ID`. It enters Browserbase's session body as top-level `extensionId`; caller request bodies never choose/upload an extension. The per-run receipt records fixed extension and AI mode; its extension participates in new idempotency fingerprints. Existing room-only hashes and renderer defaults are preserved. The worker privately uses the validated creation CDP URL, reads installed extensions with the read-only `Extensions.getExtensions` command, requires exactly one enabled name/version matching the pinned manifest, then attaches through `localBrowser.connect` with that Chrome extension ID. Browserbase upload UUID and Chrome extension ID are distinct. This avoids a second SDK session GET that may lack `connectUrl`, and avoids uploading/installing an unpacked extension or launching Chrome. Pinned SDK close sends `Browser.close` to this service-owned session; the service independently releases it and verifies exact-session terminal readback. Browser sockets/callbacks cannot be resumed from checkpoints. No caller-owned/user browser is accepted.

The gateway supplies the explicit session UUID from its creation receipt separately from the opaque `connectUrl`. Neither adapter nor worker requires a URL query ID or infers a path convention. Both validate the existing exact Browserbase WSS hosts on443 without userinfo/fragment; any query `sessionId` must be unique, nonblank and equal to that receipt. Offline fixtures cover opaque query/path credentials, wrong/duplicate/blank identity rejection before transport, exact custom-renderer UUID handoff, unchanged two-argument room rendering and release readback. Fixture URL shapes are synthetic examples of the official separate-field contract, not claims about observed signed credentials.

The service-owned Stagehand mode sets `keepAlive:true` within the existing180-second TTL because discovery and SDK attach are separate CDP connections. The inspection socket also stays open until SDK attach finishes, then closes exactly once on success or failure. [Browserbase keep-alive documentation](https://docs.browserbase.com/platform/browser/long-sessions/keep-alive) says disconnects end sessions without keep-alive and recommends it for multiple connections; it does not promise only the final connection matters. Ordinary room rendering retains `keepAlive:false`. Every Stagehand job still explicitly releases its one owned session and verifies terminal readback; unknown closure retains the owner reservation through possibleTTL. This policy requires the existing paid plan and does not enable persistent or cross-run browser reuse.

Fixed initialization, snapshot render/capture, observe/extract and cleanup failure codes survive the worker/adapter/service boundary. Specific transport/extension/runtime/timeout codes are preserved; raw exception messages and signed URLs are discarded. Cleanup errors cannot replace an earlier operation failure, and provider closure is independently verified by the service. Live acceptance remains separate from these offline lifecycle checks.

Offline real-extension acceptance:

```sh
MOMOBOT_RUN_HEADLESS_STAGEHAND_SMOKE=1 node --test dist/test/local-stagehand.test.js
```

The first test uses disposable headless Chrome: actual Stagehand requests contain visible synthetic source evidence, its extraction returns the admitted object, a real PNG exceeds1000bytes, and its own browser closes. The second launches another disposable Chrome, attaches through its existing CDP URL, discovers its real pinned extension, captures a real PNG, then verifies the SDK close stops that owned browser. Tests never attach to the user's browser or spend cloud/model credits. Backend tests cover five real framework handoffs, actual one-step CrewAI Flow lifecycle and no SQLite/files, second-call/foreign-identity/output-change rejection, private browser frames/two admitted callbacks/PNG readback, cancellation reap, durable admission cancellation and unchanged room defaults. Live useful output and installed app checks remain separate.

Primary APIs verified2026-09-30: [CrewAI custom BaseLLM](https://docs.crewai.com/v1.15.23/en/learn/custom-llm), [Mastra Agent](https://mastra.ai/reference/agents/agent), [Stagehand official source](https://github.com/browserbase/stagehand), [Browserbase session schema](https://github.com/browserbase/sdk-node/blob/main/src/resources/sessions/sessions.ts), [Browserbase session API](https://docs.browserbase.com/reference/api/create-a-session), [Deep Agents API](https://reference.langchain.com/python/deepagents/graph/create_deep_agent), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
