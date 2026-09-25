"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon, CoinsIcon } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  formatTokenCount,
  selectHeaderTokenUsage,
  type TokenUsage,
} from "@/core/messages/usage";
import {
  getTokenUsageViewPreset,
  tokenUsagePreferencesFromPreset,
  type TokenUsagePreferences,
  type TokenUsageViewPreset,
} from "@/core/messages/usage-model";
import type { ContextUsage } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import { formatContextUsagePercentage } from "./context-usage-format";

interface TokenUsageIndicatorProps {
  threadId?: string;
  messages: Message[];
  pendingMessages?: Message[];
  backendUsage?: TokenUsage | null;
  contextUsage?: ContextUsage | null;
  enabled?: boolean;
  preferences: TokenUsagePreferences;
  onPreferencesChange: (preferences: TokenUsagePreferences) => void;
  className?: string;
}

export function TokenUsageIndicator({
  threadId,
  messages,
  pendingMessages,
  backendUsage,
  contextUsage,
  enabled = false,
  preferences,
  onPreferencesChange,
  className,
}: TokenUsageIndicatorProps) {
  const { t } = useI18n();

  const usage = useMemo(
    () =>
      selectHeaderTokenUsage({
        backendUsage: threadId ? backendUsage : null,
        messages,
        pendingMessages,
      }),
    [backendUsage, messages, pendingMessages, threadId],
  );
  const preset = getTokenUsageViewPreset(preferences);
  // A percentage without a known window size has no denominator: hide it.
  const contextPercentage = contextUsage?.maxContextTokens
    ? formatContextUsagePercentage(contextUsage.percentage)
    : null;
  // A chat with no reply yet shows no figure: a bare dash reads as a value.
  // Once a reply exists, missing usage says so instead of staying quiet.
  const usageMissing =
    !usage &&
    messages.some((message) => message.type === "ai") &&
    !pendingMessages?.length;
  const headerFigure = preferences.headerTotal
    ? usage
      ? t.tokenUsage.figure(formatTokenCount(usage.totalTokens))
      : usageMissing
        ? t.tokenUsage.headerUnavailable
        : null
    : t.tokenUsage.presets[presetKeyToTranslationKey(preset)];

  if (!enabled) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className={cn(
            "text-muted-foreground bg-background/70 hover:bg-background/90 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-sm font-normal",
            className,
          )}
        >
          <CoinsIcon size={14} />
          {/* Below sm the pill collapses to its icon so the thread title fits.
              Each figure names its own unit: a bare "0%" hides what it
              measures. */}
          {headerFigure ? (
            <>
              {!preferences.headerTotal && (
                <span className="sr-only">{t.tokenUsage.label}: </span>
              )}
              <span className="sr-only font-semibold tabular-nums sm:not-sr-only">
                {headerFigure}
              </span>
            </>
          ) : (
            <span className="sr-only sm:not-sr-only">{t.tokenUsage.label}</span>
          )}
          {contextPercentage != null && (
            // not-sr-only zeroes padding, so the divider sits on an inner span.
            <span className="sr-only sm:not-sr-only">
              <span className="border-l pl-1.5 tabular-nums">
                {t.contextUsage.headerFigure(contextPercentage)}
              </span>
            </span>
          )}
          <ChevronDownIcon className="hidden size-3 sm:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" className="w-80">
        <DropdownMenuLabel>{t.tokenUsage.title}</DropdownMenuLabel>
        <div className="px-2 py-1 text-[13px]">
          {usage ? (
            <div className="space-y-1">
              <div className="flex justify-between gap-4">
                <span>{t.tokenUsage.input}</span>
                <span className="font-mono">
                  {formatTokenCount(usage.inputTokens)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span>{t.tokenUsage.output}</span>
                <span className="font-mono">
                  {formatTokenCount(usage.outputTokens)}
                </span>
              </div>
              <div className="border-t pt-1">
                <div className="flex justify-between gap-4">
                  <span>{t.tokenUsage.total}</span>
                  <span className="font-mono font-medium">
                    {formatTokenCount(usage.totalTokens)}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground leading-snug">
              {t.tokenUsage.unavailable}
            </p>
          )}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t.contextUsage.title}</DropdownMenuLabel>
        <ContextWindowReading contextUsage={contextUsage} />
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t.tokenUsage.view}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preset}
          onValueChange={(value) =>
            onPreferencesChange(
              tokenUsagePreferencesFromPreset(value as TokenUsageViewPreset),
            )
          }
        >
          {(
            ["off", "summary", "per_turn", "debug"] as TokenUsageViewPreset[]
          ).map((value) => {
            const translationKey = presetKeyToTranslationKey(value);
            return (
              <DropdownMenuRadioItem key={value} value={value}>
                <div className="grid gap-0.5">
                  <span>{t.tokenUsage.presets[translationKey]}</span>
                  <span className="text-muted-foreground text-xs">
                    {t.tokenUsage.presetDescriptions[translationKey]}
                  </span>
                </div>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <div className="text-muted-foreground px-2 py-2 text-xs leading-relaxed">
          {t.tokenUsage.note}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ContextWindowReading({
  contextUsage,
}: {
  contextUsage?: ContextUsage | null;
}) {
  const { t } = useI18n();
  const percentage = formatContextUsagePercentage(contextUsage?.percentage);
  const max = contextUsage?.maxContextTokens;
  if (percentage == null || !max) {
    return (
      <p className="text-muted-foreground px-2 pb-2 text-[13px] leading-snug">
        {t.contextUsage.unavailable}
      </p>
    );
  }
  const filled = Math.min(100, Math.max(0, Number(percentage)));
  return (
    <div className="grid gap-1.5 px-2 pb-2 text-[13px]">
      <div
        role="meter"
        aria-label={t.contextUsage.title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={filled}
        aria-valuetext={t.contextUsage.badgeAriaLabel(percentage)}
        className="bg-muted h-1.5 overflow-hidden rounded-[1px] border"
      >
        <div className="bg-primary h-full" style={{ width: `${filled}%` }} />
      </div>
      <span className="font-semibold tabular-nums">
        {t.contextUsage.measured(
          contextUsage.tokenCount.toLocaleString(),
          max.toLocaleString(),
          percentage,
        )}
      </span>
      <span className="text-muted-foreground leading-snug">
        {t.contextUsage.explanation}
      </span>
    </div>
  );
}

function presetKeyToTranslationKey(preset: TokenUsageViewPreset) {
  switch (preset) {
    case "per_turn":
      return "perTurn" as const;
    default:
      return preset;
  }
}
