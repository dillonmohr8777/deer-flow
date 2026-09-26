### Auth internals (`app/gateway/auth/`)

TOTP MFA (password accounts only): `totp.py` is a stdlib RFC 6238
implementation (no third-party TOTP dependency), verified against the RFC's
own Appendix B test vectors. `mfa_crypto.py` encrypts the stored secret with
a Fernet key derived via HMAC-SHA256 from the existing JWT secret
(`config.py`'s `AUTH_JWT_SECRET` / persisted `.jwt_secret`), so MFA needs no
second deployment secret. `recovery_codes.py` mirrors `pat.py`'s pattern:
raw value shown once, only a SHA-256 hash persisted, `hmac.compare_digest`
matching. Storage is `deerflow.persistence.user_mfa` (migration
`0036_user_mfa`); `jwt.py` also defines the signed, single-use MFA challenge
token (`typ=mfa_challenge`) that `POST /login/local` returns instead of a
session when MFA is enabled, and that `POST /login/mfa` exchanges for one.
Single-use + per-challenge attempt tracking is an in-process dict in
`routers/auth.py` (same per-worker caveat as the existing login IP
throttle); enroll/confirm/disable/login-mfa all also share a per-user
`mfa:{user_id}` bucket reusing that same throttle machinery so brute-forcing
a code cannot get a fresh budget by switching endpoints. Enroll/confirm/
disable require interactive session auth (`require_session_source`), the
same #4849 rule as PAT management and change-password. Audited actions:
`mfa.enabled`, `mfa.disabled`, `mfa.challenge.failed`,
`mfa.recovery_code.used`. Full design: `backend/docs/AUTH_DESIGN.md`.

Google sign-in needs no auth-module code: it is a normal `oidc.py` provider
entry (`config.yaml` -> `auth.oidc.providers.google`), and
`allowed_email_domains` / `auto_create_users` / `require_verified_email`
already apply generically in `user_provisioning.py`. The login page already
renders a button per enabled provider from `GET /api/v1/auth/providers`;
adding Google is a config change plus the Cloud Console steps in
`AUTH_DESIGN.md`, not a frontend change.

Workspace invitations work with it too, as "sign in, then accept".
`POST /invitations/inspect` says only `requires_login` (does the invited email
already have an account); it never says how that account signs in. A new
recipient accepts with a 12+ character, non-common password, which creates
the account. Any existing account, password or SSO, accepts only with a
verified browser session for that exact user (`_authenticated_session_user_id`:
the route is public, so AuthMiddleware stamps nothing and the handler verifies
the `access_token` cookie itself) plus the CSRF double-submit pair, which the
handler checks because the middleware exempts `/accept` for session-less new
recipients. `/accept` never takes an existing account's password: that was a
login that skipped MFA. A failed check rolls back the token reservation, so
the invitation stays usable. `/invite` offers existing invitees "Continue with
<provider>" and "Sign in with password" (`/login?next=%2Finvite`), and new
invitees the password form plus the providers. It reads and removes the
fragment-token stash on load, keeps the token in React state, and re-stashes
`{token, savedAt}` in `sessionStorage` only right before sending the person to
sign in; stashes older than 10 minutes are dropped. The token only ever
travels in `/inspect` and `/accept` request bodies, never in a URL or `next=`.

`auto_create_requires_invitation` (per provider, default false) turns SSO
auto-create into invite-only: a first login creates an account only when the
provider-verified email (case-insensitive) holds a pending invitation (not
consumed, not expired, active shared workspace, issuer still an active owner
or admin: `deerflow.persistence.organizations.invitation_policy`, the same
rule `/inspect` and `/accept` apply). Otherwise it is the same 403 as
`auto_create_users: false`, so logins cannot probe who is invited. Accounts it
created keep signing in after their invitation is used, because the gate only
applies to creating a user.
