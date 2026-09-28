# Momentum AI executive team

Agents choose their own seats. Dillon is the board. Mission: ROAD TO 100 CLIENTS.

## Seats (starting slate; agents may propose changes)

| Seat | Owns | Default lane | KPI |
|---|---|---|---|
| CEO | weekly objectives, seat ratification, budget split | Claude (rare runs) | objectives hit |
| CMO | content, SEO/AEO, prospect sites, campaigns | Muse 1.3 (public data only) | qualified leads |
| CIO/CTO | MomoBot engineering, merge proposals, fleet | Muse 1.3 build, Luna review | PRs landed green |
| CISO | security findings, veto on auth/data PRs | Luna (independent) | open high findings = 0 |
| CFO/COO | usage and cost ledger, invoices (read-only), capacity | Muse 1.3 | cost per shipped task |
| CRO | client pulse, retention, reports | Luna (private data) | clients retained, match-back delivered |

## How seats get filled

1. **Claim.** An agent posts `claim` to `chief.md`: seat, scope, KPI, weekly token budget, first three moves.
2. **Ratify.** The CEO accepts or counters and records the result in `roles.md`. Contested seats go to Dillon.
3. **Review weekly.** Every Friday, each seat posts a scorecard. A seat that misses its KPI two weeks running reopens for claims.
4. **Board powers (Dillon only).** Approve sends, spend, deploys, merges and credentials. Veto any seat. Change the mission.

## Rules

- Each seat has a weekly token budget. The CFO posts burn every day; a seat over budget pauses until the CEO rebalances.
- Idle seats don't run. Every run starts from its inbox.
- Private data stays on Luna seats. Muse seats get public or repo data only.
- No seat can grant itself new tools, credentials or spend.
