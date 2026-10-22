import {
  absoluteUrl,
  articlePath,
  MOMO_DAILY_NAME,
  MOMO_DAILY_PATH,
  plainText,
  visibleArticles,
} from "@/core/momo-daily";
import { loadAllArticles } from "@/core/momo-daily/load";

/** Read MOMOBOT_SITE_URL per request; a build-time prerender would bake in localhost. */
export const dynamic = "force-dynamic";

/** llms.txt (llmstxt.org): a plain map of the published Momo Daily for AI answer engines. */
export async function GET() {
  const published = visibleArticles(await loadAllArticles(), {
    signedIn: false,
  });
  const lines = [
    `# ${MOMO_DAILY_NAME}`,
    "",
    "> Plain-English articles from Momentum on AI search (SEO, AEO, GEO), AI agents for small businesses and using AI safely.",
    "",
    `Front page: ${absoluteUrl(MOMO_DAILY_PATH)}`,
    "",
    "## Articles",
    "",
    ...published.map(
      (article) =>
        `- [${article.title}](${absoluteUrl(articlePath(article.slug))}): ${plainText(article.summary)}`,
    ),
    "",
  ];
  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
