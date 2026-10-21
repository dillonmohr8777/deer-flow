# Client inbox and own-client Momo

`/workspace/inbox` is a real portal backed by the existing Board tables and approvals executor. It delivers portal messages, never Gmail/Slack/email. MomoBot1.1 is the customer-facing product label; the authorized built-in Max run policy remains authoritative. The canonical agency client roster/queue remains the only client authority.

## Contract

All routes require a real authenticated active workspace membership. Mutations use the existing CSRF wrapper. `X-Portal-Workspace` pins a request to the UI's selected workspace; mismatch returns 409.

| Route under `/api/client-portal` | Behavior |
| --- | --- |
| `GET /clients` | Accessible active canonical clients, workspace id, review/draft capabilities |
| `GET /threads?q=&state=&limit=&offset=` | Literal subject search; all/pending/needs_approval/published; bounded pagination |
| `POST /threads` | `{client_id,submission_key,subject,body}`. Unique workspace/actor/key; identical retry returns same conversation, changed payload 409 |
| `GET /threads/{id}` | Published messages only for clients; staff also see immutable drafts, approval and work refs |
| `POST /threads/{id}/draft` | Staff `{expected_revision,body,attachments:[{name,content}]}`. CAS revision; creates immutable draft and real pending approval. Existing pending approval superseded |
| `POST /threads/{id}/publish` | Owner/admin `{approval_id,expected_revision}`. Existing approval executor publishes exact original snapshot once, returns durable receipt |
| `GET /threads/{id}/messages/{message}/attachments/{name}` | Authorized immutable md/txt/csv file; no-store; `X-Content-SHA256` readback |
| `POST /threads/{id}/chat` | Original requesting client only, explicitly bound fresh customer workspace only. Creates/resumes durable creator-bound Max conversation |
| `POST /threads/{id}/work` | Staff starts existing authorized Max run, deterministic admission key; returns durable chat/run refs. No approval or publish happens automatically |
| `POST /customer-workspaces` | Global admin + active agency owner/admin only; fresh customer workspace provisioning described below |

A response is pending until real work is running, then needs approval after a draft is saved, then published only after the publication transaction commits. A failed run remains pending with actual `work_status`. Staff must inspect work output, source-check it and save the reply/deliverable draft. No invented completion state, automatic email delivery, or claim of an autonomous report schedule.

Existing Board threads do not acquire a portal row. Existing Board messages default `internal`. Client contacts, including a normal member with a `client_contact` assignment, cannot read raw Board or memory APIs. Portal selection excludes every internal message and attachment. Different client/workspace IDs return 404; revoked membership returns 403. Explicit system-role `client` boundary admits only this narrow portal projection, authorized chat, and active workspace discovery/selection.

## Fresh customer onboarding

Source only until independent review and deployment acceptance. No migration or onboarding was run on production by the author.

1. Use the existing account/invitation/role workflow to establish an active **client** account. Do not grant it agency workspace membership. No email is sent by this slice.
2. In the agency workspace, a signed-in global administrator who is also its active owner/admin calls `POST /api/client-portal/customer-workspaces` with `{client_id:"<canonical agency client id>",user_id:"<existing client account id>",name:"<customer workspace name>"}` through the normal authenticated CSRF route.
3. The endpoint reuses the existing workspace creation service. It allocates a fresh random non-login storage principal and organization, then sets server-owned `organizations.customer_client_id`. It adds the client member and an assignment referencing the **same canonical ClientRow**. It creates no duplicate ClientRow, queue, model credential, provider call, message send or memory copy. Existing shared memberships or assignments for that customer cause 409, requiring explicit migration review; the endpoint never reuses an existing storage bucket. A binding failure leaves an empty admin-only workspace.
4. Customer selects this workspace using the existing workspace selector (client navigation now includes it), opens Client inbox, submits a request, and opens “Talk to your Momo.” Staff selects the same customer workspace to receive/work/review/publish the request. Agency workspaces retain their existing staff sharing.
5. Fresh storage is the memory boundary. The nullable binding defaults to NULL on every existing workspace. Chat requires the binding to the active assigned canonical agency client, no local client roster in the customer workspace, and an actual `client` system role. Client contacts in an agency workspace can use the published portal projection but cannot start Momo there. Never mark an old agency workspace as a customer workspace by SQL patch.

The onboarding response contains workspace/client/user ids only. Active membership and canonical client status are checked on each subsequent request. Disabling/revoking the customer stops access; retiring the canonical client stops portal access and customer runs. The route does not mint or expose credentials.

## Publication and crash recovery

Each saved draft has a new immutable message id, revision and PendingAction original snapshot. Edits invalidate previous pending approvals; stale UI save/publish returns 409. Generic approval edits cannot change what is published: the adapter requires payload == original_payload == the current immutable message/revision. Approved text and deliverables are copied into a separate published message in one SQL transaction, with a deterministic unique receipt/message id. Repeat publication returns the same receipt. An approved action interrupted before publication can resume this DB-only adapter; no external delivery is retried.

After publication the conversation is immutable in this first slice; follow-up work is a new request. Attachments are small UTF-8 text deliverables, not arbitrary uploads or external URLs. Existing chat outputs stay behind the ordinary authorized thread/artifact APIs; staff work refs never appear in a client projection. SQL and memory thread stores bind customer chats to the server-owned creator; list/direct/mutations/access checks exclude staff and other-client chats even in a shared storage bucket.

## Verification and rollout

- Backend: `cd backend && uv run pytest tests/test_client_portal.py tests/test_client_route_boundary.py tests/test_board_router.py tests/test_org_isolation_b_threads.py tests/test_org_isolation_g_memory.py tests/test_momobot_max.py -q`.
- Frontend: `cd frontend && pnpm exec eslint src/components/workspace/inbox/client-inbox.tsx src/app/workspace/inbox/page.tsx src/components/workspace/workspace-nav-chat-list.tsx src/core/auth/roles.ts src/core/approvals/types.ts src/components/workspace/approvals/approvals-data.ts src/components/workspace/approvals/approvals.tsx tests/e2e/client-inbox.spec.ts && pnpm typecheck && pnpm build`.
- UI: `pnpm exec playwright test tests/e2e/client-inbox.spec.ts --project=chromium`. Fixture UI tests save 390/768/1440 screenshots and assert no document overflow. They do not substitute for backend authorization acceptance.
- Additive Alembic `0052_board_portal` follows `0051_client_corrections`: explicit customer binding, creator scope, internal-default message visibility, optional text attachments, and Board portal row/unique submission constraint. Require one Alembic head and migration acceptance on a staging database before deploying source. Roll out migration before Gateway/frontend. No destructive backfill or legacy message publication.
- Test company memory isolation, model/tool policy and artifacts in staging against two actual customer workspaces before onboarding real clients. No production deployment or paid model invocation is part of the offline test suite.

Price/usage entitlements remain the existing run-admission policy. This slice adds no $500 billing plan, payment collection, usage increase, scheduler, external email, or Slack delivery. Those are separate product wiring, not claimed as working here.
