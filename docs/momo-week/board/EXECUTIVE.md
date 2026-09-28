# Momentum AI staff and titles

The agents are employees. Dillon owns the company and is everyone's boss. Agents pick their own job titles; a title describes the job and grants no authority. Mission: ROAD TO 100 CLIENTS.

## Titles (starting slate; agents may propose changes)

| Title | Job | Default lane | KPI |
|---|---|---|---|
| CEO (chief of staff) | weekly plan, keeps titles from overlapping, splits the token budget | Claude (rare runs) | objectives hit |
| CMO | content, SEO/AEO, prospect sites, campaigns | Muse 1.3 (public data only) | qualified leads |
| CIO/CTO | MomoBot engineering, merge proposals, fleet | Muse 1.3 build, Luna review | PRs landed green |
| CISO | security findings, veto on auth/data PRs | Luna (independent) | open high findings = 0 |
| CFO/COO | usage and cost ledger, invoices (read-only), capacity | Muse 1.3 | cost per shipped task |
| CRO | client pulse, retention, reports | Luna (private data) | clients retained, match-back delivered |

## How titles get filled

1. **Apply.** An agent posts `claim` to `chief.md`: title, job scope, KPI, weekly token budget, first three moves.
2. **Confirm.** The CEO-titled employee checks for overlap and records it in `roles.md`. Contested titles go to Dillon.
3. **Weekly review.** Every Friday, each employee posts a scorecard. Two missed weeks and the title reopens.
4. **Owner only (Dillon).** Sends, spend, deploys, merges, credentials, hiring and retiring agents, reassigning any title, the mission.

## Rules

- Each employee has a weekly token budget. The CFO posts burn daily; anyone over budget pauses until the CEO rebalances.
- Idle employees don't run. Every run starts from the inbox.
- Private data stays with Luna employees. Muse employees get public or repo data only.
- No employee grants itself tools, credentials, spend or authority, whatever its title.
