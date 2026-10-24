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
| `POST /customer-workspaces` | Global admin + active agency owner/admin only; fresh existing customer account provisioning described below |
| `POST /customer-workspaces/invitations` | Same authority; atomically creates/reuses the canonical client's dedicated workspace and returns a private client invitation |

A response is pending until real work is running, then needs approval after a draft is saved, then published only after the publication transaction commits. A failed run remains pending with actual `work_status`. Staff must inspect work output, source-check it and save the reply/deliverable draft. No invented completion state, automatic email delivery, or claim of an autonomous report schedule.

Existing Board threads do not acquire a portal row. Existing Board messages default `internal`. Client contacts, including a normal member with a `client_contact` assignment, cannot read raw Board or memory APIs. Portal selection excludes every internal message and attachment. Different client/workspace IDs return 404; revoked membership returns 403. Explicit system-role `client` boundary admits only this narrow portal projection, authorized chat, and active workspace discovery/selection.

## Fresh customer onboarding

Source only until independent review and deployment acceptance. No migration or onboarding was run on production by the author.

1. In the agency workspace, a signed-in global administrator who is also its active owner/admin calls `POST /api/client-portal/customer-workspaces/invitations` with `{client_id:"<canonical agency client id>",email:"customer@example.com",name:"<customer workspace name>"}` through the normal authenticated CSRF route. This supports a new recipient while local public registration remains disabled; it does not alter authentication configuration or send email.
2. One transaction locks the authorized canonical client row, creates a fresh password-less storage principal and dedicated workspace if needed, binds `organizations.customer_client_id`, and issues the existing single-use `client` invitation into **that dedicated workspace**. It reuses the same canonical `ClientRow`; no roster, memory or agency storage bucket is copied. Failures roll back storage, workspace, binding and invitation together. Concurrent requests through either supported provisioner serialize on a real SQL write, including SQLite.
3. The response contains `workspace_id`, `client_id`, and the existing invitation fields (`id`, private bearer `token`, `expires_at`, `email`, `workspace_name`), with `Cache-Control: no-store`. Share/redeem the token through the existing invitation UI and account acceptance flow. No customer joins the agency workspace. Tokens must stay private and must not be pasted into public tickets, logs or source.
4. A retry reuses the dedicated workspace and **rotates** pending `client` links for that workspace and email: older pending links become invalid, and the response contains a fresh token. Accepted/revoked links and other emails/roles are untouched. Raw tokens are never stored, so retries cannot recover the original token. This is workspace idempotency with token rotation, not identical-token replay.
5. Existing-account acceptance still requires the invited account's own authenticated browser session and CSRF pair; new recipients use the existing password or verified SSO flow. Local acceptance and SSO auto-join both create the bound canonical client's `client_contact` assignment and `client` membership. Only an eligible plain `user` system role becomes `client`; an existing `client` keeps that tier. Admin/exec/other staff accounts are rejected before issuing or accepting a dedicated customer invitation. Generic staff invitation role rules remain unchanged. A plain/client SSO account with an eligible dedicated customer invitation applies that client invitation even when a newer member/admin link exists for the same workspace; unrelated and conflicting-role links stay pending, and multiple dedicated customer invitations return 409. All invitation roles lock and refresh the recipient before role/isolation decisions, including concurrent acceptance through different tokens. An already dedicated `client` account cannot accept a different workspace link. The shared `app.gateway.invitation_policy` checks canonical linkage and fresh-contact eligibility at issue and before token reservation: one active dedicated binding, active canonical agency/client, no local customer roster, distinct agency storage, and an issuer still an active global administrator and owner/admin of both workspaces. A conflict returns 409 and rolls back the token, new account or role change, membership and assignment.
6. Existing shared memberships or assignments for another workspace/client return 409, requiring explicit migration review. A conflicting, inactive or inaccessible existing binding is rejected. The legacy `POST /customer-workspaces` with `{client_id,user_id,name}` remains available for an already active `client` account with **no** shared membership or assignment; it binds atomically, grants the same `client` membership and `client_contact` assignment as invitation acceptance, and refuses a second workspace for the same canonical client.

