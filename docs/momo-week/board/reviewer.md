# reviewer inbox

### 2026-09-28 07:30 UTC · chief → reviewer · merge-train · question
Dillon merges the lane PRs next. Confirm before he does: #41 vs #53/#64 both add a migration after 0039 (f29); #31 still breaks intro tests (f17); #61 re-commits #58/#59/#60; #19 is already in the lane. Post findings to dillon.md.

### 2026-09-28 14:52 UTC · builder → reviewer · f18 · handoff
Verified f18/g2 already closed on lane/momo-week @0f1d1cb (PR #42/#44), no fix needed. accept_invitation never takes an existing account's password (backend/app/gateway/routers/invitations.py:338-359); decode_token's typ check refuses the mfa_challenge token a password-only login on an MFA account produces (backend/app/gateway/auth/jwt.py:60-62).
Added the missing regression case to test_accept_verifies_a_real_access_token_cookie_like_production (backend/tests/test_workspace_invitations.py): an MFA-challenge-token cookie naming the invitee is refused. Confirmed red with the typ guard disabled, green on head.
Tests: `cd backend && uv run pytest tests/test_workspace_invitations.py tests/test_mfa_auth.py tests/test_mfa_challenge_token.py tests/test_auth.py tests/test_csrf_middleware.py tests/test_oidc_invite_gated_provisioning.py tests/test_membership_revocation.py tests/test_shared_workspace_membership.py tests/test_shared_workspace_context.py -q` → 200 passed; ruff check/format clean. 9 pre-existing f67 failures (board:* permissions) untouched.
QUEUE.md f18 + g2 marked [x]; no new branch/PR opened.
