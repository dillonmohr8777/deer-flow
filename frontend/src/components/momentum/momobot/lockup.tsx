import Image from "next/image";

import { cn } from "@/lib/utils";

import styles from "./momobot.module.css";

/*
 * MomoBot is the product; Momentum is the company that makes it. Every front
 * door page carries both names. The inline lockup keeps the product name,
 * "by" and the unchanged Momentum wordmark artwork on one line; the paper
 * front door splits them (MomoBotWordmark on the left, MomentumMark at the
 * far right) so the product leads and the maker signs off in the corner.
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

/** The product name alone, set large: the front door's focal type. */
export function MomoBotWordmark({ className }: { className?: string }) {
  return (
    <span className={cn(styles.productName, "m-voice-serif-bold", className)}>
      MomoBot
    </span>
  );
}

/** "by" and the authentic Momentum wordmark, placed apart from the product. */
export function MomentumMark({ className }: { className?: string }) {
  return (
    <span className={cn(styles.maker, className)}>
      <span className={styles.makerBy}>by</span>
      <Image
        className={styles.makerWordmark}
        src="/momentum/wordmark.png"
        alt="Momentum"
        width={93}
        height={20}
        priority
      />
    </span>
  );
}
