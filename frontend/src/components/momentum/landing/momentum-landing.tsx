"use client";

/*
 * The signed-out front door.
 *
 * This replaces the stock upstream landing page, which advertised the
 * open-source project (Docs / Blog / "Star on GitHub" / MIT footer) rather
 * than the Momentum product people are invited into.
 *
 * Nothing under src/components/landing/** is imported or modified, so future
 * upstream pulls touching the hero, header, footer or marketing sections stay
 * conflict-free. The only upstream file this work changes is src/app/page.tsx.
 *
 * Two looks live here, chosen by resolveFunnelTreatment() (treatment.ts):
 * "current" (default, unchanged) and "paper" (scrapbook, `?look=paper`
 * only). This is a client component so it can re-resolve `?look=` after
 * mount; the server-rendered/first-paint output always uses
 * FUNNEL_TREATMENT ("current"), so day-one "/" stays byte-identical.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { CutPaper } from "@/components/momentum/cut-paper";
import { MomoFilm } from "@/components/momentum/momo-film";
import { useIntroMotion } from "@/components/momentum/momobot/intro-motion";
import { MomoBotLockup } from "@/components/momentum/momobot/lockup";
import { ScrapbookBackdrop } from "@/components/momentum/momobot/scrapbook-backdrop";
import {
  FUNNEL_TREATMENT,
  resolveFunnelTreatment,
} from "@/components/momentum/treatment";

import styles from "./momentum-landing.module.css";

/*
 * Static copy, not live numbers. The signed-out page has no session, so it
 * cannot read real run counts, and inventing them would be a lie told to the
 * person being onboarded. These describe how the workspace behaves.
 */
const CAPABILITIES = [
  {
    key: "Agents",
    body: (
      <>
        A <strong>lead</strong> that plans and delegates, with specialists for
        research, brand, revenue, client success and release review.
      </>
    ),
  },
  {
    key: "Runs",
    body: (
      <>
        Every dispatch is <strong>recorded</strong>: inputs, model, tokens and
        outcome, so work can be replayed rather than retold.
      </>
    ),
  },
  {
    key: "Receipts",
    body: (
      <>
        Sends, deploys and spend stay <strong>approval-gated</strong>. Drafts
        wait for a person; nothing leaves on an agent&apos;s own judgment.
      </>
    ),
  },
  {
    key: "Memory",
    body: (
      <>
        Client spaces are <strong>isolated</strong> by design. Knowledge
        compounds inside a workspace without leaking across it.
      </>
    ),
  },
];

// Staggered pin offsets for the four paper cards — deliberately uneven, never
// a three/four-equal-card row.
const CARD_OFFSETS = [0, 24, 8, 16] as const;

