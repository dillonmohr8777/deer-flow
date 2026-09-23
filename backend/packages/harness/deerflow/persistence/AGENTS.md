# Persistence lifecycle

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

# Organization isolation (M3)

Every organization id is `private_organization_id(storage principal)`. A private organization's principal is its owner; a shared workspace's is a password-less storage user that is never a member. Repositories build on three helpers:

- `deerflow.runtime.user_context.resolve_organization_id()` returns the active organization `AuthMiddleware` verified for a session or PAT caller. Add an `organization_id == active` filter beside the user filter only when it is non-null; internal callers, auth-disabled mode and background work get `None` and keep the user filter alone.
- `organizations.resolution.organization_for_write(active_org, parent_org, storage_user)` chooses a new or re-parented row's organization. Pass the parent's already-verified organization (for example from `organization_from_owned_parent`) and the storage principal the row is written under, never the login actor or a request field. A value that disagrees with the storage principal's organization raises `OrganizationMismatchError`, a `LookupError` that routers answer as 404. With neither an active nor a parent organization the row keeps NULL, the quarantine marker.
- `organizations.delegation.OrganizationDelegationRepository` is the authority for internal callers (contract section 4). `grant(...)` requires the owner's active membership at grant time and supersedes the subject's previous active delegation; `revoke(subject_type=..., subject_id=...)` revokes a subject in every organization; `resolve_active_delegation(...)` re-reads status, expiry, the requested scope and the owner's active membership in an active organization on every call, and denies anything missing, ambiguous or failing. It returns the owner's `ActiveOrganization` (role, storage principal), so a launcher can act without another lookup. `is_membership_active(user_id=..., organization_id=...)` is the cheap re-check for open streams and never falls back to the private organization. Subject types are the owning row's snake_case noun (`scheduled_task`, `channel_connection`); scopes are route-permission strings such as `runs:create`.

Tests build on `tests/org_isolation_fixtures.py` (private orgs A, B, C; shared workspace S with its storage user; users a, b, c). Keep fixture organization ids deterministic: `organization_for_write` rejects an id that is not the storage principal's.
