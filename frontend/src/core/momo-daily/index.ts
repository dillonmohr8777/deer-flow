/*
 * The Momo Daily: article schema, visibility and structured data.
 *
 * Pure logic only (no fs, no React) so it runs in node tests. Loading the
 * JSON files lives in ./load.ts, which is server-only.
 *
 * Articles are JSON files under src/content/momo-daily/<slug>.json. Only
 * `status: "published"` is public; drafts render for signed-in workspace
 * users, stamped "Draft", and are never indexed or listed in the sitemap.
 */

import { z } from "zod";

export const MOMO_DAILY_NAME = "The Momo Daily";
export const MOMO_DAILY_PATH = "/daily";

/**
 * Absolute origin for canonical, OpenGraph, sitemap and JSON-LD URLs.
 * MOMOBOT_SITE_URL is read on the server at runtime, so one image serves any
 * domain; NEXT_PUBLIC_SITE_URL (inlined at build) is the fallback, then the
 * local nginx entry.
 */
export const SITE_URL = (
  process.env.MOMOBOT_SITE_URL ??
  process.env.NEXT_PUBLIC_SITE_URL ??
  "http://localhost:2026"
).replace(/\/+$/, "");

const isoDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "date must be YYYY-MM-DD");

export const articleSchema = z.object({
  title: z.string().min(1),
  /** One sentence under the headline. Also the meta description. */
  dek: z.string().min(1),
  slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  date: isoDate,
  updated: isoDate.optional(),
  author: z.object({ name: z.string().min(1), title: z.string().optional() }),
  keywords: z.array(z.string().min(1)).default([]),
  /** Answer-first summary shown in the box at the top of the article. */
  summary: z.string().min(1),
  section: z.string().min(1),
  hero: z.object({ src: z.string().startsWith("/"), alt: z.string().min(1) }),
  status: z.enum(["draft", "published"]),
  /** Body blocks; headings read as questions where natural. */
  body: z
    .array(
      z.object({
        heading: z.string().min(1),
        paragraphs: z.array(z.string().min(1)).min(1),
      }),
    )
    .min(1),
  faq: z
    .array(z.object({ question: z.string().min(1), answer: z.string().min(1) }))
    .default([]),
  /** Where the article's facts come from; listed under the article and cited in JSON-LD. */
  sources: z
    .array(
      z.object({
        title: z.string().min(1),
        url: z.string().url().startsWith("https://"),
      }),
    )
    .default([]),
});

export type DailyArticle = z.infer<typeof articleSchema>;

export function parseArticle(raw: unknown, source = "article"): DailyArticle {
  const parsed = articleSchema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(`${source}: ${parsed.error.message}`);
  }
  return parsed.data;
}

/** Newest first; drafts only for a signed-in workspace user. */
export function visibleArticles(
  articles: readonly DailyArticle[],
  { signedIn }: { signedIn: boolean },
): DailyArticle[] {
  return articles
    .filter((article) => signedIn || article.status === "published")
    .sort((a, b) => b.date.localeCompare(a.date));
}

export function articlePath(slug: string) {
  return `${MOMO_DAILY_PATH}/${slug}`;
}

/*
 * Inline links in article text, written as [anchor](target). Only another
 * Daily article (/daily/<slug>) or an https:// page counts; anything else
 * stays plain text, so content can never inject a script or javascript: URL.
 */
const INLINE_LINK = /\[([^\]]+)\]\((\/daily\/[a-z0-9-]+|https:\/\/[^\s)]+)\)/g;

export type TextPart = { text: string; href?: string };

export function textParts(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE_LINK)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ text: match[1] ?? "", href: match[2] });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** The text with link markup removed, for meta tags and JSON-LD. */
export function plainText(text: string) {
  return text.replace(INLINE_LINK, "$1");
}

/** Up to *count* other published reads: same section first, then newest. */
export function relatedArticles(
  article: DailyArticle,
  articles: readonly DailyArticle[],
  count = 3,
): DailyArticle[] {
  const others = articles.filter(
    (other) => other.slug !== article.slug && other.status === "published",
  );
  const sameSection = others.filter(
    (other) => other.section === article.section,
  );
  const rest = others.filter((other) => other.section !== article.section);
  const byNewest = (a: DailyArticle, b: DailyArticle) =>
    b.date.localeCompare(a.date);
  return [...sameSection.sort(byNewest), ...rest.sort(byNewest)].slice(
    0,
    count,
  );
}

