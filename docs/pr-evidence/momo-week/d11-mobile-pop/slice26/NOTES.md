# d11 slice 26: pressed filters follow the royal selected rule

The PR comment for this slice got a 403 from the GitHub integration, so these notes go here instead.

## Why

Every pressed `FilterGroup` choice (Scheduled tasks, Board, Capability Center) was a kraft fill with ink text. DESIGN.md says royal marks the selected thing, and it listed the kraft fill as Known drift. The kraft chip also didn't match the selected task slip just below it, which has a royal edge.

## What changed

- **Pressed filters.** In the paper treatment a pressed choice is royal words on a cream-hi scrap with a 1px royal inset edge (`page-body.module.css`). That's the same edge a selected slip has. It isn't filled royal, because a filled chip would look like a second primary button. In forced-colors mode a 2px outline marks the choice. There's no layout shift, and nothing overflows at 390 or 1440.
- **DESIGN.md.** The rule is recorded, kraft no longer lists "the pressed filter fill" as one of its uses, and the Known drift line is updated.
- **e2e.** `filters are one-row rails…` in `ui-polish-mobile.spec.ts` now checks the computed royal text, cream-hi background and royal edge.

## Evidence

- `before/` and `after/` hold `tasks-{390,1440}.png`, `tasks-focus-{390,1440}.png` and `capabilities-{390,1440}.png`.
- `shots.spec.ts` is the script that took them.

## Contrast

Royal on cream-hi is 7.77:1. The unpressed choices are unchanged.

## Tests

- `pnpm exec rstest run page-body paper-tokens`: 23/23
- `playwright test ui-polish-mobile board capability-center scheduled-tasks` against a fresh `next build`: 63/63
- `pnpm lint`: clean
- prettier: clean on the touched files

## Score: 8/10

It closes a named drift item with one rule across three pages, adds no new token, and leaves the primary button as the only filled royal thing on the page.

It isn't a 9 because the other selected styles are still mixed:

- the Capability Center tabs use an ink underline
- the sidebar uses an ink-edged cream-hi row
- the Command Center job rows use a surface-blue fill

## Left for d11

- Board slips, stamps and thumb-reach Board actions at 390. These wait on #51.
- "Command" becomes "CEO" when e14 (#125) lands.
