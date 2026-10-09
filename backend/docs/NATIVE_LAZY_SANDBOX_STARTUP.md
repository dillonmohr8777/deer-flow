# Empty-skill native startup

A lead agent with `skills: []` previously constructed its sandbox provider to
prepare an empty physical skill view, even when its final tools never used a
sandbox. A restricted Docker provider consequently required a reachable Docker
Engine before a native Room or batch-only request could start.

Final lead and subagent assembly now derives a conservative internal proof after
tool authorization, deferred discovery, owner tool ceilings and middleware
composition. Only exact canonical `agent_room_read`, `agent_room_post`,
`approved_agency_phase`, `batch_status`, `cancel_batch` and `present_files` tool
objects qualify, including tools supplied by middleware. A zero-tool child may
also qualify. Skills must be explicitly empty and sandbox initialization lazy.
Inherited/default skills, unknown tools or clones, deferred tools, extension
middleware and any guardrail provider retain the ordinary sandbox path. No agent
configuration or request context can opt into this proof.

Qualified clean runs omit the unused skill projection and sandbox lease/scope
creation. Before and after execution, and around tool calls, inherited sandbox
state (including overwrite/fork wrappers), bindings and network approval payloads
are refused without clearing or releasing another execution's capability. A
task-local provider fence denies transitive provider lookup during admitted native
tool handlers, including cached lookup and `asyncio.to_thread`; its token resets
on error or cancellation. Unknown tool requests cannot use the proof. Empty
skills remain enforced by the existing prompt and tool policy. Native output
externalization continues through owner/thread host outputs without a provider.

This optimization grants no Docker control, shell, sandbox egress, tools, MCP,
owner identity or paid model authority. Ordinary authorization, sandbox network
policy, physical skill isolation and cleanup remain unchanged. Do not create a
long-lived sandbox worker from inside a native handler: child tasks inherit its
provider denial. The existing native batch poller starts at Gateway startup,
outside the handler scope.

`tests/test_sandbox_native_lazy_startup.py` invokes real assembled graphs with an
offline recording model and forbidden provider getters, native artifact and large
Room output paths, the actual child execution fence, inherited state negatives,
unknown/late tool and guardrail negatives, cached lookup and cancellation/task
isolation. It proves source behavior, not a deployed image or live pilot.
