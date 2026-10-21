"""Momentum work courses. Staff-only; stable IDs retain each person's progress."""

WORK_TRACKS = [
    {
        "id": "work-foundations",
        "title": "Start here: AI and MomoBot at work",
        "summary": "Four practical foundations, including the platform tour in under ten minutes.",
        "lessons": [
            {
                "id": "work-00-platform-tour",
                "title": "The entire MomoBot workspace in under ten minutes",
                "minutes": 9,
                "summary": "Follow one client brief through chat, files, run history and review, then find your way around the desktop and mobile workspace.",
                "steps": [
                    "Open the correct workspace and a saved chat.",
                    "Supply the brief, source dates and a clear acceptance check.",
                    "Inspect the generated file and its run record.",
                    "Save the owner, approval state and next action.",
                    "Reopen the same chat on your phone and compare the saved work.",
                ],
                "try_it": "Use Sample Dental Group as a synthetic client and ask for a weekly report draft from "
                "facts you provide. Record the chat link, artifact, owner and next action. Reopen that "
                "same chat on mobile and confirm the artifact and run status match.",
                "video_slot": "00-platform-tour",
                "video_url": None,
            },
            {
                "id": "work-01-ai-at-work",
                "title": "AI at Momentum: from request to checked work",
                "minutes": 6,
                "summary": "Learn what models, context, tools and memory do by turning supplied campaign facts into a checked report draft.",
                "steps": [
                    "State the outcome, supplied facts, constraints and format.",
                    "Separate facts from missing information.",
                    "Ask for a short draft with its calculations shown.",
                    "Check each number against the original source.",
                    "Save the checked draft and the remaining question.",
                ],
                "try_it": "For a synthetic campaign with 120 clicks and 12 inquiries, ask Momo for a short report "
                "that labels missing spend and qualified-lead data. Check its arithmetic yourself and "
                "confirm it did not invent a cost per lead.",
                "video_slot": "01-ai-at-work",
                "video_url": None,
            },
            {
                "id": "work-02-momo-handoff",
                "title": "Hand off work and pick it up again",
                "minutes": 6,
                "summary": "Keep the brief, owner, files and next action together so a teammate can pick up the same work after a session closes.",
                "steps": [
                    "Record the client, owner, source dates and acceptance check.",
                    "Save the chat link, files and approval state.",
                    "Close the tab and reopen that saved chat.",
                    "Read the last run before repairing a failed step.",
                    "Confirm the destination before repeating an external action.",
                ],
                "try_it": "Create a synthetic delivery brief, close the tab and reopen the saved chat. Check its "
                "owner, files and next action. If a step failed, ask for a repair of that step and "
                "inspect the run record before repeating an external action.",
                "video_slot": "02-momo-handoff",
                "video_url": None,
            },
            {
                "id": "work-03-terminal-work-stack",
                "title": "The terminal and your work stack",
                "minutes": 6,
                "summary": "Read files and run a small local check in a practice folder. Understand paths, output, exit status and logs.",
                "steps": [
                    "Open an isolated practice folder and run pwd.",
                    "Use ls to inspect its files before running a command.",
                    "Read the brief and sample CSV with cat and head.",
                    "Run the supplied check and inspect its exit status.",
                    "Change only the practice input and explain the failed check.",
                ],
                "try_it": "In a new practice folder, create a text brief, list it and read it with local terminal "
                "commands. Ask Momo to explain the output and exit status. Confirm the original file "
                "still exists and no production system was contacted.",
                "video_slot": "03-terminal-work-stack",
                "video_url": None,
            },
        ],
    },
    {
        "id": "work-roles",
        "title": "Choose your Momentum role",
        "summary": "A real work deliverable and an exercise for every role family, including specialist and support roles.",
        "lessons": [
            {
                "id": "work-04-account-client-success",
                "title": "Account management, projects and client success",
                "minutes": 6,
                "summary": "Turn a weekly report and customer question into checked KPIs, a project handoff and a clear reply draft.",
                "steps": [
                    "Match the account, reporting period and open promises.",
                    "Reconcile each KPI against its dated source.",
                    "Draft the report summary and answer the customer question.",
                    "Assign the project handoff and next action.",
                    "Review the exact reply and keep it unsent until authorized.",
                ],
                "try_it": "Use a synthetic weekly report and customer question. Ask for a KPI summary, open promises, project handoff and reply draft. Verify every number against the supplied report and leave the message unsent.",
                "video_slot": "04-account-client-success",
                "video_url": None,
            },
            {
                "id": "work-05-sales-outbound",
                "title": "Sales, prospecting and outbound",
                "minutes": 6,
                "summary": "Build a prospect brief, useful discovery questions and a pitch grounded in evidence.",
                "steps": [
                    "Verify the prospect identity and its first-party sources.",
                    "Check ownership and existing contact records for duplicates.",
                    "Separate observed gaps from unsupported assumptions.",
                    "Draft discovery questions and a relevant pitch.",
                    "Save the CRM owner and next action before approved outreach.",
                ],
                "try_it": "Create one synthetic prospect brief, discovery questions and pitch draft. Mark unsupported claims as missing. Check the existing contact and sender records for duplicates before any approved outreach.",
                "video_slot": "05-sales-outbound",
                "video_url": None,
            },
            {
                "id": "work-06-360-operations",
                "title": "Virtual-tour operations and shoot coordination",
                "minutes": 6,
                "summary": "Move a virtual-tour request through shoot intake, access checks, photographer coordination and an editing handoff.",
                "steps": [
                    "Confirm the address, timezone, access contact and scope.",
                    "Check photographer availability against the actual record.",
                    "Build an owned shoot checklist from the brief.",
                    "Prepare the asset and editing handoff.",
                    "Review the confirmation draft before any booking or send.",
                ],
                "try_it": "Use a synthetic tour request to produce a shoot checklist, editing handoff and confirmation draft. Confirm the address, timezone, access contact and scope against the brief; do not book or send anything.",
                "video_slot": "06-360-operations",
                "video_url": None,
            },
            {
                "id": "work-07-editing-design",
                "title": "Editors, designers and creative production",
                "minutes": 6,
                "summary": "Organize creative assets, build a cut plan and check a reviewable export against the approved brief.",
                "steps": [
                    "List approved assets, usage rights and missing inputs.",
                    "Draft a cut plan and versioned review notes.",
                    "Check dimensions, captions and export settings.",
                    "Judge picture, color and audio in the actual export.",
                    "Save the accepted version and delivery draft.",
                ],
                "try_it": "Use a synthetic creative brief to create an asset manifest, cut plan and QA checklist. Check rights, dimensions, captions and audio in the actual export; save the review notes and delivery draft.",
                "video_slot": "07-editing-design",
                "video_url": None,
            },
            {
                "id": "work-08-web-development",
                "title": "Web development, UI and UX",
                "minutes": 6,
                "summary": "Reproduce a staging issue, make a small fix and verify the page, form and destination before release.",
                "steps": [
                    "Reproduce the issue and write the acceptance check.",
                    "Make the scoped change on a branch.",
                    "Review phone, tablet and desktop layouts.",
                    "Submit one authorized test and inspect its destination.",
                    "Request review with the evidence and release action.",
                ],
                "try_it": "Ask for a scoped fix plan for a synthetic staging form. Check the page at 390, 768 and "
                "1440 pixels, submit one test in an authorized test environment and verify the "
                "destination record before requesting a release.",
                "video_slot": "08-web-development",
                "video_url": None,
            },
            {
                "id": "work-09-seo-local-ai",
                "title": "SEO, local search, GBP, AEO and GEO",
                "minutes": 6,
                "summary": "Use dated search, crawl and listing evidence to rank SEO, GBP and AI-visibility improvements.",
                "steps": [
                    "Match source coverage and reporting dates.",
                    "Inspect the actual page, crawl and local listing.",
                    "Label missing values and test AI-answer claims.",
                    "Rank fixes by business impact and available evidence.",
                    "Save one measurable acceptance check per fix.",
                ],
                "try_it": "Use synthetic Search Console and local-listing data to make a ranked SEO, GBP and AI-visibility fix list. Open each source, label missing values and record one measurable acceptance check per fix.",
                "video_slot": "09-seo-local-ai",
                "video_url": None,
            },
            {
                "id": "work-10-paid-media",
                "title": "Paid media, paid search and measurement",
                "minutes": 6,
                "summary": "Reconcile ad metrics with CRM leads, explain attribution gaps and prepare one measured experiment.",
                "steps": [
                    "Match the date window and lead definitions.",
                    "Compare ad inquiries with CRM-qualified leads.",
                    "Check calculations and attribution differences.",
                    "Draft one experiment with a success measure.",
                    "Keep budget, bid and campaign changes awaiting approval.",
                ],
                "try_it": "Use synthetic ad metrics and a CRM lead export. Reconcile inquiries against qualified "
                "leads, identify attribution differences and draft one experiment. Verify the math and "
                "keep all budget, bid and campaign changes awaiting approval.",
                "video_slot": "10-paid-media",
                "video_url": None,
            },
            {
                "id": "work-11-content-social",
                "title": "Content, social media, email and outreach",
                "minutes": 6,
                "summary": "Turn one approved brand brief into channel-specific content with checked claims, rights and voice.",
                "steps": [
                    "Confirm the offer, audience and channel requirements.",
                    "Draft the caption, email and accessible image description.",
                    "Check facts, asset rights and recipients.",
                    "Edit the voice and review the final version.",
                    "Save the publishing or sending request for authorization.",
                ],
                "try_it": "Ask for a social caption, email draft and accessible image description from one "
                "synthetic brief. Check claims, rights, recipients and client context, edit the voice "
                "and leave publishing or sending for authorized review.",
                "video_slot": "11-content-social",
                "video_url": None,
            },
            {
                "id": "work-12-leadership-ops",
                "title": "Leadership and operations management",
                "minutes": 6,
                "summary": "Read accepted work, overdue promises, decisions and measured cost to choose the next bounded outcome.",
                "steps": [
                    "Check source dates and accepted-work records.",
                    "Identify overdue promises, owners and blockers.",
                    "Separate retainer revenue from ad spend.",
                    "Review the artifact, cost and exact decision needed.",
                    "Delegate one outcome with an independent acceptance check.",
                ],
                "try_it": "Use a synthetic work ledger and provider-cost receipt to make a leadership readout. Distinguish retainer revenue from ad spend. Choose one bounded outcome with an owner and an independent acceptance check.",
                "video_slot": "12-leadership-ops",
                "video_url": None,
            },
            {
                "id": "work-13-crm-automation-admin",
                "title": "CRM, automation, account support and virtual assistants",
                "minutes": 6,
                "summary": "Map a lead to the right record and owner, then test a paused automation without duplicate records or messages.",
                "steps": [
                    "Define required fields, ownership and the duplicate key.",
                    "Map the synthetic lead into a test CRM record.",
                    "Prepare the automation in a paused state.",
                    "Run one authorized test event and read back the destination.",
                    "Record the retry rule, owner and next action.",
                ],
                "try_it": "Map a synthetic lead into a test CRM record, create a paused automation plan and one test event. Verify the destination and owner, then explain how retries avoid a duplicate record or message.",
                "video_slot": "13-crm-automation-admin",
                "video_url": None,
            },
        ],
    },
    {
        "id": "work-growth",
        "title": "Improve your work stack over time",
        "summary": "Build reliable habits week by week, then improve the operation month by month.",
        "lessons": [
            {
                "id": "work-14-week-by-week",
                "title": "Make your work stack better week by week",
                "minutes": 6,
                "summary": "Build a four-week habit: measure one job, save a reusable brief, connect a source and test a repeatable workflow.",
                "steps": [
                    "Week 1: measure one recurring job and save its sources.",
                    "Week 2: reuse a brief and compare accepted output.",
                    "Week 3: verify one read-only connection and its scope.",
                    "Week 4: test a paused repeatable workflow with outside review.",
                    "Keep the output, check and measured time or cost each week.",
                ],
                "try_it": "Make a four-week improvement plan: baseline one job; save a reusable brief; add one "
                "verified read-only integration; test a paused repeatable workflow. For each week, save "
                "the output, check and measured time or cost.",
                "video_slot": "14-week-by-week",
                "video_url": None,
            },
            {
                "id": "work-15-month-by-month",
                "title": "Make AI your operating driver month by month",
                "minutes": 6,
                "summary": "Make one workflow reliable, improve team handoffs and review a measured set of recurring jobs each month.",
                "steps": [
                    "Month 1: establish a reliable role workflow and baseline.",
                    "Month 2: connect scoped context and team handoffs.",
                    "Month 3: review recurring work and record exceptions.",
                    "Compare accepted work, real time and provider cost.",
                    "Keep improvements that pass and retire steps that fail.",
                ],
                "try_it": "Make a three-month work-stack plan: one reliable workflow; scoped context and team "
                "handoffs; reviewed recurring work with an exception record in the existing queue. "
                "Compare accepted work, real time and provider cost each month, and retire steps that "
                "fail.",
                "video_slot": "15-month-by-month",
                "video_url": None,
            },
        ],
    },
]
