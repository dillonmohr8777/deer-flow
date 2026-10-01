---
name: MomoBot Paper
description: Cut paper on a cream desk. Royal blue marks what is selected, ink carries the words, and a hint of brass marks work in progress.
colors:
  cream: "#f2ede3"
  cream-hi: "#fbf8f1"
  cream-lo: "#e9decc"
  kraft: "#d8c3a0"
  ink: "#101e3f"
  ink-muted: "#3a4a6b"
  royal: "#1b4b9e"
  royal-deep: "#14346e"
  focus: "#003da5"
  line: "#8c7a5c"
  brass: "#c8a04a"
  brass-text: "#7a5e18"
  cyan: "#17a9e8"
  cyan-text: "#0a6183"
  ok: "#0a6b4f"
  danger: "#9a2b3c"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "clamp(2.25rem, 4vw, 3.25rem)"
    fontWeight: 700
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "clamp(1.75rem, 1.25rem + 1.2vw, 2.25rem)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Nunito Sans, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Nunito Sans, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.18em"
rounded:
  mark: "1px"
  chip: "2px"
  card: "4px"
  button: "6px"
  sheet: "2px 5px 3px 6px"
spacing:
  gutter-phone: "16px"
  gutter-desktop: "32px"
  container-sm: "576px"
  container-md: "816px"
  container-lg: "1024px"
  touch-min: "44px"
components:
  button-primary:
    backgroundColor: "{colors.royal}"
    textColor: "{colors.cream-hi}"
    rounded: "{rounded.button}"
  sheet:
    backgroundColor: "{colors.cream-hi}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
  dialog:
    backgroundColor: "{colors.cream-hi}"
    shadow: "8px 10px 0 {colors.kraft}"
---

# Design System: MomoBot Paper

MomoBot is Momentum's operating console. The shipped look is the **paper cutout treatment**: cream paper, ink type, royal blue for state and action, and a hint of brass. It is the default for the signed-in workspace (`DEFAULT_APPEARANCE.treatment` in `appearance-preferences.ts`) and for the front door: `/`, `/login` and `/invite` (`FUNNEL_TREATMENT` in `components/momentum/treatment.ts`).

The source of truth is code, not this file:

- `frontend/src/styles/paper.css` holds the tokens, the shell skin, the decoration and the motion layer.
- `tests/unit/paper-tokens.test.ts` recomputes every contrast ratio listed below from that file.
- `frontend/src/styles/fonts.css` holds the type voices.
- `components/workspace/page-body.tsx` holds the shared page states.

The canon is "blue, white, grey, with a hint of gold". Restraint is the craft.

Paper is light only. A dark theme choice keeps the shadcn dark tokens. Other Appearance options (`classic`, `current`, `space`, `future`, `retro`) still exist, but they are opt-in and this file does not describe them.

## Colour

Every token lives under `[data-treatment="paper"]`. Ratios are WCAG contrast, as proven by the unit test.

| Token                | Hex     | Use                                                                    | Ratio             |
| -------------------- | ------- | ---------------------------------------------------------------------- | ----------------- |
| `--paper-cream`      | #f2ede3 | Page canvas, sidebar (with a 5% grain tile)                            | ink 14.07         |
| `--paper-cream-hi`   | #fbf8f1 | Sheets, cards, dialogs, popovers, the selected sidebar row             | ink 15.47         |
| `--paper-cream-lo`   | #e9decc | Hover and quiet fills, secondary buttons, notices                      | ink 12.34         |
| `--paper-kraft`      | #d8c3a0 | Dialog offset shadow, hero scraps                                      | ink 9.56          |
| `--paper-ink`        | #101e3f | Text                                                                   |                   |
| `--paper-ink-muted`  | #3a4a6b | Supporting copy, labels, inactive tabs                                 | 7.59 on cream     |
| `--paper-royal`      | #1b4b9e | Primary actions, selected state, active status                         | 7.07 on cream     |
| `--paper-royal-deep` | #14346e | Hover on primary, the /invite and /login field                         | cream on it 10.49 |
| `--paper-focus`      | #003da5 | Keyboard focus rings only                                              | 8.14              |
| `--paper-line`       | #8c7a5c | Borders, inputs, rules (UI only, never text)                           | 3.56              |
| `--paper-brass-text` | #7a5e18 | A brass word, the attention status                                     | 5.23              |
| `--paper-cyan-text`  | #0a6183 | A cyan word                                                            | 5.90              |
| `--paper-ok`         | #0a6b4f | Verified completion                                                    | 5.57              |
| `--paper-danger`     | #9a2b3c | Real failures and errors only                                          | 6.46              |
| `--paper-brass`      | #c8a04a | **Object only** (2.75): pins, status dots, the Light theme preview dot |                   |
| `--paper-cyan`       | #17a9e8 | **Object only** (2.28)                                                 |                   |

