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
| `--paper-kraft`      | #d8c3a0 | Dialog offset shadow, hero scraps, the pressed filter fill             | ink 9.56          |
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
  - `.pinned::before` adds a 14px brass pin, which means working. Put it on only while the work runs: a Command Center specialist with an active run, a running scheduled task, the /login sheet while a sign-in request is in flight, the /invite sheet while it is being accepted.
  - `.paper-corners` (an aria-hidden span inside a positioned sheet) draws two kraft photo corners over the bottom edge. This is how paper **at rest** is held: the landing's capability cards and the /login and /invite sheets sit in corners, never on a pin.
- **Scraps** (`components/momentum/scraps.tsx`) appear only in the sidebar footer, in `EmptyState`, and in the Momo Daily margins at desktop widths. Never in chat threads, forms, dialogs or dense tables.
- **The blueprint grid** on royal-deep is the /invite and /login field, a landing scrap and the Command Center hero scrap. It is intentional there and nowhere else.

## Motion

Paper motion is a closed list of six items (items 1 to 5 in `@layer paper-motion`, item 6 in `momobot.module.css`):

1. Front-door letters settle in 380ms, with a 40ms stagger.
2. Invite release: the pin placed while the invite was being accepted lifts, and the sheet slides away in 420ms.
3. Working squares tick in `steps(3)` over 1.2s while the work is active.
4. Cards lift 2px on hover over 140ms.
5. The brand signature drifts.
6. Front-door Momo bounces: on `/` and `/login` a Momo film on a cream photo floats 26px and tilts in 3D (rotateX and rotateY) over 2.6s above a ground shadow that shrinks as it rises (`bouncing-momo.tsx`). Transform and opacity only. Approved by Dillon, 2026-09-24.

Items 1, 2 and 5 need both `prefers-reduced-motion: no-preference` and the user's brand-motion setting, which is **off by default**. Item 6 follows the front door's own switch (`useIntroMotion().live`: reduced motion, tab visibility and the Pause motion control). Reduced motion turns every item off, not down; Momo then stands still, slightly tilted, on the film's poster. Nothing moves to fake activity.

## Layout

- **Front door names.** The product leads and the maker signs off apart from it. On `/` the MomoBot name sits top left and "by Momentum" (the unchanged wordmark artwork) sits on a cream tab at the far top right, after Sign in; phones drop the header Sign in because the hero's Enter the workspace goes to the same place. On `/login` the name heads the sheet and the Momentum tab sits in the page's top right corner. In the workspace sidebar the MomoBot name leads the header and the Momentum signature closes the footer, right-aligned. Momo is the focal point: beside the headline or the sheet on wide screens, above them on phones.
- **Page frame.** Operate pages sit in `WorkspaceContainer`, with a max width of `--container-width-md` (816px) or `-lg` (1024px). Command Center has its own 1560px frame, with 32px gutters on desktop and 16px on phones.
- **Page header.** The h1 and a one-sentence lede sit on the left. One primary action sits on the right and wraps under the lede on phones. The work leads: when a page has records, show them before any create form (Scheduled tasks puts its list first and a "New scheduled task" button jumps to the form).
- **Command Center order.**
  1. Top bar: sidebar trigger, "Command Center", and the workspace scope as a plain label.
  2. Heading: the view name as h1, then the view's own lede (the brand line "Give your ambition a team" belongs to Mission Control only), then the hero crew.
  3. Actions: Start a mission (primary) and Appearance (quiet link).
  4. Tabs: Mission Control, Agent Studio, Jobs, Workflows, Client Spaces, Business Intelligence, Artifact Library. A tab the backend only partly supports carries a Preview tag and a one-line note.
  5. A four-fact strip: Active runs, Recorded runs, Errors & timeouts, Recorded tokens.
  6. The view. Mission Control shows the agent team (lead plus specialists) beside Latest assignments, then Also in your workspace links, then the footer ("No model calls from this dashboard").
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
- Gutters are 16px on every page. No horizontal page scroll (pinned by `ui-polish-mobile.spec.ts`).
- Icon buttons have a 44px minimum below 640px (`workspace-mobile.css`). Command Center controls are 44 to 48px.
- Tabs, metric strips and the Settings section list become sideways rails. The active item is scrolled into view, and grid items get `min-width: 0` so a rail scrolls instead of widening its parent.
- Command Center puts Latest assignments before the agent team on phones. It swaps DOM order, not CSS `order`, so focus order matches reading order.
- The chat composer keeps its disclaimer clear of the bottom edge with safe-area padding. The background-work control never covers the submit button.
- Dialog headers are left-aligned at every width.

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
- The Momo Hello film on `/` and `/login` has brass pushpins painted into the artwork itself. They are photo content, not UI state, but they still read as pins; new film art should hold its photos with tape or corners.
- `command-center.module.css` keeps a pre-paper local palette on `.root`, which paper overrides.
- `.impeccable/design.json` still describes the retired "Momentum Current" palette.
- Operate pages still use several header patterns and several selected-state styles, including a kraft fill for pressed filters where the rule says royal. One shared header and one selected rule are open follow-ups.
