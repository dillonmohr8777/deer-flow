// Server only: reads the content directory with node:fs.
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

import { cache } from "react";

import { getServerSideUser } from "@/core/auth/server";

import { type DailyArticle, parseArticle } from "./index";

const CONTENT_DIR = join(process.cwd(), "src", "content", "momo-daily");

/** Every article on disk, drafts included. Callers filter with visibleArticles(). */
export const loadAllArticles = cache(async (): Promise<DailyArticle[]> => {
  const files = (await readdir(CONTENT_DIR)).filter((name) =>
    name.endsWith(".json"),
  );
  return Promise.all(
    files.map(async (name) => {
      const raw: unknown = JSON.parse(
        await readFile(join(CONTENT_DIR, name), "utf8"),
      );
      const article = parseArticle(raw, name);
      if (`${article.slug}.json` !== name) {
        throw new Error(`${name}: slug must match the file name`);
      }
      return article;
    }),
  );
});

/**
 * Drafts are for signed-in workspace users only. Cached per request so the
 * page and its metadata share one gateway round trip.
 */
export const isSignedIn = cache(
  async () => (await getServerSideUser()).tag === "authenticated",
);