Rules:

- **Colour carries state.** Royal marks the selected or acting thing. Green means verified done. Danger means a real failure. Nothing is coloured for decoration.
- **Brass is a hint.** A brass pin means something is working right now, so it is never a resting ornament. Brass and cyan as _words_ use their `-text` variants.
- **The shell remaps shadcn.** Under paper, paper.css maps `--background`, `--card`, `--primary`, `--border`, `--input`, `--ring`, `--muted-surface`, `--accent` and the sidebar tokens to paper tokens. Components use the semantic tokens (`bg-card`, `border-border`, `text-muted-foreground`), never hard-coded hex.
- **Command Center locals follow paper too.** `command-center.module.css` maps its own palette (`--canvas`, `--surface`, `--surface-blue`, `--ink`, `--line`, `--blue`) to paper tokens under `.root[data-treatment="paper"]`. `--surface-blue` is cream-lo.
- **Focus is always visible.** Focus uses a 2 to 3px `--paper-focus` outline or `--ring` (the global rule in globals.css is 3px with a 2px offset). Never remove an outline without a replacement.

## Type

| Voice      | Token              | Face                           | Where                                                                                             |
| ---------- | ------------------ | ------------------------------ | ------------------------------------------------------------------------------------------------- |
| Heading    | `--m-font-serif`   | Fraunces 700, tracking -0.01em | Page h1 and section h2 on paper pages, dialog titles, Command Center headings and metric numerals |
| Text       | `--m-font-text`    | Nunito Sans                    | Everything else: body, controls, labels, data                                                     |
| Display    | `--m-font-display` | Archivo Black                  | The landing's MomoBot wordmark only                                                               |
| Code       | `--m-font-mono`    | System mono stack              | Code, ids, file names                                                                             |
| Annotation | `--m-font-script`  | Caveat                         | The landing's handwritten aside only                                                              |

Sizes:

- **Command Center h1:** `clamp(2.25rem, 4vw, 3.25rem)`.
- **Page h1** (Agents, Scheduled tasks, Projects and others through `page-body.module.css`): `clamp(1.75rem, 1.25rem + 1.2vw, 2.25rem)`, line-height 1.15.
- **Section titles inside Settings:** 1.125rem semibold `h3`.
- **Body UI text:** 0.875rem with a 1.5rem line-height. Ledes wrap at 62ch.
- **Labels** (sidebar groups, metric names, filter group names): 11px, 700, 0.14 to 0.18em tracking, uppercase, ink-muted.
- **Metric numerals** scale with their cell: `clamp(1.25rem, 20cqi, 3.5rem)`.

Row titles stay Nunito Sans. Fraunces is for headings, never labels, buttons or table data; the Command Center's four big metric numerals are the one exception.

## Shape and depth

- **Radius**
  - Sheets use an uneven `2px 5px 3px 6px`, so they read as cut, not machined.
  - Command Center panels and cards use 4px.
  - Specialist cards, chips and filters use 2px.
  - Primary buttons use 6px.
  - Status marks are 1px squares or circles.
  - Shadcn primitives (inputs, selects, menus) keep the `--radius` scale, base 0.625rem.
- **Depth is print, not glow.**
  - Sheets have a hairline `--paper-line` edge and a 1px ink shadow at 10%.
  - Dialogs are cream-hi sheets with a hard `8px 10px 0` kraft offset.
  - The dialog overlay is ink at 45%.
  - No zero-offset coloured halos.
