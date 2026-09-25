import { formatDistanceToNow } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

function getDateFnsLocale(locale: Locale) {
  switch (locale) {
    case "zh-CN":
      return dateFnsZhCN;
    case "en-US":
    default:
      return dateFnsEnUS;
  }
}

/** A calendar day for lists and ledgers: "Sep 21, 2026", or null if unknown. */
export function formatDay(
  date: Date | string | number,
  locale: string,
): string | null {
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(parsed);
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const effectiveLocale =
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale();
  // Guard against invalid/empty timestamps (e.g. a backend returning "" for
  // lastUpdated when there are no memories) -- date-fns would throw
  // "Invalid time value" on `new Date("")`. Return a neutral placeholder.
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return formatDistanceToNow(parsed, {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}

/**
 * A short stamp that tells similar rows apart: the time for today ("2:32 PM"),
 * the day for anything older ("Sep 21"), and the year only when it differs.
 * Returns null for a missing or invalid timestamp so callers can omit it.
 */
export function formatCompactStamp(
  date: Date | string | number | null | undefined,
  locale: string,
  now: Date = new Date(),
): string | null {
  if (date === null || date === undefined || date === "") return null;
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) return null;
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  if (parsed.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat(intlLocale, {
      hour: "numeric",
      minute: "2-digit",
    }).format(parsed);
  }
  return new Intl.DateTimeFormat(intlLocale, {
    month: "short",
    day: "numeric",
    ...(parsed.getFullYear() === now.getFullYear()
      ? {}
      : { year: "numeric" as const }),
  }).format(parsed);
}
