"use client";

import { useSearchParams } from "next/navigation";

import { MomoFilm } from "@/components/momentum/momo-film";
import { useWorkspaceAppearance } from "@/components/workspace/command-center/appearance-provider";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/*
 * The empty thread: Momo's Pencil film as a pinned photo, and one Fraunces line. The starter
 * prompts sit under the composer (input-box.tsx). No emoji identity and no
 * gold text (DESIGN.md); the composer already shows the active mode.
 * The film is referenced by name: public/momentum/films/momo-pencil.*
 */
export function Welcome({
  className,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const { motionOn } = useWorkspaceAppearance();
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
      <span className="size-28 shrink-0 -rotate-2 overflow-hidden border-4 border-[#fbf8f1] shadow-[0_10px_24px_-10px_rgb(16_30_63/0.5)]">
        <MomoFilm
          name="momo-pencil"
          live={motionOn}
          className="size-full object-cover"
        />
      </span>
      <h2 className="max-w-full font-[family-name:var(--m-font-serif)] text-[1.625rem] leading-tight font-normal tracking-[-0.01em] text-balance sm:text-[2rem]">
        {t.welcome.greeting}
      </h2>
    </div>
  );
}