- **Decoration** (paper.css; every piece is aria-hidden and dropped under `forced-colors`):
  - `.paper-torn` and `.paper-torn-alt` give a 24px torn top edge; alternate them across a run of sheets.
  - `.sheet::after` adds a 5% grain.
  - `.pinned::before` adds a 14px brass pin, which means working.
- **Scraps** (`components/momentum/scraps.tsx`) appear only in the sidebar footer, in `EmptyState`, and in the Momo Daily margins at desktop widths. Never in chat threads, forms, dialogs or dense tables.
- **The blueprint grid** on royal-deep is the /invite and /login field, a landing scrap and the Command Center hero scrap. It is intentional there and nowhere else.

## Motion

Paper motion is a closed list of six items (items 1 to 5 in `@layer paper-motion`, item 6 in `momobot.module.css`):

1. Front-door letters settle in 380ms, with a 40ms stagger.
2. Invite release: the pin lifts and the sheet slides away in 420ms.
3. Working squares tick in `steps(3)` over 1.2s while the work is active.
4. Cards lift 2px on hover over 140ms.
5. The brand signature drifts.
6. Front-door Momo bounces: on `/` and `/login` a Momo film on a cream photo floats 26px and tilts in 3D (rotateX and rotateY) over 2.6s above a ground shadow that shrinks as it rises (`bouncing-momo.tsx`). Transform and opacity only. Approved by Dillon, 2026-09-24.

Items 1, 2 and 5 need both `prefers-reduced-motion: no-preference` and the user's brand-motion setting, which is **off by default**. Item 6 follows the front door's own switch (`useIntroMotion().live`: reduced motion, tab visibility and the Pause motion control). Reduced motion turns every item off, not down; Momo then stands still, slightly tilted, on the film's poster. Nothing moves to fake activity.

## Layout

- **Front door names.** The product leads and the maker signs off apart from it. On `/` the MomoBot name sits top left and "by Momentum" (the unchanged wordmark artwork) sits on a cream tab at the far top right, after Sign in; phones drop the header Sign in because the hero's Enter the workspace goes to the same place. On `/login` the name heads the sheet and the Momentum tab sits in the page's top right corner. In the workspace sidebar the MomoBot name leads the header and the Momentum signature closes the footer, right-aligned. Momo is the focal point: beside the headline or the sheet on wide screens, above them on phones.
- **Front door composition.** Below the hero on `/`, the four capability cards take the left column and a kraft grid "Your team" sheet stands beside them from 64rem: the lead as Dillon Brain (the same art the Command Center draws for the lead) and the five specialists the Agents card names as canon Momo stickers (`public/momentum/momos`), with their names in ink. It rests unpinned and follows the cards on phones. No free-floating kraft scrap behind the cards.
- **Page frame.** Operate pages sit in `WorkspaceContainer`, with a max width of `--container-width-md` (816px) or `-lg` (1024px). Command Center has its own 1560px frame, with 32px gutters on desktop and 16px on phones.
- **Page header.** The h1 and a one-sentence lede sit on the left. One primary action sits on the right and wraps under the lede on phones. The work leads: when a page has records, show them before any create form (Scheduled tasks puts its list first and a "New scheduled task" button jumps to the form).
- **Command Center order.**
  1. Top bar: sidebar trigger, "Command Center", and the workspace scope as a plain label.
  2. Heading: the view name as h1, then the view's own lede (the brand line "Give your ambition a team" belongs to Mission Control only), then the hero crew.
  3. Actions: Start a mission (primary) and Appearance (quiet link).
  4. Tabs: Mission Control, Agent Studio, Jobs, Workflows, Client Spaces, Business Intelligence, Artifact Library. A tab the backend only partly supports carries a Preview tag and a one-line note.
  5. A four-fact strip: Active runs, Recorded runs, Errors & timeouts, Recorded tokens.
  6. The view. Mission Control leads with the **dispatch board** at full width, then the agent team (lead plus specialists; when the team is 900px or wider, the lead stands as a column sheet left of the specialists and says how many it delegates to), then Also in your workspace links, then the footer ("No model calls from this dashboard").
     - The board files each recorded run as a paper slip by its **real** status: On the desk (pending or running), Stamped (success) and Returned (error, timeout or interrupted). Any other status goes to an Unsorted lane with its own word, and that lane appears only when it has slips.
     - Only a running slip carries the brass pin; a queued slip says Queued in ink-muted, because waiting is not acting. A completed slip gets a static, dated ink stamp in ok green, set beside its words so a run of finished work stays short. A failed or timed-out slip has its top right corner folded down along a straight crease, the kraft underside up and its outer edges ragged (the same language as a failed agent), and names the reason in danger. An interrupted slip was stopped, not broken: it keeps its corner and says Interrupted in ink-muted. The Returned lane's rule is danger only while it holds a real failure. There is no brief or review lane until the backend records those stages.
     - The agent team uses the board's words for the same runs: a specialist or the lead with a running run is pinned and says Working in royal beside the three working squares; one whose only live run is pending says Queued in ink-muted, unpinned and still; otherwise Idle. Without run history every agent says "Live state unknown". Agent Studio shows the same team at the frame's full width, so the lead stands as a column there too.
     - Slips open the run's receipt drawer. The board shows the latest page of runs and says so; the full, filterable history stays in the Jobs tab.
