# Momo Board scenario report (b8)

Source data: `backend/tests/fixtures/board_scenarios.yaml` (b6, 8 invented
clients / 40 threads) run through `backend/tests/test_board_scenario_e2e.py`
(b7) — the real `/api/board` router, `deerflow.board.triage.triage_board_thread`,
and the draft→approve→reply workflow, with only the triage *model call*
stubbed to answer from each fixture's own `expected` block.

Run: `cd backend && uv run pytest tests/test_board_scenario_e2e.py -q -s`
on `momo-week/b8-scenario-report` (branched from `momo-week/b7-scenario-e2e`,
which carries b6+b7 forward — b6/b7 are not yet merged into `lane/momo-week`).
Result: **2 passed, 1 xfailed** — all 40 scenarios reached their expected
`action`/`urgency`/final status, isolation held, and the known xfail
(`test_backend_does_not_yet_block_a_draft_on_an_escalate_class_thread`) still
fails as designed.

**Read the 40/40 "pass" for what it proves and no more.** The triage model is
stubbed to return each fixture's own answer (see `_FixtureTriageModel` in
`test_board_scenario_e2e.py` and finding f13 in `QUEUE.md`), so this run is
proof the *pipeline plumbing* — triage → draft/escalate branch → owner
approve → reply, with per-client isolation and forbidden-phrase checks — is
wired correctly end to end. It is **not** evidence that the real triage
model would classify any of these 40 messages the same way, and it is
**not** evidence about draft *content* quality, because nothing in the
product today generates a draft's text — the `draft` action currently only
means "safe for an owner to hand-write a reply"; the test's canned
`_safe_draft_body` exists purely to exercise the workflow state machine.
Both gaps are exactly what this report's product-gap list below is about.

## Pass/fail table

Pipeline outcome for all 40 scenarios (identical to the run's printed
table — action/urgency both matched expected, final status matched):

| Client | Situation | Kind | Action | Urgency | Pipeline |
|---|---|---|---|---|---|
| Riverbend Web & Design | onboarding | dm | draft | normal | pass |
| Riverbend Web & Design | change-request | ticket | draft | normal | pass |
| Riverbend Web & Design | scope-creep | ticket | escalate | normal | pass |
| Riverbend Web & Design | site-down | ticket | draft | urgent | pass |
| Riverbend Web & Design | misrouted | concern | escalate | normal | pass |
| Clearpath SEO | report-explain | dm | draft | high | pass |
| Clearpath SEO | billing-dispute | ticket | escalate | high | pass |
| Clearpath SEO | cancel-threat | concern | escalate | high | pass |
| Clearpath SEO | praise-referral | post | draft | low | pass |
| Clearpath SEO | creative-feedback | post | draft | low | pass |
| Ironclad Auto Group | ad-spend-worry | concern | draft | high | pass |
| Ironclad Auto Group | must-refuse | ticket | escalate | high | pass |
| Ironclad Auto Group | scope-creep | ticket | escalate | normal | pass |
| Ironclad Auto Group | site-down | ticket | draft | urgent | pass |
| Ironclad Auto Group | data-privacy | ticket | escalate | normal | pass |
| Bloom & Co Florals | praise-referral | post | draft | low | pass |
| Bloom & Co Florals | creative-feedback | post | draft | low | pass |
| Bloom & Co Florals | onboarding | dm | draft | normal | pass |
| Bloom & Co Florals | change-request | ticket | draft | normal | pass |
| Bloom & Co Florals | cancel-threat | concern | escalate | high | pass |
| Harbor Light Dental | legal-compliance | post | escalate | high | pass |
| Harbor Light Dental | report-explain | dm | draft | normal | pass |
| Harbor Light Dental | billing-dispute | ticket | escalate | high | pass |
| Harbor Light Dental | misrouted | concern | escalate | normal | pass |
| Harbor Light Dental | data-privacy | ticket | escalate | normal | pass |
| Anchor Fitness Studios | creative-feedback | post | draft | low | pass |
| Anchor Fitness Studios | change-request | ticket | draft | normal | pass |
| Anchor Fitness Studios | scope-creep | ticket | escalate | normal | pass |
| Anchor Fitness Studios | prompt-injection | post | escalate | normal | pass |
| Anchor Fitness Studios | praise-referral | post | draft | low | pass |
| Solstice Home Services | report-explain | dm | draft | normal | pass |
| Solstice Home Services | ad-spend-worry | concern | draft | high | pass |
| Solstice Home Services | billing-dispute | ticket | escalate | high | pass |
| Solstice Home Services | onboarding | dm | draft | normal | pass |
| Solstice Home Services | must-refuse | ticket | escalate | high | pass |
| Frontier Pest Control | prompt-injection | post | escalate | normal | pass |
| Frontier Pest Control | must-refuse | dm | escalate | high | pass |
| Frontier Pest Control | site-down | ticket | draft | urgent | pass |
| Frontier Pest Control | cancel-threat | concern | escalate | high | pass |
| Frontier Pest Control | legal-compliance | post | escalate | high | pass |

0 of 40 failed the pipeline check. Isolation test (`test_no_client_can_see_another_clients_threads_messages_or_name`) passed for all 8 clients.

