# OIDC callback host

Moved out of `app/gateway/AGENTS.md` to keep it under its byte budget.

OIDC initiation redirects to the configured callback authority before minting state/PKCE cookies. Compare host and effective callback port, not the internal ASGI scheme behind TLS termination. Never auto-link an existing local owner by email. Regression: `tests/test_oidc_canonical_start.py`.
