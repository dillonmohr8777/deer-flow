# d11 slice 29: Trash at 390 is paper slips with thumb-reach actions

## Why

Trash was the last project surface that still drew desktop rows at phone width. At 390 it broke four rules:

- Every document was a hairline row, not a paper slip like Agents, Chats, Scheduled tasks and a project's Chats.
- Restore and Delete permanently were 32px text buttons under the row, below the 44px phone floor. Empty trash was 32px too.
- A long file name lost its end to a one-line ellipsis ("keyword-gap-analysis-q3-final-reviewed-by-clie..."). The end of a file name is often the part that tells two versions apart.
- "1 day left" read exactly like "28 days left", in the same muted voice. A document about to be deleted for good had no signal at any width.

Two smaller ones: a document with no recorded origin said "from Unknown project" (DESIGN.md: missing data reads "Not recorded"), and the restore picker loaded behind a spinner and listed projects as bare ghost text.

## What changed

- `trash-view.tsx`:
  - The list takes `pageStyles.slips`, so below 640px each document is a cream-hi slip on the desk with the alternating cut.
  - The name wraps to two lines (`line-clamp-2`, `overflow-wrap:anywhere`), with the full name on hover, at every width.
  - The meta line is "from" the project and the size. The time left moves beside the actions. On phones that is the slip's foot line: time left on the left, Restore at 44px on the right, and the permanent delete as a 44px icon (named "Delete permanently" for assistive tech, still behind its confirmation). On desktop the time left stands just before Restore.
  - Three days or less left is an attention `StatusTag` (brass square, brass-text word).
  - A missing origin says "Project not recorded".
  - Empty trash, Try again and Load more meet the 44px floor on phones. The header is a `<header>`.
  - The restore picker loads with `WorkingState` and lists projects as a ruled list of 44px choices with a folder glyph.
- Locales: `trash.unknownProject` is "Project not recorded" (zh-CN: "来源项目未记录").
- DESIGN.md Phones: a new Trash rule.

## Evidence

`before/` and `after/` each hold `trash-{390,1440}.png`, `trash-picker-{390,1440}.png` (restore of a document whose project is gone) and `trash-empty-{390,1440}.png`. `shots.spec.ts` took them against the mocked API.

| 390x844             | before                 | after                            |
| ------------------- | ---------------------- | -------------------------------- |
| document            | hairline row           | cream-hi slip                    |
| Restore             | 32px                   | 44px                             |
| Delete permanently  | 32px text button       | 44x44 icon, same accessible name |
| Empty trash         | 32px                   | 44px                             |
| long name           | one line, cut          | two lines, whole                 |
| 1 day left          | same as 28 days left   | attention tag                    |
| origin not recorded | "from Unknown project" | "Project not recorded"           |
| picker loading      | spinner                | WorkingState                     |

## Contrast

- Name: ink on cream-hi, 15.47.
- Meta and time left: ink-muted on cream-hi, 8.35.
- Attention word: brass-text on cream-hi, 5.75.
- Delete glyph: danger on cream-hi, 7.11.

No new tokens or hex values.

## Tests

- New e2e test: `trash documents are slips with 44px actions and say when time is short` (ui-polish-mobile.spec.ts). It checks the slip's cream-hi background, that the long name wraps, that Restore, Delete permanently and Empty trash are at least 44px, the attention tone on "1 day left" and its absence on "28 days left", "Project not recorded", and no horizontal overflow. Not run against the old build; its first assertion cannot hold there, since the old row had no background (the slip class was not applied).
- `playwright test ui-polish-mobile project-documents` against a fresh `next build`: 43/43. The project document lifecycle test still restores and purges by the same button names.
- `pnpm test`: 2503/2503 tests pass. `sidecar-delete-gating.dom.test.tsx` still reports the same unhandled fetch rejection earlier slices recorded, with all its tests green.
- `pnpm lint` and `tsc --noEmit`: clean.

## Score: 8/10

Trash now reads like the other record pages on a phone: each document is a slip you can act on with a thumb, its whole name is visible, and the one that is about to go says so.

Not a 9:

- The empty state has no action. DESIGN.md asks for one, but there is no Projects index page to lead to (projects live only in the sidebar). The honest action would open the sidebar sheet at Projects, which needs a small sidebar API.
- Sizes still read "47.1 KiB" (the shared `formatArtifactBytes`). "47 KB" is the house voice, but the formatter is shared with Artifacts and the project shelf, so it should change in one place for all three.
- The lede wraps to a third line at 390 ("30 / days"). That is copy work for the whole header pattern, not this slice.
