---
name: Momentum Command Center
description: A living blue-white operating current for inspectable agent work.
colors:
  canvas: "#f7fbff"
  surface: "#ffffff"
  surface-blue: "#edf7ff"
  surface-violet: "#f2f0ff"
  ink: "#07172f"
  muted: "#50657b"
  line: "#d2e3f2"
  strong: "#91b7d6"
  blue: "#075bd8"
  blue-deep: "#06439d"
  cyan: "#008fc9"
  cyan-text: "#00668e"
  violet: "#5b3bd8"
  rose: "#c73570"
  green: "#087d62"
  danger: "#b4233e"
  focus: "#003da5"
typography:
  display:
    fontFamily: "Momentum Display, Archivo Black, sans-serif"
    fontSize: "46px"
    fontWeight: 400
    lineHeight: 1.06
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Momentum UI, Nunito Sans, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 900
    lineHeight: 1.25
  body:
    fontFamily: "Momentum UI, Nunito Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Momentum UI, Nunito Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 800
    lineHeight: 1.2
rounded:
  sm: "8px"
  md: "11px"
  lg: "14px"
  card: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  section: "34px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 18px"
  card-agent:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "14px 12px"
  input-search:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 11px"
---

# Design System: Momentum Command Center

## Overview

**Creative North Star: "Momentum Current"**

Momentum is a living blue-white operating surface where language becomes work and work resolves into evidence. White and ice-blue fields carry a controlled current of cobalt, cyan, indigo, and violet; color clarifies source, model activity, state, and selection without inventing progress.

The interface is friendly enough for daily client work and rigorous enough for an operator. Real runs, agents, artifacts, costs, and errors stay legible. Every agent and conversation receives a deterministic authored vector identity, so long histories remain scannable without emoji or platform-dependent pictograms.

**Key Characteristics:**

- White and ice-blue grounds with Momentum cobalt structure and restrained spectral accents.
- A luminous lead-agent source connected to specialist work and execution receipts.
- Deterministic Momentum vector glyphs for agents, conversations, and background work.
- Glow and motion only when a state is live, selected, or actively changing.
- Generated copy uses semantic color to speed reading while preserving long-form legibility.

## Colors

The palette is cool, luminous, and operational: deep navy establishes trust, cobalt carries action, cyan signals motion, violet identifies model intelligence, green verifies completion, and red is reserved for real exceptions.

### Primary

- **Momentum Cobalt** ({colors.blue}): Primary actions, active navigation, selected paths, links, and the dominant authored stroke.
- **Deep Cobalt** ({colors.blue-deep}): High-emphasis labels and darker gradient anchors.

### Secondary

- **Current Cyan** ({colors.cyan}): Live graphical motion and the bright edge of the current.
- **Readable Cyan** ({colors.cyan-text}): Small model metadata and link text on white; Current Cyan remains the graphical accent.
- **Intelligence Violet** ({colors.violet}): Token data, generated-copy hierarchy, and the model-intelligence side of spectral gradients.
- **Conversation Rose** ({colors.rose}): Rare identity variation inside the deterministic glyph system, not a generic alert color.

### Tertiary

- **Verified Green** ({colors.green}): Confirmed completion and enabled state.
- **Exception Red** ({colors.danger}): Failed runs, timeouts, and errors only.
- **Focus Cobalt** ({colors.focus}): Keyboard focus outline only; it is an accessibility signal, not a decorative accent.

### Neutral

- **Current Canvas** ({colors.canvas}): Main application field.
- **Clear Surface** ({colors.surface}): Cards, controls, and readable content planes.
- **Ice Surface** ({colors.surface-blue}): Hover, subtle state, and cool tonal layering.
- **Violet Surface** ({colors.surface-violet}): Quiet model-intelligence emphasis.
- **Current Ink** ({colors.ink}): Default text and high-value numbers.
- **Muted Current** ({colors.muted}): Supporting copy and metadata.
- **Current Line** ({colors.line}): Dividers and low-emphasis borders.
- **Strong Current Line** ({colors.strong}): Inputs, connectors, and stronger boundaries.

### Named Rules

**The Truth Before Glow Rule.** Color, glow, and motion may amplify recorded state; they never manufacture activity, success, cost, or urgency.

**The Spectral Semantics Rule.** Blue means structure, cyan means motion, violet means model intelligence, green means verified completion, and red means a real exception.

## Typography

**Display Font:** Momentum Display / Archivo Black (with sans-serif fallback)
**Body Font:** Momentum UI / Nunito Sans (with system sans fallback)

**Character:** A heavy, compact display voice makes the command surface decisive; rounded Momentum UI text keeps dense operational copy warm and readable. Tabular numerals stabilize changing counts.

### Hierarchy

- **Display** (400, 46px desktop / 36px intermediate / 34px mobile, 1.06): Mission Control and other singular page titles.
- **Headline** (900, 21px, 1.25): Primary sections and major result headings.
- **Title** (900, 17–19px, 1.3): Agent names, run names, and drawer headings.
- **Body** (400, 15px, 1.5): Interface copy and generated responses, normally constrained to a readable measure.
- **Label** (800, 11–14px, 1.2): Tabs, statuses, metadata, controls, and metric labels.

### Named Rules

**The Friendly Density Rule.** Use weight, spacing, and semantic color to make dense information scan quickly; never solve density by shrinking body copy below a comfortable reading size.

## Layout

The Command Center uses a 1560px maximum content frame with 32px desktop gutters and a 34px section rhythm. The first viewport moves from title and mission action to horizontally scrollable navigation, a compact four-fact strip, then a two-column agent/work stream. Below 1100px, the overview becomes one column. At 640px, gutters reduce to 16px, the heading stacks, jobs move before the specialist roster, metrics become a single swipeable rail, specialists become a vertical connected current, and tabs scroll horizontally rather than wrap.

