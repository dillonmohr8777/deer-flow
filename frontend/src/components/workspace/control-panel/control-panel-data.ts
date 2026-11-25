import { clientNewChatPath } from "@/core/auth/roles";
import { safeLocalStorage } from "@/core/settings/local";

export const MAX_PREFILL_PROMPT_CHARS = 4000;

export type CreateSomethingCard = {
  id: string;
  title: string;
  category: string;
  outcome: string;
  prompt: string;
};

export const CREATE_SOMETHING_CARDS: readonly CreateSomethingCard[] = [
  {
    id: "build-website",
    title: "Build My Website",
    category: "Website",
    outcome:
      "Generate a clean, mobile-ready single-page HTML website you can preview live right in chat.",
    prompt:
      "Build a modern, high-converting single-file HTML homepage for my business that I can preview live right here. Ask me 3 quick questions first if needed, or start with a clean layout including a clear headline, core services, local trust proof, customer FAQs, and a strong contact call to action. Save the finished page as index.html and present it so I can preview it.",
  },
  {
    id: "local-seo-aeo-blog",
    title: "Write Local SEO/AEO Blog",
    category: "SEO & AEO",
    outcome:
      "Draft an article built to rank locally on Google and get cited by AI answer engines.",
    prompt:
      "Write a local SEO and AI Answer Engine Optimization (AEO) blog article for my business. Include a clear target search question, direct answer summary near the top, local service-area relevance, structured H2/H3 headings, a 5-question FAQ section, and a natural call to action.",
  },
  {
    id: "weekly-gbp-social",
    title: "Draft Weekly GBP & Social Pack",
    category: "Content",
    outcome:
      "Create one Google Business Profile update plus a week of ready-to-approve social posts.",
    prompt:
      "Draft a weekly content pack for my business: 1 Google Business Profile update with a clear offer or helpful tip, plus 3 social media posts (with hook, caption, and visual idea for each) ready for my review before publishing.",
  },
  {
    id: "google-ads-strategy",
    title: "Create Google Ads Strategy",
    category: "Paid Ads",
    outcome:
      "Map high-intent local search campaigns, keyword groups, negative keywords, and ad copy.",
    prompt:
      "Create a focused local Google Ads search strategy for my business. Organize high-intent service keywords into tight ad groups, list essential negative keywords to prevent wasted spend, draft responsive search ad headlines and descriptions, and recommend conversion tracking priorities.",
  },
  {
    id: "go-to-market-plan",
    title: "Build Go-To-Market Plan",
    category: "Strategy",
    outcome:
      "Turn your offer, audience, and budget into a clear 30/60/90-day local growth roadmap.",
    prompt:
      "Build a practical 30/60/90-day Go-To-Market plan for my business. Cover ideal customer positioning, primary lead-generation offers, weekly marketing channels, quick-win deliverables for Month 1, and measurable milestones for Months 2 and 3.",
  },
  {
    id: "business-profile",
    title: "Fill Out My Business Profile",
    category: "Foundation",
    outcome:
      "Answer 8 short questions so every page, post, and campaign matches your voice and market.",
    prompt:
      "Interview me step by step to build my Business Profile. Ask 8 concise questions covering my core services, service area, ideal customers, top differentiators, pricing tier or offer style, brand voice, main competitors, and 90-day growth goal. Then summarize everything into a clean Business Profile document I can reuse.",
  },
];

export type RoadmapPhase = {
  id: string;
  phase: string;
  title: string;
  summary: string;
  deliverables: readonly string[];
};

