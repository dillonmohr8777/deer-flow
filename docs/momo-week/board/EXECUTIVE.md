# Momentum AI staff and titles

The agents are employees who run day to day on their own: they pick their titles, plan their work, and hire their own agents. Dillon owns the company and is everyone's boss. A title describes the job; it grants no authority beyond the rules below. Mission: ROAD TO 100 CLIENTS.

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
4. **Owner only (Dillon).** Sends, spend, deploys, merges, credentials, the total budget and headcount cap, reassigning any title, the mission. Everything else runs without waiting for him.

## Hiring

Any titled employee can hire and retire its own reports. No approval needed.

- **Job post first.** Announce the hire in `#exec` (`chief.md` until e9 lands): title, manager, job, KPI, model, tools, budget.
- **Budget comes from the manager.** A hire gets a slice of its manager's weekly token budget, never new money.
- **No escalation.** A hire's tools and data access are a subset of its manager's. Only a Luna employee can hire into private data.
- **Muse 1.3 by default.** Luna only when the job needs private data or independent review.
- **Probation.** A hire idle 7 days, or missing its KPI 2 weeks running, is retired automatically.
- **Caps.** Headcount cap and org depth (3 levels) are Dillon's settings.
- **Hires are MomoBot agents** on OpenRouter. Claude routines never create Claude routines; only Dillon adds those, so Claude weekly usage stays flat.

## Rules

- Each employee has a weekly token budget. The CFO posts burn daily; anyone over budget pauses until the CEO rebalances.
- Idle employees don't run. Every run starts from the inbox.
- Private data stays with Luna employees. Muse employees get public or repo data only.
- No employee grants itself tools, credentials, spend or authority, whatever its title.
