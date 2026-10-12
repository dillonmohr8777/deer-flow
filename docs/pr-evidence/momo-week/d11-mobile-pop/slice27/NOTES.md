# d11 slice 27: New agent heads itself and leads with its form

## Why

At 390 `/workspace/agents/new` was the weakest page left in the workspace:

- The page's own top bar held the h1, which the paper page frame sets in Fraunces at 28 to 36px, so "Design your Agent" wrapped to two lines beside the sidebar trigger and back arrow.
- The name form was centred in the viewport. The field autofocuses, so on a phone the keyboard is up from the first frame; field and Continue sat at 482 to 566 of 844, under a ~336px keyboard.
- Field and Continue were 36px, under the 44px phone floor.
- "Agent" was capitalised mid-sentence, the back control said "Back to Gallery" (there is no Gallery), and the page never said what happens after Continue.

## What changed

- The name step heads itself like Agents: an "Agents" back link (a real link, 44px on phones), the Fraunces h1 "Design your agent" and its lede, all on one left edge in a 672px frame.
- The form is a cream-hi sheet torn off the pad (`paper-torn`), the builder Momo beside a real `<label>` and its hint, then the field, the error, Continue and a dashed perforation above one line on what comes next ("Next, you describe the job in a chat and MomoBot drafts the agent with you. It is saved when you say so.").
- Field and Continue are 44px below 640px; Continue is full width on phones and sized to its word on desktop. The field turns off autocapitalise and autocorrect (names are stored lowercase) and is described by the error when there is one.
- Copy: sentence case, "Back to Agents", placeholder "for example, seo-auditor" (the hint no longer repeats the example). zh-CN changes with en-US.
- DESIGN.md Phones: an autofocusing form leads the page, never centred.
- e2e `a new agent's name field and Continue sit above the phone keyboard` (ui-polish-mobile.spec.ts): h1, focus, 44px floor, both controls end above 844 - 336, back link href, no overflow. Red on the old page (36px controls ending at 518 and 566).

## Evidence

`before/` and `after/` hold `name-{390,1440}.png`, `name-error-{390,1440}.png` and `name-keyboard-390.png` (390x500, the viewport left with the keyboard up). `shots.spec.ts` took them.

| 390x844   | field     | Continue  |
| --------- | --------- | --------- |
| before    | 482 - 518 | 530 - 566 |
| after     | 293 - 337 | 353 - 397 |

## Contrast

No new pairs: ink and ink-muted on cream-hi (15.47, 8.0+), danger on cream-hi for the error, royal button unchanged.

## Tests

- `playwright test ui-polish-mobile agent-chat agent-room agents-feature-disabled` against a fresh `next build`: 66/66
- `pnpm test`: 2500/2500 tests pass; one file (`sidecar-delete-gating.dom.test.tsx`) reports an unhandled fetch rejection with all 3 of its tests green, and does the same on the PR head without this change
- `pnpm lint`, `tsc --noEmit`: clean

## Score: 8/10

The page now reads like every other operate page, the form is where a thumb and a keyboard can reach it, and the copy says what Continue leads to.

Not a 9:

- the disabled Continue is still the shared 50% royal, which reads washed out on cream-hi
- the chat step after Continue keeps its old small top bar and was not touched
- at 1440 the sheet leaves the lower half of the page empty (a single field does not earn more)
