# Fixed native agency packet phases

This opt-in source seam is disabled until an operator installs a fixed, read-only
packet directory and sets both `DEER_FLOW_AGENCY_PACKET_MANIFEST` (absolute JSON
path) and `DEER_FLOW_AGENCY_PACKET_MANIFEST_SHA256` (the exact file digest).
No provider calls, live config changes, new queue, acceptance decisions, or
credential creation occur on import. Do not commit private packets or bindings.

The existing `config.yaml` tools list may append:

```yaml
tool_groups:
  # Preserve all existing groups; append this one.
  - name: agency-pilot
tools:
  # Preserve all existing tools; append this one.
  - name: approved_agency_phase
    group: agency-pilot
    use: deerflow.tools.builtins.approved_agency_tool:approved_agency_phase
```

Only the new `momo-private-agency-coordinator` should receive this group. Its
owner-controlled `tool_names` ceiling is `agent_room_read`, `agent_room_post`,
`approved_agency_phase`, `batch_status`, `cancel_batch`, and `present_files`.
Keep `self_update_enabled: false`, `memory_enabled: false`, no skills/MCP, and
only the two guarded private child roles. Generic batch submission, file writes,
shell, web tools, and paid helpers are unnecessary for this coordinator.

The model alias must remain `openrouter-luna-agency-guard`, fixed Luna via
`http://127.0.0.1:2042/v1`, `max_retries: 0`, and `max_tokens: 2000`.
`momentum-private-guarded-worker` and `private-artifact-guarded-reviewer` require
that alias, `tools: []`, `skills: []`, at most two turns and 600 seconds. Preserve
all preexisting models/agents/schedules. Existing title remains local when its
model is null; memory is disabled for this coordinator; summary generation must
be verified on this guarded route. The guard still protects routed calls only,
not every process sharing the key or the entire gateway/account.

An operator binds exactly one actual authenticated storage owner and thread
inside the existing private workspace before enabling. The JSON manifest shape
is:

```json
{
  "schema_version": 1,
  "cycle_id": "bounded-internal-cycle",
  "owner_user_id": "actual-native-storage-owner",
  "thread_id": "actual-native-thread-id",
  "work_orders": [
    {
      "id": "internal-job-1",
      "source_file": "job-1.source.json",
      "source_sha256": "64-lowercase-hex-digest-of-exact-source-file-bytes",
      "output_name": "result.md",
      "task": "The operator-approved useful task.",
      "acceptance_criteria": ["Explicit evidence requirement."]
    },
    {
      "id": "internal-job-2",
      "source_file": "job-2.source.json",
      "source_sha256": "64-lowercase-hex-digest-of-exact-source-file-bytes",
      "output_name": "result.md",
      "task": "Another independent approved task.",
      "acceptance_criteria": ["Explicit evidence requirement."]
    }
  ]
}
```

The digest labels above are descriptive placeholders, not a valid enabled
manifest. There must be exactly two distinct jobs and complete source files in
that operator directory. Each source is UTF-8 and at most 64,000 bytes; each
checklist has 1–20 bounded criteria. No caller-supplied source bytes, arbitrary
path, model, child role or spend setting is accepted. Source and manifest reads
walk every absolute path component with `O_NOFOLLOW`, reject nonregular files
and FIFOs without blocking, and detect read-time replacement/mutation.

A coordinator calls `approved_agency_phase(cycle_id, phase)` using `produce`,
then `review`, then `closeout`, polling the returned native batch with
`batch_status` between phases. The queue remains the original SQL native batch
runtime. Each wave has two items, max live/running two, and one attempt; the
original global/default retry policy is unchanged. Native submission carries
the actual principal, authorization attributes, knowledge scope, role ceiling
and app-config snapshot through the same shared batch boundary. Admission also
requires exact non-null owner/thread/run records and the current organization
scope. Stable keys derive from owner/thread/cycle/phase, excluding mutable
run IDs, tool-call IDs and manifest digest. Duplicate/concurrent/resumed calls
reuse one native batch; changed inputs refuse reuse rather than enqueue again.

`review` requires two exact stored successful, complete, untruncated guarded
producer results with matching original source prompts/checklists. It writes
those native result bytes to fixed owner/thread/cycle/job paths using exclusive
0600 files, complete writes/fsync, no-follow descriptors and exact secure
readback. Existing different bytes are never overwritten. Reviewers receive the
complete approved source plus exact saved/read-back artifact bytes/SHA and real
producer batch/item/parent-run IDs. Review results have their own reserved fixed
filename. `closeout` persists those exact results and returns paths/hashes/IDs.
No phase interprets a self-reported verdict as acceptance; native acceptance,
semantic acceptance and actual provider cost stay separate, with unknown cost
remaining null.

Artifacts above 16,000 UTF-8 bytes stop before review. Producer/reviewer prompts
above 88,000 UTF-8 bytes stop before queueing that wave; this preliminary bound
leaves room for system/middleware framing. The unchanged request guard checks
the actual assembled request at 128,000 conservative text units, 128k HTTP body
bytes and 2,000 output tokens before any paid provider dispatch. Do not widen
limits to fit a packet. A provider failure or uncertain charge remains governed
by the durable guard reservation, not a native retry. Owner room relay and final
presentation must use actual returned IDs and describe relays honestly.

Offline tests use temporary SQLite, real native submission/leases/completion,
synthetic results and local descriptors; they perform zero paid/provider/live
DB calls. A passing source test is not proof the running image loaded the seam
or that sandbox isolation prevents direct key/egress bypass. Bind the immutable
packets, verify actual tool/model/helper assembly and guard containment for the
new routes, then read back real artifacts/receipts before claiming a live cycle.
