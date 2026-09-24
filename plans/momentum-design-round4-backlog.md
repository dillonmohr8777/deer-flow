# Design round 4 backlog

From Astra's visual review of the 2026-09-23 release candidate (shipped live as deer-flow-frontend:momentum-design-20260923). Also: two models share the display name "Muse Spark 1.3 (OpenRouter)"; give them distinct names without the tier word.

**7/10 for cohesion.** Cream, blue, serif headings and Momo establish a shared identity, but the interior pages mostly resemble conventional admin screens with scrapbook artwork added around them.

1. **#5 — The screenshot does not substantiate the documents experience.** “Chats” is selected and only “Untitled” appears beneath a long project title. Verify the documents route opens the Documents tab; show file names, ingestion status and a clear upload action.

2. **#2, #3 — Recorded work is difficult to distinguish.** Several assignments share the same truncated opening, while recent chats repeat vague prompts. Give titles two lines and add a compact date/project identifier; expose full titles on keyboard focus and hover.

3. **#2, #3 — Telemetry lacks enough context to be trustworthy.** “Recorded tokens” has no visible period, and “Tokens | 0%” leaves the denominator unexplained. Label scope and period, explain what the percentage measures, and display “Unavailable” when the underlying measurement is missing.

4. **#2–#6 — Small secondary text weakens usability.** Model names, token counts, tool badges and sidebar controls are noticeably harder to read than the oversized headings. Increase consequential metadata toward 14px, strengthen its weight, and give icon controls generous hit areas.

5. **#1 — The landing composition looks unfinished.** The enormous empty blue paper dominates the right side while all meaningful content stacks left; the footer sits beyond a large quiet region. Put a purposeful team illustration on that paper and tighten the page’s vertical spacing.

6. **#6 — Setup status overwhelms usefulness.** The first visible catalog sections are dominated by “Not installed” and “Not configured,” with identical “View” actions. Prioritize connected tools and relevant available integrations; distinguish “Connect,” “Configure” and “Details” where those actions actually apply.

7. **#1, #2 — Pins contradict their intended meaning.** Gold pins appear on static feature descriptions, so they cannot reliably signify “working.” Reserve pins for actively executing work; attach static paper with folds, slots or simple overlaps.

8. **#2, #4 — Agent identity changes between views.** Dillon Brain is represented by Momo on the dashboard and a “D” badge in Agents. Use one persistent avatar per agent, with grey tool variations identifying specialties and gold confined to Momo’s antenna.

Other visible inconsistencies: **#3 shows an empty chat composer, not a populated thread**; the sidebar’s Projects area is empty even while #5 displays a project. Text appears jagged throughout the supplied captures—verify native-resolution rendering before attributing that to the fonts.

**Bold idea:** Make Mission Control a working paper dispatch board: each mission keeps one paper slip from brief through review to receipt. Pins appear only during execution; completion leaves a dated ink stamp linked to evidence. The scrapbook language would explain the work itself.
