"use client";

import { useSearchParams } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function WelcomeDescription({ children }: { children: string }) {
  return (
    <p className="max-w-full text-wrap break-words whitespace-pre-line">
      {children}
    </p>
  );
}

/*
 * No emoji identity (DESIGN.md) and no gold Ultra gradient: #e3a812 on the
 * cream canvas measured about 2:1, under even the 3:1 large-text floor. The
 * composer already shows the active mode, so the greeting stays plain ink.
 */
export function Welcome({
  className,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const skill = searchParams.get("mode") === "skill";
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-full flex-col items-center justify-center gap-2 px-4 py-4 text-center sm:px-8",
        className,
      )}
    >
      <h2 className="max-w-full text-2xl font-bold">
        {skill ? t.welcome.createYourOwnSkill : t.welcome.greeting}
      </h2>
      <div className="text-muted-foreground max-w-full text-sm">
        <WelcomeDescription>
          {skill
            ? t.welcome.createYourOwnSkillDescription
            : t.welcome.description}
        </WelcomeDescription>
      </div>
    </div>
  );
}
