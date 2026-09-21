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
 */

import Image from "next/image";
import Link from "next/link";

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
        Every dispatch is <strong>recorded</strong> — inputs, model, tokens and
        outcome — so work can be replayed rather than retold.
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

export function MomentumLanding() {
  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <Link className={styles.wordmark} href="/">
            <Image
              className={styles.wordmarkImage}
              src="/momentum/wordmark.png"
              alt="Momentum"
              width={132}
              height={24}
              priority
            />
            <span className={styles.wordmarkNote}>Workspace</span>
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
              Momentum Workspace is a private environment where a team of agents
              takes on real work — research, build, review — and leaves a record
              you can check. You were invited here because someone wants you in
              the room.
            </p>
            <div className={styles.actions}>
              <Link className={styles.primary} href="/workspace">
                Enter the workspace
              </Link>
              <Link className={styles.secondary} href="/workspace/command-center">
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
          <Link className={styles.footerLink} href="/workspace">
            Have an invitation? Sign in
          </Link>
        </footer>
      </div>
    </div>
  );
}
