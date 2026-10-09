# d9 dispatch-board, slice 3 (design routine, 2026-09-26)

These notes stand in for the PR #28 body. The GitHub integration got a 403 when it tried to edit the PR or comment on it.

## Why
The before shots of Agent Studio at 1440 showed three problems:
1. **The team and the board disagreed.** Client Operations, whose only run is queued, wore the brass pin and working squares on the team and said "Active run recorded". Its board slip said Queued, with no pin. The hero brain also pulsed for a queued run.
2. **The lead sheet had no live state.** It had neither a word nor a pin while its run was going.
3. **Agent Studio was capped at 960px.** At 1440 that left a 160px bare strip, out of line with the metric strip above it. "Active run recorded" also wrapped to two lines.

## What changed
- **State words match the board.** A running run is pinned and shows the working squares and "Working" in royal. A pending-only run says "Queued" in ink-muted, with no pin and no motion. Otherwise the word is "Idle", or "Live state unknown" when there is no run history. This matches d10 on PR #34.
- **The lead sheet shows its own state.** It is pinned only while its own run is going, and the hero brain pulses only for a running run.
- **Agent Studio is full width.**
- **The fixture has a running specialist.** Revenue now has a running run, and `active_runs` is 3.
- **DESIGN.md has a new rule.** It sets the team's state words and the full-width Studio.

## Checks
- `pnpm rstest run command-center` passes 56/56, including 2 new tests. With `src/` stashed, 5 of the 7 topology tests fail on the old code.
- `tsc --noEmit` is clean.
- `pnpm lint` shows one error, the pre-existing `login-mfa-step.dom.test.tsx:37` (fixed on #49).
- No new colours were added. Royal and ink-muted on cream-hi both measure above 7:1.

## Self-score: 8/10
**What works:** a pin means the same thing everywhere, and each state has one word.

**Still weak:**
- At full width the specialist cards are wide for their content.
- There is quiet space under the lead's count.
- With seven specialists, the last card sits alone in its row.
- The phone shots show a hover fill from the harness pointer, in both the before and after sets.

## Left
- Once #34 lands, route the team state through `AgentAlive`.
- Add the brief and review lanes when the backend records those stages.
- Link the stamp to a named piece of evidence.
