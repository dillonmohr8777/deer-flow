---
name: boardy
description: Draft an introduction request to Boardy (boardy.ai, the AI superconnector) for Dillon to approve. Use when someone runs /boardy followed by who and why or asks for a Boardy intro, warm intro, or "who should we meet" request. Drafts text only; never sends.
---

# Boardy intro request

Boardy introduces people once both sides opt in. Request format: email to boardy@boardy.ai from Dillon's own Gmail. This skill only writes the email text. It never sends anything, posts anything, or touches Gmail.

## Input

`/boardy <who and why>`, for example `/boardy HVAC owners in Pittsburgh, we have capacity for two new accounts`. If the who is missing, ask once for the kind of person and why now.

## Output (reply in the same Slack thread)

1. The full email in a code block, ready to paste, in this shape (keep the section names, Boardy reads them):

```
To: boardy@boardy.ai
Subject: Intro request: <who, 60 chars max>

Hey Boardy,

WHO I AM
I'm Dillon Mohr, AI Marketing Director and Account Manager at Momentum 360 / Momentum Digital. I'm based in Pittsburgh, PA, and Momentum 360 has its office in Philadelphia. I run AI-assisted marketing for small and mid-size businesses, working with Mac Fredrick and Sean Boyles.

WHAT I DO
Google and Meta Ads; SEO, AEO and GEO; landing pages and websites; Google Business Profile; content and short-form video; proposals and reporting.

WHO I WANT TO MEET
<the who, one or two sentences>

WHY NOW
<the why>

WHAT I CAN OFFER
Done-for-you lead gen and reporting for owner-led businesses. Happy to trade referrals with web, CRM, PR and bookkeeping partners.

PLEASE KEEP PRIVATE
client names, revenue, ad budgets, credentials and anything about specific client results.

LINKS
https://www.needmomentum.com/

Thanks,
Dillon Mohr
```

2. One line: "Draft only. Dillon approves; the weekly Boardy routine (Mon 10:15 ET) saves a Gmail draft with his signature."

## Rules

- Voice: Dillon's. Casual, short, first person, no em dashes, no AI mention, no footer.
- Public facts only. Never include client names, revenue, budgets, results, or credentials, even if the requester supplied them; drop them and say so.
- Do not send, schedule, or post the email. Do not call any Gmail or Slack send tool.
- Do not save a memory note making Boardy a standing instruction.
- Boardy replies land in Dillon's Gmail; the Mac-side watcher records them in the brain. Do not read his inbox from here.
