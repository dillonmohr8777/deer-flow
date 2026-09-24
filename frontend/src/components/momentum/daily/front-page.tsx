"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
} from "react";

import { MomoFilm } from "@/components/momentum/momo-film";
import { Scraps } from "@/components/momentum/scraps";
import {
  articlePath,
  type DailyArticle,
  MOMO_DAILY_NAME,
  REPORTER_SLUGS,
  REPORTERS,
  reporterForSection,
} from "@/core/momo-daily";

import { Reporter } from "./reporter";
import { StaffBox } from "./staff-box";
import { useDailyMotion } from "./use-daily-motion";

import styles from "./daily.module.css";

/** Matches the .sheet[data-turning] animation in daily.module.css. */
export const PAGE_TURN_MS = 720;
const MAX_TILT_DEG = 4;

export function DraftStamp() {
  return (
    <span
      className={styles.draftStamp}
      aria-label="Draft, visible to the team only"
    >
      Draft
    </span>
  );
}

function Masthead({
  editionDate,
  motion,
}: {
  editionDate: string;
  motion: boolean;
}) {
  return (
    <header className={styles.masthead}>
      <div className={styles.mastheadTop}>
        <span>Vol. I</span>
        <span>Late City Edition</span>
        <span>Price: one good question</span>
      </div>
      <div className={styles.mastheadRow}>
        <div className={styles.ear}>
          <MomoFilm
            name="momo-daily"
            live={motion}
            className={styles.earFilm}
          />
          <p>Reporting the latest in AI for Momentum clients and crew.</p>
        </div>
        <h1 className={styles.title}>{MOMO_DAILY_NAME}</h1>
        <div className={`${styles.ear} ${styles.earRight}`}>
          <p>Set in type by the Momentum newsroom, twelve Momos strong.</p>
        </div>
      </div>
      <p className={styles.dateline}>
        <span>Philadelphia</span>
        <time>{editionDate}</time>
        <span>Momentum Digital</span>
      </p>
    </header>
  );
}

