import { type Metadata } from "next";

import { DailyFrontPage } from "@/components/momentum/daily/front-page";
import { getI18n } from "@/core/i18n/server";
import {
  absoluteUrl,
  articlePath,
  MOMO_DAILY_NAME,
  MOMO_DAILY_PATH,
  serializeJsonLd,
  visibleArticles,
} from "@/core/momo-daily";
import { getDailyViewer, loadAllArticles } from "@/core/momo-daily/load";

const DESCRIPTION =
  "Momentum's newspaper for clients and the team: the latest in AI, explained plainly and answered first.";

export const metadata: Metadata = {
  title: { absolute: `${MOMO_DAILY_NAME}: the latest in AI from Momentum` },
  description: DESCRIPTION,
  alternates: { canonical: MOMO_DAILY_PATH },
  openGraph: {
    type: "website",
    siteName: MOMO_DAILY_NAME,
    title: MOMO_DAILY_NAME,
    description: DESCRIPTION,
    url: MOMO_DAILY_PATH,
    images: ["/momentum/momos-living/lead/flat.webp"],
  },
  twitter: {
    card: "summary",
    title: MOMO_DAILY_NAME,
    description: DESCRIPTION,
  },
};

export default async function DailyPage() {
  const [viewer, { t }] = await Promise.all([getDailyViewer(), getI18n()]);
  const articles = visibleArticles(await loadAllArticles(), {
    signedIn: viewer.signedIn,
  });
  const editionDate = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "America/New_York",
  });
  const published = articles.filter(
    (article) => article.status === "published",
  );

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: serializeJsonLd({
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            name: MOMO_DAILY_NAME,
            description: DESCRIPTION,
            url: absoluteUrl(MOMO_DAILY_PATH),
            publisher: { "@type": "Organization", name: "Momentum" },
            hasPart: published.map((article) => ({
              "@type": "NewsArticle",
              headline: article.title,
              url: absoluteUrl(articlePath(article.slug)),
              datePublished: article.date,
            })),
          }),
        }}
      />
      <DailyFrontPage
        articles={articles}
        editionDate={editionDate}
        signedIn={viewer.signedIn}
        userId={viewer.userId}
        dailyBriefCopy={t.dailyBrief}
      />
    </>
  );
}
