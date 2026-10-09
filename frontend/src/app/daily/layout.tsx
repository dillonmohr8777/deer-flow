import { type Metadata } from "next";

import styles from "@/components/momentum/daily/daily.module.css";
import { MOMO_DAILY_NAME, SITE_URL } from "@/core/momo-daily";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${MOMO_DAILY_NAME}: the latest in AI from Momentum`,
    template: `%s | ${MOMO_DAILY_NAME}`,
  },
};

export default function DailyLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className={styles.canvas} data-treatment="paper">
      {children}
    </div>
  );
}