export function DailyFrontPage({
  articles,
  editionDate,
}: {
  articles: readonly DailyArticle[];
  editionDate: string;
}) {
  const motion = useDailyMotion();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [turning, setTurning] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const turnTimer = useRef<number | undefined>(undefined);

  // `/daily?open=1` (the article's back link) arrives already unfolding.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("open") === "1") {
      setOpen(true);
    }
    return () => window.clearTimeout(turnTimer.current);
  }, []);

  const turnTo = useCallback(
    (event: MouseEvent<HTMLAnchorElement>, slug: string) => {
      if (
        !motion ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      event.preventDefault();
      setTurning(true);
      turnTimer.current = window.setTimeout(
        () => router.push(articlePath(slug)),
        PAGE_TURN_MS,
      );
    },
    [motion, router],
  );

  const tilt = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const node = stageRef.current;
      if (!motion || open || event.pointerType !== "mouse" || !node) return;
      const rect = node.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width - 0.5;
      const py = (event.clientY - rect.top) / rect.height - 0.5;
      node.style.setProperty(
        "--daily-tilt-y",
        `${(px * 2 * MAX_TILT_DEG).toFixed(2)}deg`,
      );
      node.style.setProperty(
        "--daily-tilt-x",
        `${(-py * 2 * MAX_TILT_DEG).toFixed(2)}deg`,
      );
    },
    [motion, open],
  );

  const untilt = useCallback(() => {
    stageRef.current?.style.setProperty("--daily-tilt-y", "0deg");
    stageRef.current?.style.setProperty("--daily-tilt-x", "0deg");
  }, []);

  const [lead, ...rest] = articles;
  const leadReporter = lead ? reporterForSection(lead.section) : "lead";

  return (
    <div
      ref={stageRef}
      className={styles.stage}
      data-open={open ? "true" : "false"}
      data-motion={motion ? "on" : "off"}
      onPointerMove={tilt}
      onPointerLeave={untilt}
    >
      <button
        type="button"
        className={styles.unfold}
        onClick={() => setOpen(true)}
        aria-expanded={open}
      >
        Unfold today&apos;s edition
      </button>
      <div className={styles.sheet} data-turning={turning ? "true" : undefined}>
        <div className={styles.aboveFold}>
          <Masthead editionDate={editionDate} motion={motion} />

          {lead ? (
            <article
              className={styles.lead}
              aria-labelledby="daily-lead-heading"
            >
              <figure className={styles.leadArt}>
                <Reporter slug={leadReporter} size={200} motion={motion} />
                <figcaption>
                  Filed by the {REPORTERS[leadReporter]} desk
                </figcaption>
              </figure>
              <div className={styles.leadCopy}>
                <p className={styles.kicker}>
                  {lead.section}
                  {lead.status === "draft" ? <DraftStamp /> : null}
                </p>
                <h2 id="daily-lead-heading" className={styles.leadHeadline}>
                  <Link
                    href={articlePath(lead.slug)}
                    onClick={(event) => turnTo(event, lead.slug)}
                  >
                    {lead.title}
                  </Link>
                </h2>
                <p className={styles.dek}>{lead.dek}</p>
                <p className={styles.byline}>
                  By {lead.author.name}
                  {lead.author.title ? `, ${lead.author.title}` : ""}
                </p>
                <p className={styles.leadSummary}>{lead.summary}</p>
              </div>
            </article>
          ) : (
            <section
              className={styles.lead}
              aria-labelledby="daily-empty-heading"
            >
              <figure className={styles.leadArt}>
                <MomoFilm
                  name="momo-daily"
                  live={motion}
                  className={styles.leadFilm}
                />
              </figure>
              <div className={styles.leadCopy}>
                <p className={styles.kicker}>From the editor</p>
                <h2 id="daily-empty-heading" className={styles.leadHeadline}>
                  The presses are warming up
                </h2>
                <p className={styles.dek}>
                  The first edition is being set in type. Check back soon for
                  the latest in AI, written for the people who use it.
                </p>
              </div>
            </section>
          )}
        </div>

        <div className={styles.foldWrap}>
          <div className={styles.belowFold}>
            <section
              className={styles.edition}
              aria-labelledby="daily-edition-heading"
            >
              <h2 id="daily-edition-heading" className={styles.sectionHeading}>
                In this edition
              </h2>
              {rest.length > 0 ? (
                <ul className={styles.teasers}>
                  {rest.map((article) => {
                    const reporter = reporterForSection(article.section);
                    return (
                      <li key={article.slug} className={styles.teaser}>
                        <Reporter slug={reporter} size={88} motion={motion} />
                        <div>
                          <p className={styles.kicker}>
                            {article.section}
                            {article.status === "draft" ? <DraftStamp /> : null}
                          </p>
                          <h3 className={styles.teaserHeadline}>
                            <Link
                              href={articlePath(article.slug)}
                              onClick={(event) => turnTo(event, article.slug)}
                            >
                              {article.title}
                            </Link>
                          </h3>
                          <p className={styles.teaserDek}>{article.dek}</p>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={styles.quiet}>
                  More stories are being set in type for the next edition.
                </p>
              )}
            </section>

            <section
              className={styles.newsroom}
              aria-labelledby="daily-newsroom-heading"
            >
              <h2 id="daily-newsroom-heading" className={styles.sectionHeading}>
                The Newsroom
              </h2>
              <p className={styles.quiet}>
                Every section has its own reporter, cut from blue and kraft
                paper.
              </p>
              <ul className={styles.newsroomGrid}>
                {REPORTER_SLUGS.map((slug) => (
                  <li key={slug}>
                    <Reporter slug={slug} size={76} motion={motion} />
                    <span>{REPORTERS[slug]}</span>
                  </li>
                ))}
              </ul>
            </section>

            <StaffBox />
          </div>
        </div>
      </div>
      <Scraps
        names={["old-town", "writing", "speech-bubbles", "coast-road"]}
        live={motion}
        size={110}
        className={styles.dailyScraps}
      />
    </div>
  );
}
