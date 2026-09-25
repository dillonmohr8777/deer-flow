import { cn } from "@/lib/utils";

import styles from "./comic.module.css";

/**
 * The MomoBot logo block: the product name in the display face on a royal
 * plate, with an orange stripe and Momo's antenna. It is the front door's
 * headline word, and the element the comic intro stamps onto the slab and
 * lands here. Screen readers get the one word; the plate, stripe and antenna
 * are decoration.
 */
export function MomoBotBlock({ className }: { className?: string }) {
  return (
    <span className={cn(styles.block, className)} data-comic-block="">
      <span className={styles.plate} data-comic-part="plate" aria-hidden="true">
        <span className={styles.stripe} data-comic-part="stripe" />
      </span>
      <span
        className={styles.antenna}
        data-comic-part="antenna"
        aria-hidden="true"
      />
      <span className={styles.word} data-comic-part="word">
        MomoBot
      </span>
    </span>
  );
}
