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
