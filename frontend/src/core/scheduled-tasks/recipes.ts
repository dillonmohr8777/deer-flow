import type { ScheduleValue } from "@/components/workspace/scheduled-task-schedule-input";

export type RecipeTitleKey =
  | "morningBrief"
  | "clientReport"
  | "siteWatch"
  | "visibility"
  | "pipeline";

export type Recipe = {
  id: string;
  titleKey: RecipeTitleKey;
  prompt: string;
  schedule: ScheduleValue;
};

const cronSchedule = (cron: string): ScheduleValue => ({
  schedule_type: "cron",
  schedule_spec: { cron },
  timezone: "",
});

// Front-end-only starter recipes for agency work. The schedule's timezone is
// left empty so the ScheduleInput falls back to the browser-detected timezone
// when applied. Every cron is a daily or weekly shape parseCron round-trips,
// so the applied schedule stays editable instead of landing in "custom".
// `{{client}}` style placeholders are intentional: the user fills them in the
// prompt field after applying the recipe. Prompts ask for drafts and cited
// numbers only; nothing here sends, posts or spends on its own.
export const RECIPES: Recipe[] = [
  {
    id: "morning-brief",
    titleKey: "morningBrief",
    prompt:
      "Write my morning client brief. Review yesterday's conversations, scheduled task runs and any client messages you can read, then list what needs a reply or an approval today, what is due this week, and anything that failed or stalled. Group it by client and put the most important item first. Mark anything you could not verify as unverified. Keep it to one page.",
    schedule: cronSchedule("0 8 * * 1,2,3,4,5"),
  },
  {
    id: "client-report",
    titleKey: "clientReport",
    prompt:
      'Draft this week\'s report for {{client}}: leads and booked work, spend, what we shipped, what is blocked, and the next three priorities. Use only numbers you can cite to a source export or dashboard, and write "not available" for anything you cannot find. This is a draft for review, not a message to send. Replace {{client}} with the client name.',
    schedule: cronSchedule("0 14 * * 5"),
  },
  {
    id: "site-watch",
    titleKey: "siteWatch",
    prompt:
      "Check each site in {{sites}}. Is the homepage up? Did the page title, main headline or contact form change since the last run? Do the key pages load without errors? Summarize what changed and anything broken, with the URL for each finding. Replace {{sites}} with the client URLs to watch.",
    schedule: cronSchedule("0 7 * * *"),
  },
  {
    id: "visibility",
    titleKey: "visibility",
    prompt:
      "Run the weekly search and AI-answer visibility check for {{client}}. For each keyword in {{keywords}}, record where the client appears in web search results and whether AI answer engines mention or cite them. Compare with last week where a record exists, then list the three fixes most likely to improve visibility. Cite every source URL. Replace {{client}} and {{keywords}} before running.",
    schedule: cronSchedule("0 9 * * 3"),
  },
  {
    id: "pipeline",
    titleKey: "pipeline",
    prompt:
      "Review the sales pipeline for the week ahead: open deals and their stage, leads with no reply in more than five days, and follow-ups due this week. Draft a short follow-up for each overdue lead for my approval, and do not send anything. Mark anything you could not verify as unverified.",
    schedule: cronSchedule("0 8 * * 1"),
  },
];
