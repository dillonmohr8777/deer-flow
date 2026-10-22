import { type MetadataRoute } from "next";

import { absoluteUrl } from "@/core/momo-daily";

/** Read MOMOBOT_SITE_URL per request; a build-time prerender would bake in localhost. */
export const dynamic = "force-dynamic";

/*
 * Public pages (the landing page and The Momo Daily) are open to every
 * crawler, AI answer engines included; the private workspace, API and
 * sign-in flows are not. The sitemap lists only published articles.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/daily"],
        disallow: [
          "/workspace",
          "/api",
          "/invite",
          "/auth",
          "/login",
          "/setup",
          "/artifacts",
          "/showcase",
          "/mock",
        ],
      },
    ],
    sitemap: absoluteUrl("/sitemap.xml"),
  };
}
