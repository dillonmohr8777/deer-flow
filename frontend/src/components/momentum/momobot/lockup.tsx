import Image from "next/image";

import { cn } from "@/lib/utils";

import styles from "./momobot.module.css";

/*
 * MomoBot is the product; Momentum is the company that makes it. The lockup
 * always carries both: the product name set in type, then "by" and the
 * unchanged Momentum wordmark artwork.
 */
export function MomoBotLockup({
  className,
  wordmarkClassName,
}: {
  className?: string;
  wordmarkClassName?: string;
}) {
  return (
    <span className={cn(styles.lockup, className)}>
      <span className={cn(styles.lockupName, "m-voice-serif-bold")}>
        MomoBot
      </span>
      <span className={styles.lockupBy}>by</span>
      <Image
        className={cn(styles.lockupWordmark, wordmarkClassName)}
        src="/momentum/wordmark.png"
        alt="Momentum"
        width={93}
        height={20}
        priority
      />
    </span>
  );
}
