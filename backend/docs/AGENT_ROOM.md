# Private Agent Room

Private Agent Room (`routers/agent_room.py`) is gated by
`private_workspace.enabled` and the authenticated system-admin predicate.
Its read/post routes still require thread permissions and always scope by
the actual actor's user id, never request fields or a shared workspace's
storage principal. Disabled rooms/non-admins return 404; unavailable room
persistence returns 503. The Desk capability uses the same admin predicate.
The runtime initializes `AgentRoomRepository` only with the existing shared
session factory. Preserve the owner-private room when integrating standby
code; do not copy unrelated live module contents or runtime configuration.

The deployed room0040 history and lane0046 history meet at the no-DDL0047 merge; preserve both shipped parent edges. The private owner room remains distinct from the organization client Board. Code publication, runtime installation and actual agency execution require separate evidence.

## Browser account transitions

Room GET/POST accept optional `X-Expected-User-Id`. Compare it to the actual
authenticated actor's `User.id` before resolving the Room repository or reading
/writing rows; mismatch (including an empty supplied header) returns 409. The
header is a stale-browser fence, never authorization or an organization/storage
identity. No-header callers retain their existing permissions and cookie-derived
owner scope. Private-instance/admin admission and PAT permission rules remain
unchanged. New frontend transport sends its captured actual owner; deploy the
matching Gateway fence before serving that frontend.

Frontend query/access/mutation keys are owner-bound and require confirmed private
access. Auth loading/sign-out masks prior cache, cancelled/late reads and old
post settlements cannot populate a new owner's feed, and composer drafts bind to
the owner who typed them. Tests exercise the real AuthProvider/preferences
lifecycle and actual SQLite/AuthMiddleware route; transport retains credentials
and CSRF and never retries an account-change refusal automatically.
