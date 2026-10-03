# Scoped workflows

`catalog.py` owns 100 Momentum and 20 personal definitions; `recipes.py` supplies
explicit task instructions/criteria, `examples.py` contains fictional preview data.
Do not replace canonical client facts with those examples or add private records.

`WorkflowEngine(checkpointer).execute(...)` runs a native LangGraph kernel.
Provider/browser/event callbacks are injected: never import `app.*` here.
Checkpoints scope identities and stable worker conversations to owner+run.
Same-run calls serialize on one event loop; Gateway must hold the durable
cross-process admission lease and reserve every deterministic `call_id` before I/O.
Unknown paid attempts cannot be automatically replayed from graph state.

Acceptance requires closed output schema, admitted provenance references, all
independent-review criteria, matching output SHA-256 and no unresolved blockers.
This is a reviewable draft contract, not a semantic truth or publication guarantee.
Budgets stay enforced in callback admission; model-selected role/effort never
raises server limits. All six adapter names still share this bounded controller.
Optional `supervisor=True` adds a distinct plan-review worker before any producer.
Its criterion-complete approval binds the exact plan hash; failures stop drafting.
Keep the mode immutable across checkpoint resume and Gateway idempotent admission.
Six kernel calls maximum in this mode still share the existing Gateway budget.

Core tests: `tests/test_workflow_catalog.py`, `tests/test_workflow_engine.py`.
Gateway tests: `test_workflow_native_runtime.py`, `test_workflow_routes.py`,
`test_workflow_startup.py` cover actual native stores, session/workspace gates and
shared-component lifespan wiring with synthetic credentials/model transport.
`README.md` owns lifecycle, receipt, synthetic-example and operational limits.

`tests/test_workflow_crewai_recovery.py` verifies the agency SOP through an actual
installed isolated CrewAI Flow/Crew, shared SQLite admission/checkpoints and native
SQL journal. Responses remain synthetic; this proves recovery/accounting, not
real SOP quality or new provider execution. The optional test-only
`MOMOBOT_TEST_WORKER_ROOT` selects an existing isolated worker installation; never
use it to override production worker paths.

Native model identity is server selected and checkpoint bound. The default/legacy identity remains OpenAI; an opt-in HAI run must use Low for planner, supervisor plan reviewer, maker and checker and cannot change provider on resume. Keep this package provider-neutral: Gateway owns its protected route, original currency admission and actual model/usage receipts. Synthetic HAI tests do not authorize real dispatch.
