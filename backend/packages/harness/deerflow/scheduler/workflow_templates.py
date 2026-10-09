"""Agency workflow templates for scheduled tasks (data only, no client data).

The roster is read at run time from the operator's client registry, never from
this repo. Seeded tasks start paused; turning on ``scheduler.enabled`` is a
separate operator decision.
"""

from __future__ import annotations

from typing import Any

from deerflow.scheduler.schedules import normalize_cron_expression, validate_timezone

TIMEZONE = "America/New_York"
REGISTRY_PATH = "~/code/client-operations-canonical/registry/clients.json"

RULES = f"""Rules that apply to everything you do in this run:
- Drafts only. Never send an email, never post to Slack or social, never change an account.
- No AI footer, signature or mention of AI anywhere in anything you write.
- Write in Dillon's casual voice: "hey y'all", short sentences, no em dashes, no corporate phrasing.
- Never invent numbers, dates or promises. If a number is missing, say it is missing. Missing is not zero.
- Get the client roster at run time from {REGISTRY_PATH}. Only work on clients marked active there. Never mix one client's data with another's.
- Finish with a short plain list of what you drafted and what you skipped and why."""

_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "monday-report-drafts",
        "title": "Monday report prep and client email drafts",
        "cron": "0 7 * * 1",
        "prompt": """Monday weekly report prep. For every active client in the registry, create one Gmail DRAFT of the weekly report email.
- Find that client's exact report URL in the registry or the client's notes. Link it. If you cannot find it, skip the client and say so.
- Bold the 3 to 5 KPIs that matter most this week, with real values from the report. Keep the whole email short.
- If the client already has a weekly-report email thread, reply inside that thread. Otherwise start a new draft.
- Cc the agency partners using the exact addresses from that client's past report threads. Do not guess addresses.
- Use Dillon's usual Gmail signature, with no AI footer.

"""
        + RULES,
    },
    {
        "key": "client-followup-sweep",
        "title": "Client follow-up sweep",
        "cron": "0 8 * * 1-5",
        "prompt": """Weekday follow-up sweep. Search Gmail for client threads where the last message is from the client and Dillon has not replied for more than 2 business days.
- Only include threads with active clients from the registry.
- For each one, write a Gmail DRAFT reply inside the same thread. Answer what they asked using facts you can verify. If you need an answer from Dillon first, say what is missing in the run summary and skip the draft.
- Keep replies short. Do not promise dates, numbers or deliverables that are not confirmed.

"""
        + RULES,
    },
    {
        "key": "search-term-review",
        "title": "Weekly search term review (read only)",
        "cron": "0 9 * * 2",
        "prompt": """Weekly Google Ads search term review, read only. For each active client that runs Google Ads, pull the last 7 days of search terms with a read-only tool.
- Flag wasted spend: terms with real spend and zero conversions, and terms that clearly do not match the offer. Show the actual spend and click numbers.
- Suggest negative keywords with the match type and the campaign or ad group they belong to.
- Put the suggestions in a Gmail DRAFT to Dillon, one section per client. Do not change any account, budget, bid, keyword or campaign. If the data is unavailable for a client, say it is unavailable.

"""
        + RULES,
    },
    {
        "key": "morning-brief",
        "title": "Morning brief",
        "cron": "30 6 * * 1-5",
        "prompt": """Weekday morning brief for Dillon. Read his calendar, unread client email and the client queue.
- Lead with what needs him today, then meetings, then anything waiting on a reply.
- Group by client using the registry. Keep it to one short screen.
- Save it as a Gmail DRAFT to Dillon. Do not message anyone else.

"""
        + RULES,
    },
]


def workflow_templates() -> list[dict[str, Any]]:
    """Return create-request payloads (plus a stable ``key``) for each workflow."""
    return [
        {
            "key": spec["key"],
            "title": spec["title"],
            "prompt": spec["prompt"],
            "schedule_type": "cron",
            "schedule_spec": {"cron": normalize_cron_expression(spec["cron"])},
            "timezone": TIMEZONE,
            "context_mode": "fresh_thread_per_run",
        }
        for spec in _TEMPLATES
    ]


def validate_template(template: dict[str, Any]) -> None:
    """Raise ValueError unless the template is a valid cron task payload."""
    validate_timezone(template["timezone"])
    normalize_cron_expression(template["schedule_spec"]["cron"])
    if template["schedule_type"] != "cron":
        raise ValueError("workflow templates must be cron schedules")


def plan_seed(existing_titles: set[str]) -> list[dict[str, Any]]:
    """Templates not yet created, matched by title so reruns are idempotent."""
    return [t for t in workflow_templates() if t["title"] not in existing_titles]
