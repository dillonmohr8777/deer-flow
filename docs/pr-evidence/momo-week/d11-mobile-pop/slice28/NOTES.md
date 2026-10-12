# d11 slice 28: the New agent chat step names its agent and shows Save

## Why

Slice 27 fixed the name step and left the chat step after Continue. At 390 it broke three rules:

- The phone tab bar sat under the composer. DESIGN.md says that inside a conversation the composer owns the bottom edge and the bar steps aside. The bar only checks the URL, and this step stays on `/workspace/agents/new`, so it never stepped aside.
- Save, the page's one action, was hidden behind a "..." menu. A bordered info banner then had to explain where it was ("from the top-right menu").
- The top bar said "Design your agent" and never named the agent. The name you had just typed showed up only inside the canned bootstrap message.

The saved state was a centred check mark in a rounded-2xl box, with "Agent created!". That box was not paper, and the exclamation mark is not the house voice.

## What changed

- `workspace-tab-bar.tsx`: `claimBottomEdge()` / `useComposerOwnsBottomEdge(active)` let a page whose composer has no conversation URL hide the bar, with ref-counted claims and an idempotent release. The chat step claims the edge, and leaving it (Back to Agents) hands the edge back.
- The top bar now holds: sidebar trigger, then the back arrow (a real link to Agents, 44px on phones), then the builder Momo at 32px (the same new teammate the name step drew), then "New agent" in the eyebrow voice over the agent's name as the h1 (14px semibold, truncates with a title), then **Save agent** as the primary button on the right (44px on phones, "Saving agent..." while requested). Once saved, the button becomes an ok `StatusTag` "Saved".
- The save-hint banner, its localStorage key and the "..." menu are gone.
- The composer placeholder says what to write: "Describe the job this agent does and what done looks like" (it used to reuse the page subtitle, "...and we will shape it together in conversation"). The composer foot clears the home-bar inset now that it owns the edge.
- Saved: a cream-hi sheet, `role="status"`, saying "seo-auditor is in your Agents, ready for its first job." with Start chatting and Back to Agents. They stack full width at 44px on phones and sit side by side on desktop. The header already says Saved, so the sheet does not repeat it.
- Locales: `chatStepEyebrow`, `chatStepPlaceholder`, `chatStepSaved` were added. `agentCreated` now takes `{name}`. The unused `saveHint` and `agents.more` were removed. en-US and zh-CN changed together.
- DESIGN.md Phones: the tab bar rule names the claim, and there is a new "New agent, the chat step" rule.

## Evidence

`before/` has `chat-{390,1440}.png` and `chat-menu-{390,1440}.png` (Save behind the menu). `after/` has `chat-{390,1440}.png` and `chat-saved-{390,1440}.png`. `shots.spec.ts` took them. It mocks the agent name check, and it mocks history so that Save returns a `setup_agent` tool result.

| 390x844     | before                          | after                             |
| ----------- | ------------------------------- | --------------------------------- |
| top bar     | 69px, "Design your agent"       | 61px, "New agent" / seo-auditor   |
| Save        | in a menu (44px "More actions") | 102x44 primary button, in the row |
| tab bar     | under the composer (57px)       | gone, composer at the bottom edge |
| save banner | 66px bordered alert             | gone                              |

## Contrast

- Eyebrow: ink-muted on cream, 7.59.
- Name: ink on cream, 14.07.
- Save: cream-hi on royal (the shared primary).
- Saved tag: ok on cream, 5.57.
- Sheet text: ink on cream-hi, 15.47.

No new pairs.

## Tests

- New e2e test: `the new agent chat step names the agent, shows Save and drops the tab bar` (ui-polish-mobile.spec.ts). It checks the tab bar on the name step and its absence in the chat step, the h1, the eyebrow, that "More actions" is gone, that Save is 44px and inside the gutter in the header row, the placeholder, no overflow, and the bar's return after Back to Agents. On the old page it fails at the h1: the before run recorded h1 "Design your agent", the tab bar present and "More actions" in the header.
- New unit test: `claimBottomEdge` (workspace-tab-bar.test.ts). It checks that two claims hold the edge and that a double release of one claim does not free the other.
- `playwright test ui-polish-mobile agent-chat agent-room agents-feature-disabled` against a fresh `next build`: 67/67.
- `pnpm test`: 2501/2501 tests pass. `sidecar-delete-gating.dom.test.tsx` still reports the same unhandled fetch rejection slice 27 recorded, with all of its tests green.
- `pnpm lint`, `tsc --noEmit`, prettier on touched files: clean.

## Score: 8/10

The step now reads as a conversation with one clear action. The bar names the teammate you are building, and the bottom edge belongs to the composer, as it does in every other chat.

Not a 9:

- Save is disabled while the bootstrap reply streams. The shared 50% royal looks washed out on cream (the same gap slice 27 noted for Continue).
- The shared top-centre "Save requested" toast covers the top bar at 390 for about 4 seconds.
- The bootstrap message is still the engineer-voiced "The new custom agent name is ... SOUL.md". It is model-facing text, so changing it is a product call, not a design run.
