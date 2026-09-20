---
name: Momentum Command Center
description: An inspectable paper-and-ink operating console for real agent work.
colors:
  paper: "#fbf8f4"
  panel: "#f0ece5"
  ink: "#14181b"
  muted: "#636465"
  line: "#dcd6cc"
  strong: "#8e8578"
  blue: "#155e86"
  deep: "#0e1417"
  signal: "#e27113"
  signal-ink: "#a35309"
typography:
  display:
    fontFamily: "Momentum Display, Archivo Black, system-ui, sans-serif"
    fontSize: "clamp(28px, 3vw, 44px)"
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Momentum UI, Nunito Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Momentum UI, Nunito Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.2
rounded:
  sm: "5px"
  md: "7px"
  lg: "8px"
  xl: "10px"
  card: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  section: "34px"
components:
  button-primary:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.lg}"
    padding: "12px 17px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.blue}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  card-agent:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: "14px 10px"
  input-search:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
---

# Design System: Momentum Command Center

## Overview

**Creative North Star: "The Operational Ledger"**

Momentum is rendered as a paper-and-ink control register: warm paper, crisp rules, compact records, and a single deep lead-agent module. The interface keeps actual assignments and account-scoped run facts in view, using blue for navigation and state and restrained orange for deliberate action. Authentic Momentum branding, Nunito Sans UI text, and Archivo Black headings establish the voice.

The system is dense but legible. It favors visible source scope, bounded lists, keyboard-accessible controls, and honest loading/error/empty states over decorative metrics or simulated activity.

**Key Characteristics:**
- Warm paper canvas with ink typography and ruled dividers.
- Deep lead-agent card connected to a compact specialist roster.
- Blue state/navigation signal; orange reserved for primary action.
- Tonal layering and borders instead of decorative shadows.

## Colors

The palette is a warm neutral register punctuated by a cool operational blue and a scarce orange action signal.

### Primary
- **Momentum Blue** ({colors.blue}): Links, active tabs, enabled states, icons, charts, and focus-adjacent affordances.
- **Signal Orange** ({colors.signal}): Start-a-mission actions and small intentional action accents.

### Neutral
- **Momentum Paper** ({colors.paper}): Main canvas and drawer surfaces.
- **Panel Beige** ({colors.panel}): Hover rows, notices, icon wells, and secondary tonal surfaces.
- **Ink** ({colors.ink}): Default text and metrics.
- **Deep Ink** ({colors.deep}): Lead-agent module and high-contrast anchor.
- **Muted Ink** ({colors.muted}): Supporting copy, metadata, and labels.
- **Rule Gray** ({colors.line}): Primary dividers and table rules.
- **Strong Rule** ({colors.strong}): Input borders, secondary outlines, and connector lines.
- **Signal Ink** ({colors.signal-ink}): Light-surface signal text and focus outline.

### Named Rules
**The Evidence-First Rule.** Counters and activity represent recorded workspace facts; never style invented progress or revenue as a KPI.

## Typography

**Display Font:** Momentum Display / Archivo Black (with system sans fallback)
**Body Font:** Momentum UI / Nunito Sans (with system sans fallback)

**Character:** Heavy, compact display headlines contrast with friendly, highly readable UI copy. Labels and metadata stay small and quiet so operational records remain primary.

### Hierarchy
- **Display** (400, `clamp(28px, 3vw, 44px)`, 1.08): Mission Control page title.
- **Headline** (800, 20px, 1.25): Section names such as Your agent team and Latest assignments.
- **Title** (800, 17–19px): Agent names, notices, and detail headings.
- **Body** (400, 15px, 1.5): Default interface copy.
- **Label** (700–800, 11–14px): Tabs, metrics labels, statuses, and controls.

### Named Rules
**The Register Hierarchy Rule.** Use Archivo Black only for the main display title; keep operational labels in Momentum UI with compact numeric alignment.

## Layout

The desktop frame uses a branded top bar with 32px horizontal padding, a centered content column capped at 1560px, and 32px content gutters. Mission Control starts with heading/action, horizontally scrollable tabs, a four-column metric strip, then a two-column team/jobs overview with a 34px gap. The roster uses three columns at desktop and four below 1100px; destinations collapse to one column below 1100px.

At 640px, the top bar and content use 16px gutters, the heading stacks, metrics become a 2×2 grid, the roster becomes two columns, and job rows hide decorative icons to preserve readable records. Horizontal tab overflow is retained rather than wrapping.

## Elevation & Depth

The system is flat-by-default. Depth comes from warm tonal layering, ruled borders, the deep lead-agent panel, and a fixed receipt drawer; no box-shadow vocabulary is used in the Command Center CSS. Active states use color and border changes, not floating effects.

### Named Rules
**The Tonal Ledger Rule.** Use panel beige and deep ink to establish hierarchy; do not introduce ornamental shadows into this paper register.

## Shapes

Shapes are gently rounded and functional: controls use 5–8px radii, agent cards 10px, and the lead module 12px. Dividers are 1px solid rules. The lead icon is circular; status marks are tiny circles. Inputs and selects are outlined, transparent, and compact.

## Components

### Buttons
- **Shape:** Compact rounded controls (5–8px).
- **Primary:** Signal orange fill, ink text, 12px × 17px padding, heavy label weight.
- **Hover / Focus:** Primary shifts to a lighter orange; all interactive elements receive a 3px signal-ink outline with 3px offset on focus-visible.
- **Secondary / Ghost:** Transparent blue text or outlined strong-rule controls for retry, pagination, and cancellation.

### Cards / Containers
- **Agent lead:** Deep ink, light text, 12px radius, 20px padding, blue outlined circular icon, orange outbound action.
- **Agent cards:** Transparent paper cards with 1px rule border, 10px radius, 14px/10px padding; hover/selected state uses panel beige and blue border.
- **Notices:** Panel beige, 8px radius, 16px padding.

### Inputs / Fields
- **Search/select:** Transparent paper controls with strong-rule border, 7px radius, compact 8–10px padding, muted placeholder/label text.
- **Focus:** Signal-ink 3px outline via the shared focus-visible rule.

### Navigation
- **Top bar:** Momentum wordmark, divider, Command Center label, workspace scope; 18px × 32px padding desktop and 14px × 16px mobile.
- **Tabs:** Blue active text with 2px blue bottom rule; muted at rest; 27px desktop gap and horizontal overflow on mobile.

### Signature Component: Execution Receipt
The selected run opens a fixed right-side paper drawer, up to 460px wide, with a strong left rule, status, actual model/usage/cost metadata, error notice when present, and cancellation controls only for active ordinary runs.

## Do's and Don'ts

### Do:
- **Do** keep the Momentum paper/ink/blue/orange palette and authentic wordmark together.
- **Do** use blue for state, navigation, and operational links; reserve orange for deliberate action.
- **Do** preserve visible loading, error, empty, source-scope, and reduced-motion behavior.
- **Do** keep numbers tabular and records bounded with readable truncation.

### Don't:
- **Don't** turn run counters into marketing KPIs or claim data that is unavailable.
- **Don't** add perpetual motion, orbiting diagrams, fake progress, or decorative shadows.
- **Don't** replace the deep lead-agent anchor with a generic card grid.
- **Don't** canonize the unrelated global aurora/golden-text utilities as Command Center language; they are outside this shipped surface.
