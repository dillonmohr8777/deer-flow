### Auth internals (`app/gateway/auth/`)

TOTP MFA (password accounts only): `totp.py` is a stdlib RFC 6238
implementation (no third-party TOTP dependency), verified against the RFC's
own Appendix B test vectors. `mfa_crypto.py` encrypts the stored secret with
a Fernet key derived via HMAC-SHA256 from the existing JWT secret
(`config.py`'s `AUTH_JWT_SECRET` / persisted `.jwt_secret`), so MFA needs no
second deployment secret. `recovery_codes.py` mirrors `pat.py`'s pattern:
raw value shown once, only a SHA-256 hash persisted, `hmac.compare_digest`
matching. Storage is `deerflow.persistence.user_mfa` (migration
`0035_user_mfa`); `jwt.py` also defines the signed, single-use MFA challenge
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
