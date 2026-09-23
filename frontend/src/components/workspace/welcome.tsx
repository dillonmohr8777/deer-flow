"use client";

import { useSearchParams } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/*
 * The empty thread: the lead Momo, small, and one Fraunces line. The starter
 * prompts sit under the composer (input-box.tsx). No emoji identity and no
 * gold text (DESIGN.md); the composer already shows the active mode.
 * The avatar is referenced by path: its canon drawing is owned elsewhere.
 */
export function Welcome({
  className,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  if (searchParams.get("mode") === "skill") {
    return (
      <div
        className={cn(
          "mx-auto flex w-full max-w-full flex-col items-center justify-center gap-2 px-4 py-4 text-center sm:px-8",
          className,
        )}
      >
        <h2 className="max-w-full text-2xl font-bold">
          {t.welcome.createYourOwnSkill}
        </h2>
        <p className="text-muted-foreground max-w-full text-sm text-wrap break-words whitespace-pre-line">
          {t.welcome.createYourOwnSkillDescription}
        </p>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-full flex-col items-center justify-center gap-3 px-4 pb-4 text-center sm:px-8",
        className,
      )}
    >
      <img
        src="/momentum/momos/lead.svg"
        alt=""
        aria-hidden="true"
        width={56}
        height={56}
        className="size-14 shrink-0"
      />
      <h2 className="max-w-full font-[family-name:var(--m-font-serif)] text-[1.625rem] leading-tight font-normal tracking-[-0.01em] text-balance sm:text-[2rem]">
        {t.welcome.greeting}
      </h2>
    </div>
  );
}
