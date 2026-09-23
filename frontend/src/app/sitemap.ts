import { type MetadataRoute } from "next";

import {
  absoluteUrl,
  articlePath,
  MOMO_DAILY_PATH,
  visibleArticles,
} from "@/core/momo-daily";
import { loadAllArticles } from "@/core/momo-daily/load";

/** Public pages only: drafts never reach the sitemap. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const published = visibleArticles(await loadAllArticles(), {
    signedIn: false,
  });
  return [
    { url: absoluteUrl("/") },
    {
      url: absoluteUrl(MOMO_DAILY_PATH),
      lastModified: published[0]?.date,
      changeFrequency: "daily",
    },
    ...published.map((article) => ({
      url: absoluteUrl(articlePath(article.slug)),
      lastModified: article.updated ?? article.date,
    })),
  ];
}
