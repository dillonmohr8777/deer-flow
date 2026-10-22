"use client";

import Link from "next/link";

import {
  articlePath,
  type DailyArticle,
  formatEditionDate,
  MOMO_DAILY_NAME,
  REPORTERS,
  reporterForSection,
  textParts,
} from "@/core/momo-daily";

import { DraftStamp } from "./front-page";
import { Reporter } from "./reporter";
import { useDailyMotion } from "./use-daily-motion";

import styles from "./daily.module.css";

const FRONT_PAGE = "/daily?open=1";

/** Article text with its [anchor](target) links: Daily links stay in the app, sources open in a new tab. */
function RichText({ text }: { text: string }) {
  return textParts(text).map((part, index) => {
    if (!part.href) return part.text;
    if (part.href.startsWith("/")) {
      return (
        <Link key={index} href={part.href}>
          {part.text}
        </Link>
      );
    }
    return (
      <a key={index} href={part.href} target="_blank" rel="noopener noreferrer">
        {part.text}
      </a>
    );
  });
}

export function DailyArticleView({
  article,
  related = [],
}: {
  article: DailyArticle;
  related?: DailyArticle[];
}) {
  const motion = useDailyMotion();
  const reporter = reporterForSection(article.section);

  return (
    <div
      className={styles.stage}
      data-open="true"
      data-motion={motion ? "on" : "off"}
    >
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <ol>
          <li>
            <Link href={FRONT_PAGE}>{MOMO_DAILY_NAME}</Link>
          </li>
          <li aria-current="page">{article.section}</li>
        </ol>
      </nav>

      <article
        className={`${styles.sheet} ${styles.articleSheet}`}
        data-arrive="true"
      >
        <header className={styles.articleHeader}>
          <p className={styles.articleFlag}>
            <Link href={FRONT_PAGE}>{MOMO_DAILY_NAME}</Link>
          </p>
          <p className={styles.kicker}>
            {article.section}
            {article.status === "draft" ? <DraftStamp /> : null}
          </p>
          <h1 className={styles.articleTitle}>{article.title}</h1>
          <p className={styles.dek}>{article.dek}</p>
          <div className={styles.articleByline}>
            <Reporter slug={reporter} size={64} motion={motion} />
            <p className={styles.byline}>
              By <span>{article.author.name}</span>
              {article.author.title ? `, ${article.author.title}` : ""}
              <br />
              <time dateTime={article.date}>
                {formatEditionDate(article.date)}
              </time>
              {article.updated ? (
                <>
                  {", updated "}
                  <time dateTime={article.updated}>
                    {formatEditionDate(article.updated)}
                  </time>
                </>
              ) : null}
            </p>
          </div>
        </header>

        <aside
          className={styles.answerBox}
          aria-labelledby="daily-answer-heading"
        >
          <h2 id="daily-answer-heading">The short answer</h2>
          <p>
            <RichText text={article.summary} />
          </p>
        </aside>

        <figure className={styles.hero}>
          <img
            src={article.hero.src}
            alt={article.hero.alt}
            width={320}
            height={320}
          />
        </figure>

        <div className={styles.articleBody}>
          {article.body.map((block) => (
            <section key={block.heading}>
              <h2>{block.heading}</h2>
              {block.paragraphs.map((paragraph) => (
                <p key={paragraph}>
                  <RichText text={paragraph} />
                </p>
              ))}
            </section>
          ))}
        </div>

        {article.faq.length > 0 ? (
          <section className={styles.faq} aria-labelledby="daily-faq-heading">
            <h2 id="daily-faq-heading">Questions readers ask</h2>
            {article.faq.map((item) => (
              <div key={item.question}>
                <h3>{item.question}</h3>
                <p>
                  <RichText text={item.answer} />
                </p>
              </div>
            ))}
          </section>
        ) : null}

        {article.sources.length > 0 ? (
          <section
            className={styles.faq}
            aria-labelledby="daily-sources-heading"
          >
            <h2 id="daily-sources-heading">Sources</h2>
            <ol>
              {article.sources.map((source) => (
                <li key={source.url}>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {source.title}
                  </a>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {related.length > 0 ? (
          <section
            className={styles.faq}
            aria-labelledby="daily-related-heading"
          >
            <h2 id="daily-related-heading">More from {MOMO_DAILY_NAME}</h2>
            {related.map((other) => (
              <div key={other.slug}>
                <h3>
                  <Link href={articlePath(other.slug)}>{other.title}</Link>
                </h3>
                <p>{other.dek}</p>
              </div>
            ))}
          </section>
        ) : null}
        <footer className={styles.articleFooter}>
          <p>
            Filed by the {REPORTERS[reporter]} desk of {MOMO_DAILY_NAME}.
          </p>
          <Link href={FRONT_PAGE}>Back to the front page</Link>
        </footer>
      </article>
    </div>
  );
}
