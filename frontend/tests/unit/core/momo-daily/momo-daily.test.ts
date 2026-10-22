import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  articleJsonLd,
  type DailyArticle,
  parseArticle,
  plainText,
  relatedArticles,
  serializeJsonLd,
  textParts,
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

describe("articleJsonLd citations", () => {
  it("cites the sources and keeps link markup out of structured text", () => {
    const graphs = articleJsonLd(
      article({
        summary: "Read [the guide](/daily/what-is-a-test) first.",
        faq: [
          {
            question: "Why?",
            answer: "See [Google](https://developers.google.com/search).",
          },
        ],
        sources: [
          {
            title: "Google Search Central",
            url: "https://developers.google.com/search",
          },
        ],
      }),
    );
    const news = graphs.find((g) => g["@type"] === "NewsArticle")!;
    expect(news.abstract).toBe("Read the guide first.");
    expect(news.citation).toEqual([
      {
        "@type": "CreativeWork",
        name: "Google Search Central",
        url: "https://developers.google.com/search",
      },
    ]);
    const faq = graphs.find((g) => g["@type"] === "FAQPage") as {
      mainEntity: { acceptedAnswer: { text: string } }[];
    };
    expect(faq.mainEntity[0]!.acceptedAnswer.text).toBe("See Google.");
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

  it("every published article cites 2 to 5 sources and links only to real Daily articles", () => {
    const slugs = new Set(files.map((name) => name.replace(/\.json$/, "")));
    for (const name of files) {
      const parsed = parseArticle(
        JSON.parse(readFileSync(join(CONTENT_DIR, name), "utf8")),
        name,
      );
      if (parsed.status !== "published") continue;
      expect(parsed.sources.length, name).toBeGreaterThanOrEqual(2);
      expect(parsed.sources.length, name).toBeLessThanOrEqual(5);
      const text = [
        parsed.summary,
        ...parsed.body.flatMap((b) => b.paragraphs),
        ...parsed.faq.map((f) => f.answer),
      ];
      for (const part of text.flatMap(textParts)) {
        if (part.href?.startsWith("/daily/")) {
          expect(
            slugs.has(part.href.slice("/daily/".length)),
            `${name} -> ${part.href}`,
          ).toBe(true);
        }
      }
    }
  });
});

describe("inline links", () => {
  it("turns Daily and https links into parts and leaves anything else as text", () => {
    expect(
      textParts(
        "See [the guide](/daily/what-is-a-test) and [Google](https://developers.google.com/search) or [bad](javascript:alert(1)) [plain](http://x.test).",
      ),
    ).toEqual([
      { text: "See " },
      { text: "the guide", href: "/daily/what-is-a-test" },
      { text: " and " },
      { text: "Google", href: "https://developers.google.com/search" },
      { text: " or [bad](javascript:alert(1)) [plain](http://x.test)." },
    ]);
    expect(plainText("Read [the guide](/daily/what-is-a-test).")).toBe(
      "Read the guide.",
    );
  });

  it("only accepts https sources", () => {
    expect(() =>
      article({ sources: [{ title: "Insecure", url: "http://example.com" }] }),
    ).toThrow();
  });
});

describe("relatedArticles", () => {
  it("puts the same section first, skips the article itself and drafts, and stops at three", () => {
    const self = article({ slug: "self", section: "Research" });
    const pool = [
      self,
      article({
        slug: "other-section-new",
        section: "Tools",
        date: "2026-09-30",
      }),
      article({
        slug: "same-section-old",
        section: "Research",
        date: "2026-09-01",
      }),
      article({
        slug: "same-section-new",
        section: "Research",
        date: "2026-09-25",
      }),
      article({ slug: "a-draft", section: "Research", status: "draft" }),
      article({
        slug: "other-section-old",
        section: "Tools",
        date: "2026-09-02",
      }),
    ];
    expect(relatedArticles(self, pool).map((a) => a.slug)).toEqual([
      "same-section-new",
      "same-section-old",
      "other-section-new",
    ]);
  });
});