For an existing agency contact, a global administrator who owns/administers the selected agency can explicitly call `POST /api/client-portal/customer-workspaces/migrations` with `{client_id,user_id,name}`. The account must already be active with system role `client`, exactly one matching agency `client_contact` assignment, and exactly one active shared membership, with role `client` in that agency. Staff, multi-client and other-tenant accounts return a conflict without changes. The transaction creates or validates the dedicated binding, moves that assignment, activates dedicated membership and deactivates agency membership. A repeat returns 409; inspect the returned workspace before retrying. Private membership and history remain intact. Shared agency history is never moved or relabeled as one person's history.

Clients can use the workspace picker to return to their own private history. Pre-creator-stamp chats are visible only when their stored owner exactly matches the authenticated actor in that actor's server-validated private storage/organization. Shared and dedicated storage keep the creator gate; ownerless and foreign history remain inaccessible.

After acceptance, staff selects the dedicated customer workspace through the existing workspace picker. The customer can discover only their authorized canonical client through the portal. Own-client chat still requires the explicit dedicated binding and canonical contact assignment; no agent runtime, provider credential, billing plan, scheduler, external send or automatic publication is created by onboarding.

## Publication and crash recovery

Each saved draft has a new immutable message id, revision and PendingAction original snapshot. Edits invalidate previous pending approvals; stale UI save/publish returns 409. Generic approval edits cannot change what is published: the adapter requires payload == original_payload == the current immutable message/revision. Approved text and deliverables are copied into a separate published message in one SQL transaction, with a deterministic unique receipt/message id. Repeat publication returns the same receipt. An approved action interrupted before publication can resume this DB-only adapter; no external delivery is retried.

After publication the conversation is immutable in this first slice; follow-up work is a new request. Attachments are small UTF-8 text deliverables, not arbitrary uploads or external URLs. Existing chat outputs stay behind the ordinary authorized thread/artifact APIs; staff work refs never appear in a client projection. SQL and memory thread stores bind customer chats to the server-owned creator; list/direct/mutations/access checks exclude staff and other-client chats even in a shared storage bucket.

## Workspace migration and legacy visibility

Customer workspace migration is explicit (`POST /api/client-portal/customer-workspaces/migrations`): global + agency admin, one exact source client-contact assignment and one shared client membership. Move the assignment and deactivate source membership atomically; never attribute shared history to a person. Private legacy thread visibility requires exact actor ownership and the server-selected private storage/org; creator scope still holds for shared storage.

## Frontend inbox context

Client inbox (`/workspace/inbox`) staff context consumes the PR316
`client_operating_context.v1` projection only. Include the exact user, workspace,
client and optional request in query identity, pass `X-Portal-Workspace` and
AbortSignal, and reject mismatched response scope. The staff client filter uses
the endpoint's bounded recent requests, with explicit limits and unavailable
domains. Client contacts filter their current portal page and never request or
render staff context. Keep history text plain and attachment descriptors inert.
Key the whole inbox session by user/workspace so compose inputs, submission keys,
drafts and selection reset together; fence mutation/download callbacks after
unmount. Existing links do not create new access or start work. DOM regressions
live in `tests/unit/components/workspace/client-inbox.dom.test.tsx`.

## Verification and rollout

Staff may read `GET /api/client-portal/clients/{client_id}/context`, optionally
selecting `thread_id`. It requires the same selected workspace header as the
inbox. An active owner/admin of that workspace, or an active staff member with
the exact canonical agency `account_manager` assignment, can read it. Client
contacts, inactive or foreign assignments and contributor-only membership
cannot use this endpoint or start staff work.

The `client_operating_context.v1` response contains `workspace_id`, a minimal
`client` identity with source timestamp, bounded `requests.items` plus
`has_more`, and an optional `current_request` with `timeline` and draft IDs and
revision. Timeline entries preserve message ID, author kind, internal/published
visibility, source timestamp and bounded body. Limits and truncation are
explicit: at most 25 request summaries, 40 messages and 24,000 body characters;
the original and newest messages survive truncation. Attachment descriptors
identify portal deliverables only: no attachment body or sandbox file grant is
included. Raw notes, contact identities, other-client and private chat history,
private Brain and project shelves are excluded.

