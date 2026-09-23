import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  articleJsonLd,
  type DailyArticle,
  parseArticle,
  serializeJsonLd,
  visibleArticles,
} from "@/core/momo-daily";

const CONTENT_DIR = join(process.cwd(), "src", "content", "momo-daily");

function article(overrides: Partial<DailyArticle> = {}): DailyArticle {
  return parseArticle({
    title: "What is a test?",
    dek: "A short dek.",
    slug: "what-is-a-test",
    date: "2026-09-20",
    author: { name: "Dillon Mohr", title: "AI Marketing Director" },
    keywords: ["testing"],
    summary: "A test is a check that fails when the logic breaks.",
    section: "Research",
    hero: {
      src: "/momentum/momos-living/research/flat.webp",
      alt: "Research Momo",
    },
    status: "published",
    body: [{ heading: "Why test?", paragraphs: ["Because."] }],
    ...overrides,
  });
}

describe("visibleArticles", () => {
  const published = article({ slug: "published-one", date: "2026-09-01" });
  const draft = article({
    slug: "draft-one",
    status: "draft",
    date: "2026-09-10",
  });

  it("hides drafts from the public list", () => {
    expect(visibleArticles([draft, published], { signedIn: false })).toEqual([
      published,
    ]);
  });

  it("shows drafts to signed-in workspace users, newest first", () => {
    expect(
      visibleArticles([published, draft], { signedIn: true }).map(
        (a) => a.slug,
      ),
    ).toEqual(["draft-one", "published-one"]);
  });
});

describe("articleJsonLd", () => {
  it("emits NewsArticle and BreadcrumbList with a Person author and Momentum publisher", () => {
    const graphs = articleJsonLd(article());
    expect(graphs.map((g) => g["@type"])).toEqual([
      "NewsArticle",
      "BreadcrumbList",
    ]);

    const news = graphs[0]!;
    expect(news["@context"]).toBe("https://schema.org");
    expect(news.headline).toBe("What is a test?");
    expect(news.datePublished).toBe("2026-09-20");
    expect(news.author).toMatchObject({
      "@type": "Person",
      name: "Dillon Mohr",
      jobTitle: "AI Marketing Director",
    });
    expect(news.publisher).toMatchObject({
      "@type": "Organization",
      name: "Momentum",
    });
    expect(String(news.url)).toMatch(/^https?:\/\/.+\/daily\/what-is-a-test$/);
    expect((news.image as string[])[0]).toMatch(/^https?:\/\//);

    const crumbs = graphs[1]!.itemListElement as {
      position: number;
      item: string;
    }[];
    expect(crumbs.map((c) => c.position)).toEqual([1, 2]);
    expect(crumbs[1]!.item).toBe(news.url);
  });

  it("adds FAQPage only when the article has a FAQ", () => {
    const graphs = articleJsonLd(
      article({ faq: [{ question: "Is it fast?", answer: "Yes." }] }),
    );
    const faq = graphs.find((g) => g["@type"] === "FAQPage");
    expect(faq?.mainEntity).toEqual([
      {
        "@type": "Question",
        name: "Is it fast?",
        acceptedAnswer: { "@type": "Answer", text: "Yes." },
      },
    ]);
  });

  it("serializes as valid JSON that cannot close its script tag", () => {
    const [news] = articleJsonLd(article({ title: "</script><b>x</b>" }));
    const json = serializeJsonLd(news!);
    expect(json).not.toContain("<");
    expect(JSON.parse(json).headline).toBe("</script><b>x</b>");
  });
});

describe("content/momo-daily", () => {
  const files = readdirSync(CONTENT_DIR).filter((name) =>
    name.endsWith(".json"),
  );

  it("every article file parses, its slug matches its name, and copy has no dashes", () => {
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const text = readFileSync(join(CONTENT_DIR, name), "utf8");
      const parsed = parseArticle(JSON.parse(text), name);
      expect(`${parsed.slug}.json`).toBe(name);
      expect(text).not.toMatch(/[—–]/);
    }
  });

  it("rejects an unknown status", () => {
    expect(() => article({ status: "live" as never })).toThrow();
  });
});
