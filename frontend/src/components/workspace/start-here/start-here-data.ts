import { safeLocalStorage } from "@/core/settings/local";

export type StartHereLesson = {
  id: string;
  title: string;
  minutes: number;
  summary: string;
  steps: readonly string[];
  tryPrompt: string;
};

export type PromptLibraryItem = {
  id: string;
  title: string;
  category:
    | "Website"
    | "SEO & AEO"
    | "Social & GBP"
    | "Paid Ads"
    | "Strategy"
    | "Profile";
  description: string;
  prompt: string;
};

export const BUSINESS_OWNER_LESSONS: readonly StartHereLesson[] = [
  {
    id: "control-panel-vs-chat",
    title: "Control Panel vs. Chat: Where to Start Every Week",
    minutes: 2,
    summary:
      "Use Control Panel to track kickoff setup, weekly deliverables, meeting follow-ups, and reporting readiness. Use Chat whenever you want MomoBot to create a page, blog, campaign, or plan.",
    steps: [
      "Open Control Panel from the top of the left sidebar to see your 4 workspace tabs.",
      "Pick any 1-click workflow under Create Something to launch a structured chat prompt.",
      "Return to Weekly Plan & Approvals to check deliverables before anything goes live.",
    ],
    tryPrompt:
      "Give me a simple 3-step weekly marketing routine for my business using MomoBot so I can spend under 30 minutes a week reviewing high-impact work.",
  },
  {
    id: "business-profile-setup",
    title: "Teach MomoBot Your Business Profile in 3 Minutes",
    minutes: 3,
    summary:
      "Better context produces sharper pages, local SEO content, and ads. Run the short profile interview once so every draft reflects your real services and service area.",
    steps: [
      "Click Try This in Chat below to start the 8-question Business Profile interview.",
      "Answer naturally by typing or clicking the Voice mic button in the chat bar.",
      "Save or reuse the finished profile summary whenever you spin up new campaigns.",
    ],
    tryPrompt:
      "Interview me step by step to create my Business Profile. Ask 8 short questions about my services, location, ideal customers, tone, and 90-day goal, then write a reusable summary.",
  },
  {
    id: "build-and-preview-pages",
    title: "Build a Webpage and Preview It Live Inside Chat",
    minutes: 3,
    summary:
      "Ask MomoBot to create a landing page or homepage as an HTML file, then click Preview Page right on the file card to inspect Desktop and Mobile views immediately.",
    steps: [
      "Describe the offer, city, and main call to action you want on your page.",
      "Wait for the HTML file card to appear in the chat response.",
      "Click Preview Page to test Desktop and Mobile layouts, copy the HTML, or download the file.",
    ],
    tryPrompt:
      "Create a clean, mobile-friendly single-file HTML landing page for my top service with a clear hero headline, 3 proof points, customer FAQs, and a booking section. Save it as landing-page.html and present it for live preview.",
  },
  {
    id: "weekly-seo-social-ads",
    title: "Turn One Brief Into Local SEO/AEO, GBP, Social & Ads",
    minutes: 4,
    summary:
      "Instead of starting from a blank page every week, use one customer question or seasonal offer to generate aligned search, social, and paid ad drafts together.",
    steps: [
      "Pick one core service or seasonal promotion you want more leads for this month.",
      "Ask MomoBot for a local SEO/AEO article, a Google Business Profile post, and 3 social captions.",
      "Review each draft and request quick tone or offer edits before approving.",
    ],
    tryPrompt:
      "Take my primary service and create a coordinated local visibility pack: 1 local SEO/AEO FAQ blog outline, 1 Google Business Profile post, and 3 short social posts ready for my review.",
  },
  {
    id: "voice-approvals-reporting",
    title: "Use Voice Dictation, Approvals & Reporting Connections",
    minutes: 3,
    summary:
      "Speak naturally with the composer mic button when brainstorming, keep final sign-off in Client Inbox, and connect Google Ads, GA4, Search Console, and call tracking for live lead proof.",
    steps: [
      "Click the Voice button in the chat input bar to dictate ideas hands-free.",
      "Paste call notes into Chat to pull out clean decisions and owner action items.",
      "Visit Results & Reporting in Control Panel to check which analytics accounts are ready to connect.",
    ],
    tryPrompt:
      "List the exact read-only access details I need to share so Google Ads, GA4, Google Search Console, and call tracking can power my monthly lead report.",
  },
];

