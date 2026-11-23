import { type Metadata } from "next";
import Link from "next/link";

import styles from "@/components/momentum/daily/daily.module.css";
import { getSiteUrl, MOMO_DAILY_NAME } from "@/core/momo-daily";
import { isSignedIn } from "@/core/momo-daily/load";

export function generateMetadata(): Metadata {
  return {
    metadataBase: new URL(getSiteUrl()),
    title: {
      default: `${MOMO_DAILY_NAME}: the latest in AI from Momentum`,
      template: `%s | ${MOMO_DAILY_NAME}`,
    },
  };
}

export default async function DailyLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // /daily lives outside the workspace shell, and the desktop app has no
  // browser back button, so the way out is always on the page.
  const signedIn = await isSignedIn();
  return (
    <div className={styles.canvas} data-treatment="paper">
      <Link className={styles.exit} href={signedIn ? "/workspace" : "/"}>
        &larr; {signedIn ? "Back to MomoBot" : "Momentum home"}
      </Link>
      {children}
    </div>
  );
}
