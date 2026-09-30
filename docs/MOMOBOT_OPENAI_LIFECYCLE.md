# MomoBot hosted agent lifecycle evidence

Prepared in the isolated feature worktree on 2026-09-29; this document does not
assert production deployment or provider billing limits.

## Confirmed regressions and changes

Five new offline tests failed against the previous service before the fixes:
historical completed sessions blocked the fourth task; no rolling owner admission
cap existed; a crash after durable watchdog claim stranded cancellation forever;
a claimed cancellation allowed a newer turn to be submitted; and SDK delegation
participants/message phases disappeared from the app projection.

The service now caps three active sessions and sixteen create/follow-up admissions
per server-verified actor/organization/storage scope over a rolling 24-hour window.
Both limits are checked within the admission transaction. Historical idle/terminal
sessions remain usable; unknown outcomes count. Same-key receipts read existing
work, and cancellation is exempt. No prompt or response text is stored in the
local admission ledger. Usage/cost remains unknown unless provider records supply it.

Expired watchdog claims recover with a 60-second lease and the same deterministic
provider cancellation key. A new input cannot race a claimed cancellation.
Transport success alone does not establish a stopped turn. Existing deadline
tables gain the lease field in a serialized transaction; previously stranded
claims without leases recover. An unknown initial create can be reconciled only
from exact server-created session/owner metadata before cancellation, without
ever resubmitting its paid input. A missing or ambiguous remote match remains
uncertain. These controls provide bounded admissions and best-effort cancellation,
not a dollar/token guarantee when Gateway/provider connectivity fails.

SDK `agent_message` items use `sender_agent_id` and `recipient_agent_id`; their
delegation text is retained. `create_subagent_call.agent_id` identifies the
requester and does not invent a child ID. Message `phase` survives projection;
only nonempty `final_answer` output on the latest completed root turn establishes
final output presence. Commentary and child completion cannot establish it.
Contracts were checked against installed `openai==3.22.1` typed resources and
the parent's actual completed hosted-session record.

## Validation

The offline service, route, released-SDK and strict storage suite passes 35 tests, including rolling expiry,
cross-owner budgets, uncertain admission accounting, cancellation exemption,
restart/lease recovery, stable cancellation keys, legacy database migration,
pending-cancel input fences, unknown-create ownership reconciliation and actual
delegation/phase fields. Ruff check and format checks pass for the changed service
and tests. The passing strict Blockbuster storage test exercises real migration, admission,
owner reads and watchdog storage to detect event-loop filesystem/database work.

The iPhone PWA separately passes eighteen unit/DOM tests and six production-server
Chromium browser tests at 390/768/1440: actual install help, focus return, 44px
controls, reduced motion, installed suppression, actual worker registration and
offline private-data isolation. This is browser automation with iPhone install
signals, not physical-device Safari installation or App Store review.

Run commands from `backend/`:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_openai_agents_service.py tests/test_openai_agents_routes.py tests/test_openai_agents_sdk.py tests/blocking_io/test_openai_agent_storage.py -q
.venv/bin/ruff check app/gateway/openai_agent_service.py tests/test_openai_agents_service.py tests/blocking_io/test_openai_agent_storage.py
.venv/bin/ruff format --check app/gateway/openai_agent_service.py tests/test_openai_agents_service.py tests/blocking_io/test_openai_agent_storage.py
```

From `frontend/`, with the production verification server running on port 3040:

```sh
pnpm exec rstest run pwa
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3040 PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test tests/e2e/pwa.spec.ts --reporter=line --workers=1
```

The app API/runtime contract is [OPENAI_AGENTS_APP.md](../backend/docs/OPENAI_AGENTS_APP.md).
Full repository gates and live deployment/provider evidence are tracked by the
coordinating task; this document records the scoped fixes and checks.