- **Selection.** Selecting a run opens its receipt drawer on the right.

## States

Use the shared components in `components/workspace/page-body.tsx`. Do not write one-off state markup.

- **Loading:** `WorkingState`. Three ticking squares plus the word, `role="status"`. No spinner in the middle of content.
- **Empty:** `EmptyState`. A small Momo holding a tool, two scraps, a bold title, **one sentence that says what will appear here**, and **one action** (for example Chats: "No recent chats", then "Conversations you start with the team show up here, newest first", then New chat). Never a bare "nothing here".
- **Error:** `ErrorState`. A red-thread tag, the plain reason, the server detail when there is one, and one next step (Retry or Try again), `role="alert"`.
- **Status:** `StatusTag` puts a word beside a shape, so colour is never the only signal:
  - ok: filled green circle
  - active: filled royal circle
  - idle: hollow circle
  - attention: brass square
  - danger: rotated square
  - unknown: dashed circle
- **Truth before tidiness.**
  - Missing data is unavailable, not zero. Show "Not recorded", "Not priced" or "Unavailable".
  - A failed or pending read never produces an "empty" message. For example, Client Spaces says "no clients" only after a successful empty read.
  - Configured agents are definitions, not running workers.
  - Missing ids in a receipt read as a muted word, not a monospace placeholder.

## Phones

