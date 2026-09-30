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

/**
 * When a scheduled run happens, in words a person plans by: "Today, 11:30 PM",
 * "Tomorrow, 8:50 AM", a weekday within the week ("Sat, 2:00 PM"), otherwise
 * the day ("Nov 9, 10:00 AM") with the year only when it differs. Days are
 * calendar days, not 24-hour windows. Returns null for a missing or invalid
 * timestamp so callers can name the gap.
 */
export function formatScheduleTime(
  date: Date | string | number | null | undefined,
  locale: string,
  now: Date = new Date(),
): string | null {
  if (date === null || date === undefined || date === "") return null;
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) return null;
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  const time = new Intl.DateTimeFormat(intlLocale, {
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
  const midnight = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  // Round, so a DST day (23 or 25 hours) still counts as one day.
  const days = Math.round((midnight(parsed) - midnight(now)) / 86_400_000);
  let day: string;
  if (Math.abs(days) <= 1) {
    day = new Intl.RelativeTimeFormat(intlLocale, { numeric: "auto" }).format(
      days,
      "day",
    );
    day = day.charAt(0).toLocaleUpperCase(intlLocale) + day.slice(1);
  } else if (days > 1 && days < 7) {
    // Weekday only ahead: an overdue "Fri" would read as the coming Friday.
    day = new Intl.DateTimeFormat(intlLocale, { weekday: "short" }).format(
      parsed,
    );
  } else {
    day = new Intl.DateTimeFormat(intlLocale, {
      month: "short",
      day: "numeric",
      ...(parsed.getFullYear() === now.getFullYear()
        ? {}
        : { year: "numeric" as const }),
    }).format(parsed);
  }
  return intlLocale === "zh-CN" ? `${day} ${time}` : `${day}, ${time}`;
}