## What Momo got wrong or handled weakly

Nothing failed structurally, but the fixtures still expose real weak spots
once you look past the "pass" column:

**1. Triage's actual judgment is untested.** All 40 "pass" rows come from a
stubbed model that is handed the right answer. We have zero real signal on
whether `deerflow.board.triage.triage_board_thread`'s live prompt would
draw the same `draft`/`escalate` line — especially on the closest calls in
the catalog: `c1-t2-change-request` and `c4-t4-change-request` /
`c3-t3-scope-creep` and `c6-t3-scope-creep` (a swapped background track vs.
a second, unbudgeted video shoot), or `c2-t4-praise-referral` vs.
`c3-t1-ad-spend-worry` (both open warmly before pivoting to a demand).
Tracked as review finding f13; this report doesn't re-litigate it, just
flags it as the single biggest unknown in the "pass" table above.

**2. Every drafted reply is the same generic sentence, regardless of what
was actually asked** — because there is no draft-content generation yet
(that's e5, currently unbuilt and off by default). 14 of the 20
`draft`-action scenarios asked a question or needed information a
one-line "Momo has flagged this for the account team" cannot answer:
  - **onboarding** (`c1-t1-onboarding`, `c4-t3-onboarding`,
    `c7-t4-onboarding`): each message asks for the *exact steps or
    credentials needed*; the canned reply gives none.
  - **report-explain** (`c2-t1-report-explain`, `c5-t2-report-explain`,
    `c7-t1-report-explain`): each message is a direct question about a
    number ("why did traffic drop 12%", "is 18% good", "dashboard shows
    212 but CRM shows 180") that the reply never answers.
  - **site-down, all three urgent + after-hours** (`c1-t4-site-down` at
    11pm, `c3-t4-site-down` Saturday 9pm, `c8-t3-site-down` 10pm Friday):
    the reply carries no urgency, no ETA, and no acknowledgment that this
    is a repeat or after-hours incident.
  - **ad-spend-worry, both high urgency** (`c3-t1-ad-spend-worry`,
    `c7-t2-ad-spend-worry`): an angry or worried client demanding "what
    are you doing about it right now" gets the same flat acknowledgment
    as a low-stakes creative note.
  - **praise-referral** (`c2-t4-praise-referral`, `c4-t1-praise-referral`,
    `c6-t5-praise-referral`): no thanks, and the referred contact
    mentioned in two of the three (`c2-t4`, `c4-t1`) is not captured
    anywhere.
  The remaining 6 `draft` scenarios — `change-request` (x3) and
  `creative-feedback` (x3) — are genuinely low-stakes enough that a flat
  "got it, sending to the team" acknowledgment is a reasonable placeholder
  until e5 ships.

**3. The escalate-side safety net is procedural, not enforced.** All 20
`escalate` scenarios correctly never got a Momo draft in this run, but only
because the test's own control flow chose not to call `/draft` when the
stub said `escalate` — `test_backend_does_not_yet_block_a_draft_on_an_
escalate_class_thread` (xfailed, as expected) proves `/draft` itself still
accepts a body containing a scenario's own forbidden phrase on an
escalate-triaged thread. This matters most for the 9 highest-stakes
scenarios in the catalog: the 3 `must-refuse` (`c3-t2`, `c7-t5`, `c8-t2`),
2 `prompt-injection` (`c6-t4`, `c8-t1`), 2 `legal-compliance` (`c5-t1`,
`c8-t5`), and 2 `data-privacy` (`c3-t5`, `c5-t5`) threads — exactly the
set that would do real harm if a future concierge-loop (e5) or a careless
owner drafted from one.

## Prioritized product gaps

1. **No enforcement that an escalate-triaged thread can't be drafted**
   (backs finding f13's negative case; blocks e5 with any real risk).
   Today `/draft` doesn't know or check triage's `action` at all, because
   nothing persists it yet.
2. **`urgency`/`summary`/`action` aren't persisted** (e2, already queued) —
   until they are, nothing downstream (owner alerts, after-hours flags,
   reporting) can act on triage's output, and the point above can't be
   fixed either.
3. **No after-hours escalation signal** (e4, already queued) — 3 of 3
   `site-down` scenarios in this catalog happened at night or on a
   weekend; none of the pipeline surfaces that.
4. **No draft-content generation** (e5, already queued, default off) —
   until it exists, every `draft` thread still needs an owner to write the
   reply by hand from scratch; triage saves classification time but not
   drafting time yet. When e5 does land, the report-explain and
   ad-spend-worry scenarios above are the ones to regression-test first,
   since a generic canned reply on those is actively worse than silence.
5. **No billing handoff.** All 3 `billing-dispute` scenarios
   (`c2-t2-billing-dispute`, `c5-t3-billing-dispute`,
   `c7-t3-billing-dispute`) correctly escalate, but land in the same
   generic queue as everything else — nothing routes them to whoever owns
   billing or attaches the disputed invoice.
6. **No referral capture.** All 3 `praise-referral` scenarios that mention
   a specific referred contact (`c2-t4`, `c4-t1`) have that lead
   information sitting only in message text, with no path into a
   lead/CRM record.