export function MomentumLanding() {
  // Initial state is always the plain default, matching what the server
  // rendered — reading window.location.search here would run during
  // hydration too and could disagree with the server's markup (which never
  // sees the URL) when `?look=paper` is present. Re-resolving in the effect
  // below (post-hydration) is what actually applies the query override, in
  // both directions, while keeping day-one "/" byte-identical.
  const [treatment, setTreatment] =
    useState<typeof FUNNEL_TREATMENT>(FUNNEL_TREATMENT);

  useEffect(() => {
    setTreatment(resolveFunnelTreatment());
  }, []);

  if (treatment === "paper") {
    return <PaperLanding />;
  }

  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <Link className={styles.wordmark} href="/">
            <MomoBotLockup wordmarkClassName={styles.wordmarkImage} />
          </Link>
          <Link className={styles.secondary} href="/workspace">
            Sign in
          </Link>
        </header>

        <main>
          <section className={styles.hero}>
            <p className={styles.eyebrow}>
              <span className={styles.eyebrowDot} aria-hidden="true" />
              Invite only
            </p>
            <h1 className={styles.title}>Give your ambition a team.</h1>
            <p className={styles.lede}>
              MomoBot is a private workspace where a team of agents takes on
              real work across research, build and review, and leaves a record
              you can check. You were invited here because someone wants you in
              the room.
            </p>
            <div className={styles.actions}>
              <Link className={styles.primary} href="/workspace">
                Enter the workspace
              </Link>
              <Link
                className={styles.secondary}
                href="/workspace/command-center"
              >
                Open Command Center
              </Link>
            </div>
          </section>

          <section className={styles.band} aria-labelledby="how-it-works">
            <div className={`${styles.panel} ${styles.panelLead}`}>
              <h2 className={styles.panelTitle} id="how-it-works">
                Built to be checked, not trusted blindly.
              </h2>
              <p className={styles.panelBody}>
                Agents move fast and are sometimes wrong. So the workspace is
                built around evidence: what was measured is kept separate from
                what was claimed, and anything that leaves the building waits
                for a human first.
              </p>
            </div>

            <div className={styles.panel}>
              <ul className={styles.rows}>
                {CAPABILITIES.map((item) => (
                  <li className={styles.row} key={item.key}>
                    <span className={styles.rowKey}>{item.key}</span>
                    <p className={styles.rowValue}>{item.body}</p>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </main>

        <footer className={styles.footer}>
          <span>© {new Date().getFullYear()} Momentum</span>
          <Link className={styles.footerLink} href="/daily">
            The Momo Daily
          </Link>
          <Link className={styles.footerLink} href="/workspace">
            Have an invitation? Sign in
          </Link>
        </footer>
      </div>
    </div>
  );
}

/*
 * The paper cutout look, previewed with `?look=paper`. Scoped entirely under
 * [data-treatment="paper"] (paper.css) so it wins over the `.dark` class the
 * theme provider pins on this route (theme-provider.tsx:14) — nothing here
 * reads a `--momentum-*`/shadcn dark-mode token, only `--paper-*` ones.
 */
function PaperLanding() {
  const motion = useIntroMotion();
  // Momo's intro plays once, then his Hello loop stays pinned in front of
  // the moving collage for as long as the page is open.
  const [introDone, setIntroDone] = useState(false);
  return (
    <div className={styles.paperPage} data-treatment="paper">
      <div className={styles.paperIntro}>
        <ScrapbookBackdrop motion={motion} tone="cream" />
      </div>
      <div
        className={`${styles.paperBlueprintB} paper-torn-alt`}
        aria-hidden="true"
      />

      <div className={styles.paperShell}>
        <header className={styles.paperHeader}>
          <Link className={styles.paperWordmark} href="/">
            <MomoBotLockup />
          </Link>
          <Link className={styles.paperSignIn} href="/workspace">
            Sign in
          </Link>
        </header>

        <main className={styles.paperHero}>
          <p className={`${styles.paperScrap} m-voice-annotation`}>
            still invite only, for now
          </p>

          <h1 className={styles.paperTitle}>
            <span className="m-voice-serif">Say hello to</span>
            <CutPaper
              word="MomoBot"
              className={`${styles.paperCutWord} m-voice-cut-paper`}
              letterClassName={styles.paperCutLetter}
            />
          </h1>

          <p className={`${styles.paperLede} m-voice-body`}>
            MomoBot is a private workspace where a team of agents takes on real
            work and leaves a record you can check. You were invited here
            because someone wants you in the room.
          </p>

          <div className={styles.paperActions}>
            <Link className={styles.paperPrimary} href="/workspace">
              Enter the workspace
            </Link>
            <Link
              className={styles.paperSecondary}
              href="/workspace/command-center"
            >
              Open Command Center
            </Link>
          </div>

          <ul className={styles.paperCards}>
            {CAPABILITIES.map((item, index) => (
              <li
                key={item.key}
                // "pinned" / "sheet" / "paper-torn(-alt)" are paper.css's
                // own (unscoped) hooks — literal strings, not CSS-module
                // classes, so its [data-treatment="paper"] .pinned::before
                // etc. selectors still match.
                className={`${styles.paperCard} pinned sheet ${
                  index % 2 === 0 ? "paper-torn" : "paper-torn-alt"
                }`}
                style={{
                  transform: `translateY(${CARD_OFFSETS[index] ?? 0}px)`,
                }}
              >
                <span className={`${styles.paperCardKey} m-voice-label`}>
                  {item.key}
                </span>
                <p className={`${styles.paperCardBody} m-voice-body`}>
                  {item.body}
                </p>
              </li>
            ))}
          </ul>

          <div className={styles.paperMomos} aria-hidden="true">
            <MomoFilm
              key={introDone ? "hello" : "intro"}
              name={introDone ? "momo-hello" : "momo-intro"}
              live={motion.live}
              loop={introDone}
              onEnded={() => setIntroDone(true)}
            />
          </div>
        </main>

        <footer className={styles.paperFooter}>
          <span className="m-voice-body">
            © {new Date().getFullYear()} Momentum
          </span>
          <Link className={styles.paperFooterLink} href="/daily">
            The Momo Daily
          </Link>
          <Link className={styles.paperFooterLink} href="/workspace">
            Have an invitation? Sign in
          </Link>
        </footer>
      </div>
    </div>
  );
}