Conversation pages keep generated copy in a readable central measure and anchor the composer at the bottom. On persisted mobile conversations, the background-work control sits above the composer so it never obscures the submit control.

## Elevation & Depth

Depth is cool and diffuse. White surfaces use faint blue ambient shadows; selected cards and the lead-agent source receive stronger cobalt depth. Background auroras and the faceted current provide atmosphere, but zero-offset glow is reserved for live rings and selected paths. Reduced-motion users receive the same hierarchy with all nonessential animation removed.

Operational motion is state-bound: controls transition in 160ms, the desktop live ring resolves over 1.9s, the desktop status pulse runs at 1.8s, and active fetch spinners use 1s. The ambient current is still. Optional brand expression uses a 7-second Current or 8-second Paper cycle with an explicit pause control; it is never an activity signal. Mobile keeps at most one continuous state loop in the Command Center. Reduced-motion removes every loop and transition.

### Named Rules

**The State Earns Light Rule.** Resting content stays clear and quiet; stronger glow belongs only to live, selected, focused, or actively changing state.

## Shapes

Cards use gently rounded 14–16px corners; controls use 8–11px corners. Pills are limited to compact status and account controls. Connector geometry is crisp and deterministic. Authored Momentum glyphs use circles, paths, gradients, and nodes as true vector identity marks—not as illustration substitutes.

## Components

### Buttons

- **Shape:** Compact rounded action controls (11px).
- **Primary:** Cobalt-to-indigo gradient, white text, 12px × 18px padding, and a soft directional shadow.
- **Hover / Focus:** Gradient deepens on hover; keyboard focus receives a 3px Focus Cobalt outline with 3px offset. Controls on deep blue receive a white inner outline.
- **Secondary / Ghost:** Clear or ice-blue surfaces with cobalt text and a Current Line border.

### Cards / Containers

- **Operational panels:** Clear Surface at roughly 93% opacity, 16px radius, Current Line border, and a soft blue ambient shadow.
- **Lead agent:** Deep navy-to-cobalt-to-indigo current with light text and a brighter custom glyph.
- **Specialist cards:** Clear Surface with compact metadata; selection shifts to an ice/violet wash and strengthens the connected path.

### Inputs / Fields

- **Search/select:** Clear Surface, Strong Current Line, 8–9px radius, and compact 9–11px padding.
- **Focus:** Focus Cobalt outline; placeholders remain Muted Current and meet the surrounding tonal system.

### Navigation

- **Top bar:** Authentic Momentum mark, current surface name, and account scope on a translucent ice-white rail.
- **Tabs:** Cobalt active state with a spectral underline; compact horizontal overflow on narrow screens.

### Momentum Glyph

Each seed deterministically chooses one of eight authored paths, six accent colors, twelve rotations, and twenty-five node positions. This yields thousands of stable identities while keeping a shared visual grammar and accessible labels where the glyph carries meaning.

### Generated Copy

Long-form responses keep navy body text. Headings run through a cobalt-indigo gradient; strong text is deep blue, links and emphasis use cyan, list markers and code use violet, and blockquotes receive an ice-blue wash. Dark conversations use a separate high-contrast blue-violet ramp, and forced-colors mode returns gradient headings to solid system text. The color hierarchy is semantic and restrained enough for sustained reading.

### Execution Receipt

Selecting a run opens a right-side evidence drawer with recorded status, model, usage, cost when available, errors, artifacts, and only the controls the runtime truly supports.

## Do's and Don'ts

### Do:

- **Do** drive activity, counts, model names, costs, and status from recorded runtime evidence.
- **Do** use the authentic Momentum mark, self-hosted Momentum type, and deterministic vector glyph system together.
- **Do** preserve loading, error, empty, disabled, hover, keyboard focus, and reduced-motion states.
- **Do** keep generated copy colorful by meaning and readable over long sessions.
- **Do** keep mobile controls clear of the composer and other primary actions.

### Don't:

- **Don't** use emoji, Unicode stand-ins, or platform-dependent pictograms as agent or conversation identity.
- **Don't** add perpetual motion, decorative fake progress, or glow to resting content.
- **Don't** turn unavailable data into zero or configured agents into claims of running workers.
- **Don't** flatten the lead-agent current into a generic same-size card grid.
- **Don't** let spectral styling reduce contrast or become rainbow confetti.

## Personal appearance expansion — September 21, 2026

Dillon requested visible dashboard customization and the dimensional paper
language of the existing Momo film. The incumbent Momentum Current world now
has three personal treatments: **Classic** (still, clear fields), **Current**
(cool dimensional brand planes), and **Paper cutout** (ivory ground, cobalt and
yellow layered brand planes, offset paper framing on stable agent glyphs).
Operational surfaces stay readable and do not rotate. The original wordmark
remains unchanged; the new Momo vector is a film-derived interpretation with
provenance in `frontend/public/momentum/SOURCES.md`.

The logo is the single decorative focal motion, separate from recorded agent
activity. This user-requested exception to the original no-decorative-motion
rule is explicitly opt-in, defaults off, has a visible pause switch, and stops
when offscreen, hidden or reduced motion is active. Classic always stays still.
The shared treatment appears in workspace navigation and the dashboard brand
stage; agent identities receive the same material framing without looping.

Appearance controls expand inline beside Start a mission. Local client-logo
previews use a validated raster file and account-scoped browser storage; the
panel labels that scope and provides a reset. It does not imply shared workspace
branding, a changed expert prompt or a live agent. Existing specialist records
provide the visible name, role, model and runtime state in Mission Control and
Agent Studio.