export const PROMPT_LIBRARY_CATEGORIES = [
  "All",
  "Website",
  "SEO & AEO",
  "Social & GBP",
  "Paid Ads",
  "Strategy",
  "Profile",
] as const;

export type PromptLibraryCategory = (typeof PROMPT_LIBRARY_CATEGORIES)[number];

export const PROMPT_LIBRARY: readonly PromptLibraryItem[] = [
  {
    id: "homepage-refresh",
    title: "Homepage Conversion Redesign",
    category: "Website",
    description:
      "Build a live-previewable HTML homepage focused on local trust and phone or form leads.",
    prompt:
      "Design and build a complete single-file HTML homepage for my business with strong local trust signals, clear service blocks, customer FAQs, and an above-the-fold contact call to action. Save it as homepage.html so I can preview it live.",
  },
  {
    id: "service-landing-page",
    title: "High-Intent Service Landing Page",
    category: "Website",
    description:
      "Create a focused paid-search landing page for one flagship service.",
    prompt:
      "Build a focused single-file HTML landing page built for Google Ads traffic for my highest-margin service. Include a clear value promise, 3-step process, social proof placeholders, and a lead form layout. Present it as service-landing.html.",
  },
  {
    id: "aeo-faq-article",
    title: "Local SEO & AI Answer Engine Article",
    category: "SEO & AEO",
    description:
      "Write a helpful local guide structured for Google Search and AI citations.",
    prompt:
      "Write an 800-word local SEO and AEO article answering the #1 question customers ask before hiring my business. Start with a concise direct answer, include local considerations, and end with 5 structured FAQ answers.",
  },
  {
    id: "gbp-weekly-pack",
    title: "Weekly Google Business Profile & Social Pack",
    category: "Social & GBP",
    description:
      "Generate one GBP update and three social posts with photo ideas.",
    prompt:
      "Draft 1 Google Business Profile update and 3 social media posts for this week highlighting a customer problem we solve, a behind-the-scenes tip, and a clear booking call to action.",
  },
  {
    id: "review-reply-templates",
    title: "Customer Review Reply Kit",
    category: "Social & GBP",
    description:
      "Create warm, human responses for 5-star reviews and constructive feedback.",
    prompt:
      "Write 5 natural, local-friendly reply templates for positive Google reviews and 3 calm, helpful response templates for mixed or critical reviews that protect our reputation.",
  },
  {
    id: "google-ads-blueprint",
    title: "Local Google Ads Campaign Blueprint",
    category: "Paid Ads",
    description:
      "Structure search ad groups, local keywords, negatives, and ad variations.",
    prompt:
      "Draft a local Google Ads search blueprint for my business: 3 tight service ad groups, high-intent keywords, a starter negative keyword list, and 6 crisp responsive search headlines and descriptions.",
  },
  {
    id: "gtm-90-day",
    title: "30/60/90-Day Local Growth Plan",
    category: "Strategy",
    description:
      "Prioritize quick wins, core offers, and weekly channel execution.",
    prompt:
      "Build a practical 30/60/90-day local growth plan for my business covering positioning, lead offers, quick wins for the first 30 days, and monthly milestones.",
  },
  {
    id: "meeting-action-plan",
    title: "Turn Call Notes Into an Action Plan",
    category: "Strategy",
    description:
      "Convert messy meeting notes into decisions, owners, and next steps.",
    prompt:
      "Turn these meeting notes into a clean summary with decisions made, owner action items, and the top deliverable to tackle first:\n\n",
  },
  {
    id: "business-profile-interview",
    title: "Guided Business Profile Interview",
    category: "Profile",
    description:
      "Answer 8 quick questions to capture your services, tone, and goals.",
    prompt:
      "Ask me 8 short questions one group at a time to build a complete Business Profile for my workspace, then compile my answers into a clean reference sheet.",
  },
];

function lessonsStorageKey(scopeKey: string) {
  return `momobot.start-here.lessons.${scopeKey}`;
}

export function readStartHereProgress(
  scopeKey: string,
): Record<string, boolean> {
  const raw = safeLocalStorage.getItem(lessonsStorageKey(scopeKey));
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

export function writeStartHereProgress(
  scopeKey: string,
  progress: Record<string, boolean>,
): void {
  safeLocalStorage.setItem(
    lessonsStorageKey(scopeKey),
    JSON.stringify(progress),
  );
}