export const KICKOFF_ROADMAP_PHASES: readonly RoadmapPhase[] = [
  {
    id: "phase-1",
    phase: "Phase 1",
    title: "Foundation & Business Profile",
    summary:
      "Lock in your offer, service area, brand voice, and ideal customer details so every output sounds like your business.",
    deliverables: [
      "Complete Business Profile interview",
      "Confirm priority services and target neighborhoods",
      "Clarify team roles and approval rules",
    ],
  },
  {
    id: "phase-2",
    phase: "Phase 2",
    title: "Website & Local SEO/AEO Assets",
    summary:
      "Build and preview landing pages and local answer-engine content designed to convert real leads.",
    deliverables: [
      "Draft and live-preview primary service or homepage HTML",
      "Publish local SEO/AEO cornerstone articles and FAQs",
      "Verify clear phone, form, and booking calls to action",
    ],
  },
  {
    id: "phase-3",
    phase: "Phase 3",
    title: "Weekly Plan, Content & Campaigns",
    summary:
      "Run a repeatable weekly cadence of Google Business Profile updates, social packs, and search campaigns with review gates.",
    deliverables: [
      "Weekly GBP & Social Pack drafted for review",
      "Google Ads keyword themes and negative keyword list",
      "Tracked approvals before anything publishes live",
    ],
  },
  {
    id: "phase-4",
    phase: "Phase 4",
    title: "Results & Reporting Loop",
    summary:
      "Connect your live analytics and ad accounts so every report ties spend and traffic back to real leads.",
    deliverables: [
      "Connect Google Ads, GA4, Search Console, and call tracking",
      "Review lead quality and conversion match-back monthly",
      "Refine offers and creative based on real performance",
    ],
  },
];

export type ChecklistItem = {
  id: string;
  title: string;
  description: string;
  actionLabel: string;
  actionKind: "prompt" | "route";
  actionTarget: string;
};

export const DAY_ONE_CHECKLIST: readonly ChecklistItem[] = [
  {
    id: "complete-profile",
    title: "Complete your Business Profile",
    description:
      "Capture services, service area, brand voice, and goals so MomoBot tailors every draft.",
    actionLabel: "Start profile interview",
    actionKind: "prompt",
    actionTarget: CREATE_SOMETHING_CARDS[5]!.prompt,
  },
  {
    id: "preview-first-page",
    title: "Build and preview your first webpage",
    description:
      "Generate an HTML page in chat and click Preview Page to inspect Desktop and Mobile layouts.",
    actionLabel: "Build my website",
    actionKind: "prompt",
    actionTarget: CREATE_SOMETHING_CARDS[0]!.prompt,
  },
  {
    id: "weekly-content-pack",
    title: "Draft your first Weekly GBP & Social Pack",
    description:
      "Create a week of local updates you can edit and approve before posting.",
    actionLabel: "Draft weekly pack",
    actionKind: "prompt",
    actionTarget: CREATE_SOMETHING_CARDS[2]!.prompt,
  },
  {
    id: "connect-reporting",
    title: "Review reporting connections",
    description:
      "Check which analytics and ad platforms still need access so real lead numbers flow in.",
    actionLabel: "Open Results & Reporting",
    actionKind: "route",
    actionTarget: "#reporting",
  },
  {
    id: "start-here-guide",
    title: "Complete the 5-minute Start Here guide",
    description:
      "Walk through the quick business-owner lessons and copy-ready prompt library.",
    actionLabel: "Open Start Here / Academy",
    actionKind: "route",
    actionTarget: "/workspace/start-here",
  },
];

export type TeamRoleSummary = {
  role: string;
  owner: string;
  responsibilities: string;
};

export const WORKSPACE_TEAM_ROLES: readonly TeamRoleSummary[] = [
  {
    role: "Business Owner / Approver",
    owner: "You & your team",
    responsibilities:
      "Share business goals, upload call notes, review drafts, and give final approval before anything publishes.",
  },
  {
    role: "MomoBot AI Workspace",
    owner: "Always-on assistant",
    responsibilities:
      "Drafts websites, local SEO/AEO blogs, weekly GBP and social packs, ad strategies, and action plans on demand.",
  },
  {
    role: "Account & Strategy Support",
    owner: "Your agency team",
    responsibilities:
      "Connects reporting channels, verifies campaign setup, and handles live production launches after approval.",
  },
];

export type ReportingConnection = {
  id: string;
  name: string;
  category: string;
  status: "connected" | "not_connected" | "unknown";
  statusLabel: string;
  unlocks: string;
};

