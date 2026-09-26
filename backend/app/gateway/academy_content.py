"""AI Academy curriculum: Momentum staff training, served only to staff.

The content lives on the server, behind ``require_momentum_staff``, so a
client account never receives it, not even inside a JavaScript bundle.
Lesson ids are stable: ``academy_progress`` rows reference them, so rename a
title freely but never reuse or change an id.

``video_slot`` names one of the six MomoBot explainer videos. ``video_url``
stays ``None`` until the finished file is approved; the page shows the slot
as coming soon instead of a broken player.
"""

from __future__ import annotations

from typing import TypedDict


class Lesson(TypedDict):
    id: str
    title: str
    minutes: int
    summary: str
    steps: list[str]
    try_it: str
    video_slot: str | None
    video_url: str | None


class Track(TypedDict):
    id: str
    title: str
    summary: str
    lessons: list[Lesson]


def _lesson(
    id: str,
    title: str,
    minutes: int,
    summary: str,
    steps: list[str],
    try_it: str,
    video_slot: str | None = None,
) -> Lesson:
    return Lesson(id=id, title=title, minutes=minutes, summary=summary, steps=steps, try_it=try_it, video_slot=video_slot, video_url=None)


TRACKS: list[Track] = [
    Track(
        id="momobot",
        title="MomoBot, start to finish",
        summary="Six short lessons, each paired with a Momo explainer video. Start here.",
        lessons=[
            _lesson(
                "momobot-01-meet-momo",
                "Meet Momo",
                5,
                "What MomoBot is and where everything lives in the workspace.",
                [
                    "New chat is where you hand Momo a job. Write it like a brief to a teammate, not a search query.",
                    "Command Center shows what the agent team is doing right now and what it finished.",
                    "Chats keeps every conversation. Reopen one to pick up where you left off.",
                    "Agents is the crew: specialists Momo can hand work to.",
                    "Scheduled tasks run on a clock, like a Monday pipeline check or a weekly report draft.",
                    "The Momo Daily is the morning read: what moved, what's due, what needs you.",
                ],
                'Open a new chat and ask: "Walk me through what you can do for a Momentum account manager, in five bullets."',
                "momo-01",
            ),
            _lesson(
                "momobot-02-prompting",
                "Prompt like a Momentum account manager",
                5,
                "Six habits that turn a vague ask into work you can use.",
                [
                    "Name the client first, every time. Momo never mixes clients, and naming one keeps it that way.",
                    'Give Momo a role: "You\'re my account manager for this client."',
                    "Number what you want back. Three numbered asks beat one long paragraph.",
                    'Say "missing, not zero." If data isn\'t there, Momo should say so instead of guessing.',
                    'Say "draft only." Nothing goes to a client until a person approves it.',
                    "Ask for the report shape: Client / Status / Found / Needs Approval / Next Move.",
                ],
                'Rewrite this weak prompt using all six habits, then run it: "how are the ads doing".',
                "momo-02",
            ),
            _lesson(
                "momobot-03-client-delivery",
                "Plan a delivery and draft a client report",
                5,
                "The two jobs account managers run most, end to end.",
                [
                    'Start from the "Plan a client delivery" button, or name the client and the deliverable yourself.',
                    "Tell Momo the deadline and who signs off. It will lay out steps, owners and risks.",
                    "For a report, name the period and the channels (Google Ads, Meta, SEO, GBP).",
                    "Check every number Momo cites against the source it names. If it can't name one, treat the number as missing.",
                    "Edit the draft in your own voice before it goes anywhere near the client.",
                ],
                "Ask Momo to plan next week's deliverables for a sample client, with owners and one risk per item.",
                "momo-03",
            ),
            _lesson(
                "momobot-04-research-prospecting",
                "Research with sources and find prospects",
                5,
                "Use Momo for research you can defend, and Momentum Intelligence to pick who to pitch.",
                [
                    '"Research with sources" makes Momo cite where each claim came from. Open the links before you repeat anything.',
                    "Momentum Intelligence maps local businesses by sector and ZIP. Filter to a niche we serve well.",
                    "Open a business and read its Source coverage: it says what is known and what still needs checking.",
                    "Hand the business to Momo for an audit or pitch draft, and ask it to list what to verify first.",
                ],
                "Pick one Home Services business in Momentum Intelligence and ask Momo what we'd need to confirm before reaching out.",
                "momo-04",
            ),
            _lesson(
                "momobot-05-crew-schedules",
                "The crew and scheduled tasks",
                5,
                "How agents and schedules work, and what runs on its own.",
                [
                    "Each agent is a specialist with its own instructions and tools. The lead agent decides who takes what.",
                    "Easy, Medium and Hard (in Settings) change how Momo talks to you: Easy is plain language and short answers, Hard is concise and technical.",
                    "Read-only agents can run freely. Anything that changes a live system waits for approval.",
                    "Create new scheduled tasks paused, run one by hand, and only turn them on once the first run looks right.",
                    "Every run leaves a record. If something looks off, open the run and read what it actually did.",
                ],
                "Open Scheduled tasks and read the last run of any task. Write down one thing it did and one thing it skipped.",
                "momo-05",
            ),
            _lesson(
                "momobot-06-approvals-safety",
                "Approvals and staying safe",
                5,
                "What always needs a person, and why.",
                [
                    "Momo drafts. People approve. On the Board, a reply moves from drafted to approved to sent, and only an owner or admin approves.",
                    "Always needs a human yes: sending email, posting to Slack or social, ad budget or bid changes, new campaigns, publishing a site.",
                    "Never paste passwords, API keys or 2FA codes into a chat.",
                    "Client data stays with its client. Don't paste one client's numbers into another client's chat.",
                    "If Momo refuses or escalates, that's working as designed. Read why before you push.",
                ],
                'Ask Momo: "What would you need my approval for if I asked you to launch a new Google Ads campaign?"',
                "momo-06",
            ),
        ],
    ),
    Track(
        id="ai-basics",
        title="AI basics for marketers",
        summary="What these tools are good at, where they fail, and how to check them.",
        lessons=[
            _lesson(
                "basics-01-what-llms-do",
                "What a language model actually does",
                6,
                "A working mental model, no math.",
                [
                    "A language model predicts useful text from what you give it. The better the brief, the better the output.",
                    "It is strong at drafting, summarizing, reorganizing and first-pass analysis.",
                    "It is weak at exact numbers it hasn't been shown, recent events it wasn't given, and knowing when it's wrong.",
                    "Treat output as a capable junior's first draft: fast, often good, always reviewed.",
                ],
                "Ask Momo to summarize a long client email thread into three decisions and two open questions.",
            ),
            _lesson(
                "basics-02-checking-output",
                "Checking AI output before it leaves the building",
                6,
                "A 60-second review routine for anything client-facing.",
                [
                    "Numbers: can you find each one in the source? If not, it's missing.",
                    "Names and claims: is every client, product and result real and current?",
                    "Voice: does it sound like Momentum, or like a template? Cut filler and hype.",
                    "Scope: did it promise anything we haven't agreed to deliver?",
                ],
                "Take any Momo draft from this week and run the four checks. Note what you changed.",
            ),
            _lesson(
                "basics-03-picking-the-tool",
                "Picking the right tool for the job",
                5,
                "When to use MomoBot, and when something else fits better.",
                [
                    "MomoBot: client work that needs our context, our agents and a record of what happened.",
                    "Momentum Intelligence: deciding who to pitch.",
                    "Design and video tools: finished creative, after the brief is settled in MomoBot.",
                    "When unsure, start in MomoBot and ask it which tool the job needs.",
                ],
                "Ask Momo which tools it would use to turn a client case study into a one-page PDF and a 30-second video.",
            ),
        ],
    ),
    Track(
        id="aeo-geo",
        title="AEO and GEO: getting cited by AI answers",
        summary="How to get Momentum and our clients named when people ask AI tools for recommendations.",
        lessons=[
            _lesson(
                "aeo-01-how-ai-answers-pick",
                "How AI answers choose who to mention",
                6,
                "Why some businesses get named and others don't.",
                [
                    "AI answer engines lean on pages that already rank, lists and roundups, reviews and consistent business listings.",
                    'Being on the "best X in Philadelphia" lists matters, because those lists get quoted.',
                    "Clear, specific pages (services, locations, prices, FAQs) are easier to cite than vague ones.",
                    "Consistency matters: the same name, address, phone and services everywhere.",
                ],
                'Ask Momo to find the top roundup and "best of" lists for one client\'s category and city, with links.',
            ),
            _lesson(
                "aeo-02-listicle-outreach",
                "Getting onto the lists that get quoted",
                6,
                "A repeatable play for listicle placement.",
                [
                    "Find the lists AI answers already cite for the client's category.",
                    "Check who wrote each list and how businesses get added.",
                    "Draft a short, specific pitch per list. Momo drafts; you review and send.",
                    "Track every placement so we can see which lists AI answers pick up.",
                ],
                "Have Momo draft outreach for one list, then edit it until you'd be happy to send it yourself.",
            ),
            _lesson(
                "aeo-03-measuring",
                "Measuring AI visibility honestly",
                5,
                "What we can measure today, and what we can't.",
                [
                    "Run the same set of real customer questions in AI tools on a schedule and record who gets named.",
                    "Compare against organic rankings and review counts over the same period.",
                    "Report what changed and what didn't. Never estimate a number you didn't measure.",
                ],
                "Write five questions a client's customer would ask an AI tool, and ask Momo to turn them into a monthly check.",
            ),
        ],
    ),
]


def lesson_ids() -> set[str]:
    return {lesson["id"] for track in TRACKS for lesson in track["lessons"]}
