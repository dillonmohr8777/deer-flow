# Optional packaged workflow workers

The default Gateway image excludes these isolated dependencies. `Dockerfile`
provides an opt-in `workflow-runtime` target on an explicitly reviewed local
`MOMOBOT_GATEWAY_IMAGE`. It adds versioned Python3.13 and Node24 worker runtimes;
never overwrite the Gateway Python3.12 environment or install CrewAI into it.
Source and frozen lockfiles enter through explicit COPY instructions and the
Dockerfile-specific build-context allowlist. No host venv, provider credential,
private receipt, runtime database or generated distribution enters that context.

This image runs the existing Gateway command and adds no service/scheduler.
Owner scope, persistence, budgets, retries and effects remain Gateway-owned.
The offline `backend/scripts/verify_workflow_workers.py` uses synthetic responses
and real installed framework lifecycles. Its opt-in image test runs with network
disabled and a read-only root. Installation/smoke never establishes a production
deployment, paid provider acceptance, useful draft or authenticated browser run.
See `browser-teams/README.md` and `agno-team/AGENTS.md` for worker details.

The CrewAI child installs pinned pre-import auth/storage hooks before its real
Flow/Crew runs. Cloud token lookup is denied; settings use only private temporary
scratch removed when the child returns. Preserve audit traps and the unguarded
negative control in `backend/tests/test_crewai_flow_worker.py`; never read the
operator's Crew cloud credentials or settings to make a disabled trace work.
