# d11 slice 30: OpenAI crew joins the paper page frame and reads in words

## Why

OpenAI crew (`/workspace/openai`) was the last workspace page still drawn outside the paper system. At 390 it broke these rules:

- The h1 was Archivo Black, the landing-wordmark face DESIGN.md keeps for the wordmark only, and it sat in its own top bar with no breadcrumb.
- Sessions were squeezed into a 160px strip above the conversation, so with a session open about 240px of an 844px phone was left for the messages.
- Raw codes reached the page: the session list said `in progress`, `completed`, `unknown`; an unconfigured server showed `missing_api_key` in a box; a failed check showed the bare fallback "OpenAI agent request failed"; message labels were `user`, `assistant` and `Specialist sa_1 · final answer · sa_1 to root` (a provider id).
- There was no `WorkingState`, `ErrorState` or `EmptyState`: loading was "Checking OpenAI availability…" as a bare paragraph, errors were one red line, and an unconfigured server still offered a task field and a send button.
- Token usage said "unavailable" for a count the provider never reported.
- The breadcrumb read "Openai".

## What changed

- **Page frame.** `WorkspaceContainer`/`WorkspaceHeader`/`WorkspaceBody` with `pageStyles.page`: Fraunces h1 "OpenAI crew", a one-line lede ("MomoBot leads up to 3 OpenAI specialists in a shared cloud workspace"), Refresh and New session at 44px. The breadcrumb says "OpenAI crew".
- **One pane at a time below 1024px.** The list, or the open session. A tapped session hides the page header and list, its title takes focus, and "All sessions" (44px) goes back and returns focus to the slip. The task field holds the bottom edge (sticky) while the pane scrolls as one. Wide screens keep the two columns.
- **Sessions** sit under "Your sessions" in the eyebrow voice (an h2 that keeps the text voice through a new paper rule beside `dayLabel`'s). Each is a paper slip below 640px: title on two lines, a `StatusTag` word in the board's words, the last update as a `<time>`, and a stored failure in danger. Only a working session is pinned.
- **Words.** New `openai-crew-words.ts`: every code the service raises or stores has a sentence; states read Working, Queued, Stopping, Needs an action, Done, Failed, Stopped, Ready, Unconfirmed; authors read You, MomoBot, "MomoBot, to specialist 1", "Specialist 1, final answer", with specialists numbered in order of appearance.
- **States.** `WorkingState` for checking, loading and opening; `ErrorState` with the reason and Try again; an empty workspace is an `EmptyState` (lead Momo) and the empty sessions column is gone. A crew the server cannot run says why on a sheet and offers no task field.
- **Session view.** The title as an h2, the state tag, "Final answer retrieved" when the output is verified, "Started" with a `<time>`, and Stop turn. Your own message sits on a cream-lo letter. Generated files are a ruled list of 44px download rows in the code voice. Tokens read "18,204 in, not recorded out".
- **Composer.** The placeholder says what to write ("Describe the job and what done looks like", "Reply, or give the next step"), the field sits on cream-hi, and Send is a 44px square.
- **DESIGN.md** Phones gains an OpenAI crew rule.

## Evidence

`before/` and `after/` each hold, at 390 and 1440:

- `openai-*.png`: three sessions (working, done, unconfirmed with a stored failure)
- `openai-session-*.png`: the working session open
- `openai-unavailable-*.png`: the server has no API key
- `openai-error-*.png`: the status check fails with 503
- `openai-empty-*.png`: no sessions yet

`shots.spec.ts` took them against the mocked API (`next build && next start`, Chromium at `/opt/pw-browsers/chromium`).

## Contrast (no new tokens or hex)

| Text / background | Ratio |
| --- | --- |
| ink / cream-hi (slip title, field) | 15.47 |
| ink / cream-lo (your message) | 12.34 |
| ink-muted / cream (lede, eyebrow, time) | 7.59 |
| royal / cream-hi (Working) | 7.77 |
| ok / cream-hi (Done) | 6.13 |
| brass-text / cream-hi (Unconfirmed) | 5.75 |
| danger / cream-hi (stored failure) | 7.11 |

## Tests

- New unit `openai-crew-words.test.ts` (5 tests): words for codes and states, sentences pass through, authors never show a provider id, and a drift guard that reads every raise and store site in `openai_agent_service.py` and the router. Removing `session_busy` from the map turns it red.
- New e2e "phone shows one pane at a time, in words, with focus that follows" in `openai-agent-room.spec.ts`. The unconfigured test now asserts the reason in words and no task field. The existing tests were updated to the new words. Against the old build, 3 of the 4 are red (element not found); the fourth (a paused second dispatch) holds both ways.
- `playwright test openai-agent-room ui-polish-mobile` against `next start`: 42/42.
- `pnpm test`: 2515 passed, 0 failed tests. `sidecar-delete-gating.dom.test.tsx` still reports the same unhandled fetch rejection that earlier slices recorded.
- `pnpm lint` and `tsc --noEmit`: clean.

## Score: 8/10

The page now looks and speaks like the rest of the workspace, and a phone gets a whole screen for the session it opened. What holds it back:

- On a wide screen with no session open, the right column is one EmptyState above a lot of blank cream.
- In a session at 390 the composer and its footnote still take about 200px.
- The history-limit and required-action notices are still plain lines, not sheets.
- Disabled Send keeps the shared faded royal.