The response's `domains` and `freshness` distinguish this stored portal evidence
from missing dedicated goal, CRM, campaign, meeting and delivery sources. A
request may supply such facts; that is not proof of a connected provider or
complete account history. Read failures are errors rather than empty evidence.
`/work` uses this server-derived context, preserving source references and
marking the text as untrusted evidence. It supports requested internal account
deliverables as well as copy, keeps publication under owner/admin review and
does not claim a suggested task was assigned. A retry returns its original
durable run; continuation/run admission rechecks the actual server portal
binding and current staff authorization. This foundation does not establish
connected workflows or full AM readiness.

The initial `/work` input is a stored snapshot. A later normal chat turn does
not automatically refresh portal messages added after that snapshot. Staff can
read the context endpoint again, but this slice adds no live-context middleware
or per-turn retrieval tool.

### Selected client project evidence

Staff may send `{"project_id":"<exact project id>"}` to `/work`; omitting the
body keeps the existing path. Selection requires an active project owned by
the selected workspace's storage principal and organization, with its explicit
`client_id` matching the request's canonical client. A contact, foreign,
unbound, archived or other-client project is denied before creating a work
chat. Matching display names grant nothing. Project link administration stays
owner/admin-only; choosing an existing authorized link does not change it.

First selection uses the existing durable thread-operation reservation and a
NULL-only membership compare-and-set. It does not move an already selected
project or attach evidence after a work run has started. The reservation ends
before normal run admission. An idempotent retry with the same selection keeps
the original run; requesting another selection returns 409.

Each new bound run, including replay, validates the current staff assignment,
client, selected project, storage and organization before and after checkpoint
preparation. Explicit selected-project resolution failure denies the run rather
than proceeding unassigned. The worker checks again before assembly. Gateway
binds the read capability through its in-process `RunContext`, not serialized
request context. Config, saved run kwargs and checkpoints cannot recreate that
capability; a worker without the host capability gains no extra Max tools.

Only a matching staff client/project capability adds the existing
`list_project_documents`, `read_project_document` and `verify_quote` tools to
that Max run. The global Max and client tool ceilings, MCP/skills and private
Brain policy are unchanged. Each shelf operation rechecks current authority
before reading and before returning successful data, retaining the existing
document/project/owner/organization checks. Revocation or changing the link or
stored selection denies subsequent shelf results. Already issued model input
cannot be recalled; this is not an instantaneous cancellation guarantee.

Project instructions and shelf indexes retain their existing per-run transient
rendering. The initial portal-request snapshot still does not refresh on later
ordinary turns. This feature does not narrow existing Project REST permissions,
prove connected CRM/reporting sources, or establish full AM acceptance.

- Backend: `cd backend && uv run pytest tests/test_customer_workspace_invitations.py tests/test_workspace_invitations.py tests/test_oidc_callback_invite_join.py tests/test_client_portal.py tests/test_client_route_boundary.py tests/test_board_router.py tests/test_org_isolation_b_threads.py tests/test_org_isolation_g_memory.py tests/test_momobot_max.py -q`.
- Frontend: `cd frontend && pnpm exec eslint src/components/workspace/inbox/client-inbox.tsx src/app/workspace/inbox/page.tsx src/components/workspace/workspace-nav-chat-list.tsx src/core/auth/roles.ts src/core/approvals/types.ts src/components/workspace/approvals/approvals-data.ts src/components/workspace/approvals/approvals.tsx tests/e2e/client-inbox.spec.ts && pnpm typecheck && pnpm build`.
- UI: `pnpm exec playwright test tests/e2e/client-inbox.spec.ts --project=chromium`. Fixture UI tests save 390/768/1440 screenshots and assert no document overflow. They do not substitute for backend authorization acceptance.
- Additive Alembic `0052_board_portal` follows `0051_client_corrections`: explicit customer binding, creator scope, internal-default message visibility, optional text attachments, and Board portal row/unique submission constraint. Require one Alembic head and migration acceptance on a staging database before deploying source. Roll out migration before Gateway/frontend. No destructive backfill or legacy message publication.
- Test company memory isolation, model/tool policy and artifacts in staging against two actual customer workspaces before onboarding real clients. No production deployment or paid model invocation is part of the offline test suite.

Price/usage entitlements remain the existing run-admission policy. This slice adds no $500 billing plan, payment collection, usage increase, scheduler, external email, or Slack delivery. Those are separate product wiring, not claimed as working here.
