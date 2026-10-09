# Gateway security hardening

Agent/profile and memory CRUD routers use
`authz.resource_permission_dependency("threads")`: GET requires read, DELETE
requires delete, and other mutations require write. This dependency receives the
real HTTP request even when a handler's `request` parameter is a Pydantic body.
Private-workspace PAT route admission and an internal delegation do not bypass
these checks. Run-only scheduled delegations cannot clear memory; channel worker
grants omit delete, so destructive IM memory commands are denied unless the
owner separately reviews that grant. Direct embedded handler calls retain their
caller-owned authorization responsibility.

MCP mutation failures log only the exception class and return generic errors.
Never include remote exception strings or credential-bearing tracebacks in
HTTP responses or logs; known validation errors retain sanitized field details.

