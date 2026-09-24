import { type Metadata } from "next";
import { notFound } from "next/navigation";

import { DailyArticleView } from "@/components/momentum/daily/article-view";
import {
  articleJsonLd,
  articlePath,
  MOMO_DAILY_NAME,
  serializeJsonLd,
  visibleArticles,
} from "@/core/momo-daily";
import { isSignedIn, loadAllArticles } from "@/core/momo-daily/load";

type Props = { params: Promise<{ slug: string }> };

/** Drafts resolve only for a signed-in workspace user; anyone else gets a 404. */
async function findArticle(slug: string) {
  const articles = visibleArticles(await loadAllArticles(), {
    signedIn: await isSignedIn(),
  });
  return articles.find((article) => article.slug === slug);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const article = await findArticle((await params).slug);
  if (!article) return {};
  const path = articlePath(article.slug);
  return {
    title: article.title,
    description: article.dek,
    keywords: article.keywords,
    authors: [{ name: article.author.name }],
    alternates: { canonical: path },
    robots:
      article.status === "draft" ? { index: false, follow: false } : undefined,
    openGraph: {
      type: "article",
      siteName: MOMO_DAILY_NAME,
      title: article.title,
      description: article.dek,
      url: path,
      publishedTime: article.date,
      modifiedTime: article.updated ?? article.date,
      authors: [article.author.name],
      section: article.section,
      tags: article.keywords,
      images: [{ url: article.hero.src, alt: article.hero.alt }],
    },
    twitter: {
      card: "summary",
      title: article.title,
      description: article.dek,
    },
  };
}

export default async function DailyArticlePage({ params }: Props) {
  const article = await findArticle((await params).slug);
  if (!article) notFound();

  return (
    <>
      {articleJsonLd(article).map((graph) => (
        <script
          key={String(graph["@type"])}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: serializeJsonLd(graph) }}
        />
      ))}
      <DailyArticleView article={article} />
    </>
  );
}
