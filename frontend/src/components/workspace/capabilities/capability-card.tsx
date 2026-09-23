"use client";

import { PuzzleIcon, SparklesIcon, type LucideIcon } from "lucide-react";

import { pageStyles } from "@/components/workspace/page-body";
import { cn } from "@/lib/utils";

// Quiet tints for the current treatment; the paper treatment renders every
// mark on cream (see .mark), because colour there carries state only.
const tones = [
  "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  "bg-stone-100 text-stone-700 dark:bg-stone-900 dark:text-stone-300",
  "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
];

export function CapabilityIcon({
  name,
  skill = false,
  icon: CustomIcon,
}: {
  name: string;
  skill?: boolean;
  icon?: LucideIcon;
}) {
  const tone =
    [...name].reduce((value, char) => value + char.charCodeAt(0), 0) %
    tones.length;
  const Icon = CustomIcon ?? (skill ? SparklesIcon : PuzzleIcon);
  return (
    <div
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg",
        tones[tone],
        pageStyles.mark,
      )}
    >
      <Icon className="size-5" strokeWidth={1.6} />
    </div>
  );
}
