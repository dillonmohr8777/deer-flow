# LangGraph Studio auth

Moved from `backend/app/gateway/AGENTS.md` to keep that file under its byte budget. The rules are unchanged.

Standalone local LangGraph Studio is recognized only through the upstream
`Auth.types.StudioUser` principal type, never by its reusable identity string.
The type is resolved once at import; an older SDK without it degrades to normal
owner scoping.
For that principal's assistant reads/searches, `langgraph_auth.add_owner_filter`
selects genuine server-registered assistants plus assistants owned by Studio;
all other resources remain owner-scoped. Assistant create/update handlers make
both `user_id` and `created_by=user` server-owned, because LangGraph gives
`created_by=system` privileged ownership semantics during run creation. The
custom application module in `langgraph_studio.py` is imported before the
locked in-memory runtime lifespan. At that pre-runtime boundary it derives
genuine system assistant IDs from the CLI-provided graph registry, removes
their persisted active/version rows so graph registration recreates them, and
demotes every other legacy `created_by=system` marker in both active assistants
and version history. This must happen before runtime 0.30.0 loads and purges
system-marked rows; a user application lifespan is too late. LangGraph executes
this file-backed custom app without first registering its module in
`sys.modules`; keep its annotations eager so dataclass processing remains
compatible with that loader, and preserve the direct file-loader regression
test. An empty graph registry or absent persistence file is a no-op, while
persistence parse/write errors fail startup closed. The harness requires
in-memory runtime 0.30.0 or newer, and a persisted store containing no
expected registered assistant row emits a drift warning so changes to
LangGraph's internal persistence contract are observable. With current
create/update writes and all legacy versions sanitized, ordinary
owner-scoped assistant version selection remains enabled.