export const REPORTING_CONNECTIONS: readonly ReportingConnection[] = [
  {
    id: "google-ads",
    name: "Google Ads",
    category: "Paid search",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks: "Live spend, clicks, cost per lead, and search-term performance.",
  },
  {
    id: "ga4",
    name: "GA4",
    category: "Web analytics",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks: "Website sessions, key events, and landing page conversion rates.",
  },
  {
    id: "search-console",
    name: "Search Console",
    category: "Organic search",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks:
      "Top local search queries, clicks, impressions, and indexing health.",
  },
  {
    id: "meta-ads",
    name: "Meta Ads",
    category: "Paid social",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks: "Facebook and Instagram reach, lead forms, and creative spend.",
  },
  {
    id: "whatconverts",
    name: "WhatConverts",
    category: "Lead tracking",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks: "Named calls, web forms, and lead-to-channel match-back.",
  },
  {
    id: "buffer",
    name: "Buffer",
    category: "Social publishing",
    status: "unknown",
    statusLabel: "Status unknown",
    unlocks: "Direct scheduled publishing after you approve a social draft.",
  },
];

export const MEETING_NOTES_PROMPT =
  "Turn my meeting notes or call transcript into a structured recap with: 1) Key decisions made, 2) Open action items with owner and target timing, and 3) Suggested next deliverable to draft. Here are the notes:\n\n";

export const CONNECT_REPORTING_PROMPT =
  "Help me prepare a quick access checklist to connect my Google Ads, GA4, Search Console, Meta Ads, WhatConverts, and Buffer accounts for reporting. Ask which platforms I currently use and give me simple step-by-step instructions.";

export type LocalActionItem = {
  id: string;
  text: string;
  done: boolean;
  createdAt: string;
};

export function parsePrefillPrompt(raw: string | null): string | undefined {
  if (!raw) {
    return undefined;
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return undefined;
  }
  return trimmed.slice(0, MAX_PREFILL_PROMPT_CHARS);
}

export function buildChatPromptHref({
  isClient,
  agents,
  agentsLoading = false,
  prompt,
}: {
  isClient: boolean;
  agents: readonly { name: string; builtin?: boolean }[];
  agentsLoading?: boolean;
  prompt: string;
}): string {
  const basePath =
    isClient && !agentsLoading
      ? clientNewChatPath(agents)
      : "/workspace/chats/new";
  const bounded = prompt.trim().slice(0, MAX_PREFILL_PROMPT_CHARS);
  if (!bounded) {
    return basePath;
  }
  return `${basePath}?prompt=${encodeURIComponent(bounded)}`;
}

function checklistStorageKey(scopeKey: string) {
  return `momobot.control-panel.checklist.${scopeKey}`;
}

export function readChecklistState(scopeKey: string): Record<string, boolean> {
  const raw = safeLocalStorage.getItem(checklistStorageKey(scopeKey));
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const result: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === "boolean") {
        result[key] = value;
      }
    }
    return result;
  } catch {
    return {};
  }
}

export function writeChecklistState(
  scopeKey: string,
  state: Record<string, boolean>,
): void {
  safeLocalStorage.setItem(
    checklistStorageKey(scopeKey),
    JSON.stringify(state),
  );
}

function actionItemsStorageKey(scopeKey: string) {
  return `momobot.control-panel.actions.${scopeKey}`;
}

export function readActionItems(scopeKey: string): LocalActionItem[] {
  const raw = safeLocalStorage.getItem(actionItemsStorageKey(scopeKey));
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is LocalActionItem =>
        Boolean(item) &&
        typeof item === "object" &&
        typeof (item as LocalActionItem).id === "string" &&
        typeof (item as LocalActionItem).text === "string" &&
        typeof (item as LocalActionItem).done === "boolean" &&
        typeof (item as LocalActionItem).createdAt === "string",
    );
  } catch {
    return [];
  }
}

export function writeActionItems(
  scopeKey: string,
  items: LocalActionItem[],
): void {
  safeLocalStorage.setItem(
    actionItemsStorageKey(scopeKey),
    JSON.stringify(items),
  );
}