- Below 768px the sidebar becomes a sheet and pages take the mobile shell. The server renders the phone layout from a User-Agent hint, so it does not flash the desktop first.
- **Tab bar.** Below 768px a cream-hi strip at the bottom edge (`workspace-tab-bar.tsx`) carries the daily destinations at thumb reach: Chat, Desk and Board (Desk and Board only where Desk is enabled), Command, then More, which opens the sidebar sheet for everything else. The selected tab is royal with a 3px royal mark on its top edge and `aria-current="page"`; the rest are ink-muted. Tabs are at least 56px tall. Inside a conversation the composer owns the bottom edge, so the bar steps aside; a page whose composer has no conversation URL (the New agent chat step) claims the edge with `useComposerOwnsBottomEdge`. While the bar is on the page `--tab-bar-h` holds its height, and anything sized against the viewport (`WorkspaceContainer`, the chat welcome) subtracts it.
- Gutters are 16px on every page. No horizontal page scroll (pinned by `ui-polish-mobile.spec.ts`).
- Icon buttons have a 44px minimum below 640px (`workspace-mobile.css`, matched on the element so a Tooltip or Sheet trigger wrapped around a button cannot drop it). Command Center controls are 44 to 48px.
- **Chat at phone width.** Every chat control is 44px: the header actions, the message actions and the composer tools. Their rows are pulled out by the button's inset, so the first glyph meets the text edge. Below 768px the thread's Scheduled tasks link folds into the header's Chat actions menu (the Export menu, with an ellipsis), so the title keeps its room.
- **A new chat at thumb reach.** Below 640px the empty thread keeps its composer low, just above the starters and the tab bar, instead of lifting it to the middle of the screen, and the Momo photo grows into the desk above (112px on a short phone, up to 176px). The starters are paper tags cut at 2px, like every chip, and 44px tall on phones. From 640px the composer still lifts toward the middle. The composer is two rows at every width: the field, then the tools with Send at the right edge; only a model picker (a resolved model outside easy mode) takes a second footer row on phones, never an empty button. Its placeholder says what to write, not a greeting ("Describe the job and what done looks like" on a new chat, "Reply, or give the next step" in a thread), in ink-muted at full strength (8.35 on cream-hi; it was 60%, 3.03), never faded. Short phones give way from the top: 660px tall or less drops the Momo, below 375px wide the starters run as one sideways rail, and a phone in landscape (440px tall or less) drops the greeting and the starters so the field stays in view. The composer is named "Message" for assistive tech; its placeholder only says what to write.
- **Who is answering.** In an agent chat each reply turn opens with a byline: the agent's 32px Momo (decorative) and its name in ink, 14px semibold, sitting 12px above the reply it signs. It shows at every width, but it exists for phones, where the header badge is a bare icon without the name. The default chat draws no byline until the lead has a settled identity there.
- Tabs, metric strips and the Settings section list become sideways rails. The active item is scrolled into view, and grid items get `min-width: 0` so a rail scrolls instead of widening its parent.
- The Desk's Agents rows lead with each agent's 40px Momo (canon art where a template has a confident fit, the monogram disc otherwise). Below 640px the face holds a left column and the row folds to three lines: name, then model and next run, then the last run with its receipt.
- Command Center puts the dispatch board before the agent team at every width, in DOM order, so focus order matches reading order. On phones the board's lanes stack, desk first. Below 640px a Stamped lane of more than three slips folds into a pile: the latest three, two paper edges under the third, and a "Show N older stamped slips" toggle, so a batch of finished work never buries the Returned lane. Wider boards show every slip.
- **Paper on the desk.** Below 640px the dispatch board and the agent team drop their panel frame and lie straight on the canvas, as the Desk's sections do, so slips run the full gutter width. At a phone-width team (320 to 439px) the specialists stand as a two-column sticker sheet: a 64px Momo on top, name and state under it, the even column set 14px lower.
- Desk Today results become paper slips below 640px, and the whole slip opens the receipt, so the tap target is the slip rather than a text link. A slip reads top to bottom: the title on up to two lines, its time in ink-muted under it, a failure reason in danger and in full, then a foot line with the state on the left and Open receipt on the right. A failed result folds its top right corner down with the kraft flap, the same fold as a failed dispatch slip; a result that did not fail keeps its corner.
- The Agents roster becomes paper slips below 640px: each agent a cream-hi slip on the desk with its Momo at the 64px sticker size beside the name, and Chat across the slip's foot at 44px with settings beside it. The page scrolls as one, so the header leaves with it. Wider screens keep the hairline roster.
- **Pages scroll inside the body.** Every operate page scrolls in its `WorkspaceBody` (a `ScrollArea`), never the document, so the header and the tab bar keep their edges. Scheduled tasks broke this and ran 1269px past a 390 viewport, with the list painting over the tab bar.
- On Scheduled tasks below 1024px, where the task sheet stacks under the list, tapping a task scrolls its sheet into view (instantly under reduced motion) and focuses the sheet's title. Below 640px its text buttons and every `FilterGroup` toggle meet the 44px floor.
- A pressed `FilterGroup` choice is selected, so it follows the royal rule at every width: royal words on a cream-hi scrap with a 1px royal edge (7.77:1), the same edge a selected slip wears. It is never filled royal, which would read as a primary button, and never kraft.
- Below 640px every `FilterGroup` is a one-row sideways rail (Scheduled tasks, Board, Capability Center), its label first; the cut last choice says there is more. The rail sizes to its column (`contain: inline-size`), never to its choices, so it cannot push a page past the gutter. Scheduled tasks become paper slips on the desk there, the selected slip edged in royal instead of a left stripe.
- **Chats** heads itself like every operate page: the h1 with New chat beside it, a one-line lede, then Recent and Archived and search, all scrolling in the body so the heading leaves. Below 640px each chat is a paper slip on the desk (a cut that alternates slip to slip, the whole slip the link), and search waits for a tap instead of opening the keyboard on arrival. The empty state keeps its own New chat, so the header drops it there. Chats are filed like a ledger under day labels in the eyebrow voice (Pinned, Today, Yesterday, Last 7 days, "Earlier in" the current month, then each older month, with the year only when it differs), and each chat names its time for today or its day otherwise. Below 640px each label carries a hairline to the gutter; wider lists already rule every row, so the label stands alone.
- **Chats before there are chats.** While the list loads, Chats shows `WorkingState` ("Loading your chats"); a failed read is `ErrorState` with the server's reason and Try again (44px on phones), after the read's own retries. Search appears only once there are chats to search, so neither state, nor an empty Recent, offers a field over nothing. An empty Archived is an `EmptyState` that says what waits there and leads Back to Recent chats. Recent and Archived stay, because an empty Recent can still hide archived chats.
- **A project's Chats tab** files its chats exactly as Chats does (the same day labels, the title on up to two lines with the full text on hover, the time today or the day otherwise as a `<time>`, and paper slips below 640px), so one chat reads the same wherever it is listed; its time is never "about 6 hours ago". Below 640px its New chat and Load older chats meet the 44px floor.
- **A project** heads itself on the shared page header: its name as the h1 with no eyebrow (the top bar already says Projects), then one line of lede, the first line of its instructions, which is the brief every chat there starts from (two lines from 640px, the full line on hover), then New chat. With no instructions the lede says where to add them; an archived project says to restore it in Settings to start a new chat, since New chat is gone. Its tabs meet the 44px floor.
- **Workflows** heads itself on the shared page header (the h1 and a one-line lede, Refresh beside it at 44px) and scrolls in its body. Your runs lead, before the catalog, each run with its state as a `StatusTag` word (Running, Queued, Accepted, Not accepted, Failed, Interrupted, Cancelled), its day and time as a `<time>`, and a failure's reason in danger; only a running run is pinned. Below 640px runs and catalog entries are paper slips. A failed read is `ErrorState` with a plain reason and Try again, never a raw code such as `workflow_request_failed`; no runs yet is an `EmptyState` that leads to the catalog.
- **A workflow run reads as a receipt.** Title, state word and framework, then "Started" with a `<time>`. Then four labelled sections in the eyebrow voice: Steps, Result, Evidence, Record. Steps shows each journalled step once, at its latest word (Done, Working, Failed), in plain words ("Check the inputs", "Independent review"). A step still running in a run that has ended says "Stopped here", in danger if the run failed. Detail codes become sentences, and an unknown bare code is dropped. Worker hashes never show. The Result shows text fields as text and string lists as lists, with only nested data as JSON; an unaccepted one is labelled "Result, not accepted". Model ids, evidence references, hashes and the run id sit in the code voice, and the run id goes last, under Record, with attempts, tokens ("at least" when usage is incomplete) and cost ("Unavailable" when not priced). Steps, Result and Record keep a 62ch measure on wide screens, so each state tag stays close to its step.
- **A chosen workflow reads as a brief to fill**, on a cream-hi sheet like its receipt: the category as an eyebrow in words ("Paid media", "SEO", never `paid_media`), the title as a Nunito h3, the summary, and one line on what it reads (the public pages you list, or only your inputs). "Checked before it is accepted" lists the acceptance checks in the open; the steps fold under "How it runs, in N steps" in the receipt's step words, without the research step when it reads no pages. Above the fields one sentence states the facts-only rule once, instead of the catalog's template hint repeated under every field; a field keeps a hint only when it says something of its own (the brief, the source pages and their limit). Every field is required, so required is unmarked and only an optional field says "(optional)" (`aria-required` carries it for assistive tech). Labels keep their acronyms ("Source URLs", "KPIs"), enum choices read as words, and the foot says "Runs on", the per-run limit in plain words, then Run workflow, full width on phones with Fill in sample inputs.
- **Browser research** heads itself on the shared page header (the h1, a one-line lede, the remaining browser minutes, Refresh beside it at 44px) and scrolls in its body. Your captures lead, before the capture form, each with its state as a `StatusTag` word in the board's words (Working, Queued, Captured, Failed, Stopped), its day and time as a `<time>`, and a failure's reason in danger; only a running capture is pinned. Below 640px captures are paper slips. A tapped capture opens as a receipt on a cream-hi sheet under the list, scrolled into view (instantly under reduced motion) with focus on its title: state and start time, then Pages and Record in the eyebrow voice, with minutes "Not recorded" and cost "Not priced" when unknown, and Download evidence only when a page was saved. Every stored or raised Browserbase code reads as a sentence (`browser-research-words.ts`, guarded against the service's raise sites); a failed status read is `ErrorState` with Try again and no form beneath it. Placeholders start "For example," so a hint never reads as a value already typed.
- A scheduled task whose last run failed says so on its row at every width ("Last error:" and the reason in danger, two lines at most), because an enabled task can be failing.
- Scheduled tasks say when in the words a person plans by, at every width: "Today, 11:30 PM", "Tomorrow, 8:50 AM", a weekday within the coming week ("Sat, 2:00 PM"), then the day ("Nov 9, 10:00 AM", the year only when it differs), by calendar day (`formatScheduleTime`). Each is a `<time>` carrying the full date on hover. The selected task is edged in royal at every width, never a left stripe.
- **Trash** files each removed document as a paper slip below 640px: the file name on up to two lines (never cut to one line of a long name), "from" its project and its size, then a foot line with the time left on the left and Restore at 44px on the right, the permanent delete a 44px icon beside it, still behind its confirmation. Wider screens keep the ruled rows, with the time left standing just before the actions. Three days or less left is an attention `StatusTag`, because the document is about to go for good. A document whose origin was never recorded says "Project not recorded". The restore picker is a ruled list of projects at 44px, and it loads with `WorkingState`, not a spinner.
- `EmptyState` art (Momo and its two scraps) stays inside the content box at every width; no scrap crosses the gutter.
- The chat composer keeps its disclaimer clear of the bottom edge with safe-area padding. The background-work control never covers the submit button.
- Dialog headers are left-aligned at every width.
- A form whose field autofocuses (New agent) leads the page under its header, never centred in the viewport: the phone keyboard is up from the first frame and covers the lower half.
- **New agent, the chat step.** The top bar names what is being built: the back arrow, the builder Momo at 32px, "New agent" in the eyebrow voice over the agent's name (the h1, 14px semibold), and Save agent, the page's one action, as the primary button on the right (44px on phones), never behind a "..." menu that a banner has to explain. Once saved the button becomes an ok `StatusTag` (Saved), and the composer gives way to a cream-hi sheet that says where the agent went, with Start chatting and Back to Agents (stacked, full width, 44px on phones).

## Copy

- The product is **MomoBot**; the company is **Momentum**.
- **No em or en dashes** in user-visible copy. Use a colon, a comma or a new sentence.
- Actions are sentence case and name what they do: "New agent", "Sign in", "Start a mission", "New scheduled task".
- No internal identifiers in labels (`lead_agent`, raw status enums). Show "Default agent", "Active", "Prospect".
- Errors name the problem and the recovery.
- Scheduled-task presets are agency routines that draft and cite; none sends, posts or spends on its own.
- Locale strings live in `core/i18n/locales/{en-US,zh-CN,types}.ts` and change together.

## Don't

- **No AI purple or violet** in product UI. No violet gradient stops.
- **No neon glow**, no glassmorphism or decorative blur, and no floating gradient orbs.
- **No three equal cards in a feature row.** No generic same-size card grids for the agent team.
- **No emoji or platform pictograms as identity.** Agents use canon Momo art or the deterministic `MomentumGlyph`.
- **No gradient text**, and no coloured left-border stripes on cards or alerts.
- **No decorative motion or fake progress.** No glow on resting content.
- **No new hex values.** If a colour is missing, it belongs in paper.css with a measured ratio and a test.

## Known drift

This is where code still departs from the rules above, recorded so no one copies it:

- The landing hero heading uses gradient text ending in violet (`momentum-landing.module.css`, `globals.css` violet stops).
- `workspace-appearance.module.css` carries raw hex for its treatment previews.
- `command-center.module.css` keeps a pre-paper local palette on `.root`, which paper overrides.
- `.impeccable/design.json` still describes the retired "Momentum Current" palette.
- Operate pages still use several header patterns and several selected-state styles, One shared header and one selected rule are open follow-ups (pressed filters now follow the royal rule).
