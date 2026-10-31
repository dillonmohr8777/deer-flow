# Northwind actual system implementation

Scope: one authenticated MomoBot extension for Hillsborough placement operations. Existing prototype and strategy owner remains unchanged. Synthetic-only acceptance; no sends or billing.

| Step | Owner | Output | Acceptance written before build |
| --- | --- | --- | --- |
| 1 | Parent | SYSTEM-DESIGN.md | Concrete data ownership, states, provider contracts, permissions, deployment and failure handling; no invented live connections |
| 2 | Implementation owner | Supported extension + durable store | Persistence/restart, identity isolation, duplicate handling, sourced availability, suppression and fee tests pass |
| 3 | Parent | Dashboard | Real API calls; readable at 390px; no overflow; errors and empty states visible; no fake live metrics |
| 4 | Independent Claude API reviewer | Review receipt | Verify findings against code; resolve every material finding |
| 5 | Parent | Git commit + draft PR | Diff check, package checks, test receipts and explicit remaining account acceptance |

Resource choice: sparse worktree, no Docker rebuild or dependency installation. PC considered; this first build needs the local MomoBot extension contracts, so bounded tests stay here. Lumen semantic_search was not exposed in the current callable tool inventory; known source paths used instead.