export function absoluteUrl(path: string) {
  return `${SITE_URL}${path}`;
}

/*
 * One reporter Momo per section: the living cut-paper crew under
 * public/momentum/momos-living/<slug>/. Sections not listed fall back to
 * the lead Momo.
 */
export const REPORTERS = {
  lead: "Front Page",
  research: "Research",
  analytics: "Data",
  builder: "Tools",
  engineer: "Engineering",
  growth: "Search and Growth",
  revenue: "Business",
  "client-success": "Clients",
  qa: "Quality",
  verifier: "Safety",
  reliability: "Reliability",
  migration: "Platforms",
} as const;

export type ReporterSlug = keyof typeof REPORTERS;

export const REPORTER_SLUGS = Object.keys(REPORTERS) as ReporterSlug[];

export function reporterForSection(section: string): ReporterSlug {
  const match = REPORTER_SLUGS.find(
    (slug) => REPORTERS[slug].toLowerCase() === section.toLowerCase(),
  );
  return match ?? "lead";
}

export function reporterLayers(slug: ReporterSlug) {
  const base = `/momentum/momos-living/${slug}`;
  return {
    layers: [`${base}/back.webp`, `${base}/body.webp`, `${base}/top.webp`],
    flatSrc: `${base}/flat.webp`,
  };
}

const ORGANIZATION = {
  "@type": "Organization",
  "@id": `${SITE_URL}/#organization`,
  name: "Momentum",
  url: SITE_URL,
  logo: { "@type": "ImageObject", url: absoluteUrl("/momentum/wordmark.png") },
} as const;

type JsonLd = Record<string, unknown>;

/**
 * NewsArticle + BreadcrumbList, plus FAQPage when the article has a FAQ.
 * Returned as a list of separate graphs, each rendered in its own
 * application/ld+json script.
 */
export function articleJsonLd(article: DailyArticle): JsonLd[] {
  const url = absoluteUrl(articlePath(article.slug));
  const graphs: JsonLd[] = [
    {
      "@context": "https://schema.org",
      "@type": "NewsArticle",
      headline: article.title,
      description: plainText(article.dek),
      abstract: plainText(article.summary),
      datePublished: article.date,
      dateModified: article.updated ?? article.date,
      articleSection: article.section,
      keywords: article.keywords.join(", "),
      image: [absoluteUrl(article.hero.src)],
      mainEntityOfPage: { "@type": "WebPage", "@id": url },
      url,
      author: {
        "@type": "Person",
        "@id": `${SITE_URL}/#${article.author.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
        name: article.author.name,
        ...(article.author.title ? { jobTitle: article.author.title } : {}),
        worksFor: ORGANIZATION,
      },
      publisher: ORGANIZATION,
      isPartOf: {
        "@type": "Periodical",
        name: MOMO_DAILY_NAME,
        url: absoluteUrl(MOMO_DAILY_PATH),
      },
      ...(article.sources.length > 0
        ? {
            citation: article.sources.map((source) => ({
              "@type": "CreativeWork",
              name: source.title,
              url: source.url,
            })),
          }
        : {}),
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: MOMO_DAILY_NAME,
          item: absoluteUrl(MOMO_DAILY_PATH),
        },
        { "@type": "ListItem", position: 2, name: article.title, item: url },
      ],
    },
  ];
  if (article.faq.length > 0) {
    graphs.push({
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: article.faq.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: { "@type": "Answer", text: plainText(item.answer) },
      })),
    });
  }
  return graphs;
}

/** JSON for a <script> body: `<` escaped so content can never close the tag. */
export function serializeJsonLd(graph: JsonLd) {
  return JSON.stringify(graph).replace(/</g, "\\u003c");
}

/** "Tuesday, September 23, 2026" for a YYYY-MM-DD date, timezone-proof. */
export function formatEditionDate(date: string) {
  const [y = 1970, m = 1, d = 1] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}
