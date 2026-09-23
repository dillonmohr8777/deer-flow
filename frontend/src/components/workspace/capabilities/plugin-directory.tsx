"use client";

import { type ReactNode } from "react";

import { EmptyState, pageStyles } from "@/components/workspace/page-body";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { pluginCategories, type PluginCategory } from "./plugin-catalog";

export type PluginDirectoryEntry = {
  id: string;
  category: PluginCategory;
  search: string;
  installed: boolean;
  node: ReactNode;
};

/**
 * One catalog line: mark, name with its state, one line of purpose, one
 * action. `label` is the state, usually a StatusTag.
 */
export function PluginRow({
  name,
  description,
  icon,
  label,
  onDetails,
  detailsLabel,
  children,
}: {
  name: string;
  description: string;
  icon: ReactNode;
  label?: ReactNode;
  onDetails?: () => void;
  detailsLabel?: string;
  children: ReactNode;
}) {
  return (
    <article className="flex h-full min-w-0 items-center gap-3.5 py-4">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <h3 className="text-sm font-bold">
            {onDetails ? (
              <button
                className="text-left underline-offset-4 hover:underline"
                onClick={onDetails}
                aria-label={detailsLabel}
              >
                {name}
              </button>
            ) : (
              name
            )}
          </h3>
          {label}
        </div>
        <p className="text-muted-foreground mt-1 line-clamp-2 text-[13px] leading-5">
          {description}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">{children}</div>
    </article>
  );
}

export function PluginDirectory({
  entries,
  query = "",
  category = "all",
  installedOnly = false,
}: {
  entries: PluginDirectoryEntry[];
  query?: string;
  category?: PluginCategory | "all";
  installedOnly?: boolean;
}) {
  const { t } = useI18n();
  const copy = t.capabilities.directory;
  const visible = entries.filter(
    (entry) =>
      (!installedOnly || entry.installed) &&
      (category === "all" || entry.category === category) &&
      entry.search.toLowerCase().includes(query.trim().toLowerCase()),
  );
  if (!visible.length)
    return (
      <div role="status">
        <EmptyState momo="research">{t.capabilities.noResults}</EmptyState>
      </div>
    );
  return (
    <div className="space-y-9">
      {pluginCategories.map((key) => {
        const items = visible.filter((entry) => entry.category === key);
        if (!items.length) return null;
        return (
          <section key={key} aria-labelledby={`plugin-group-${key}`}>
            <div className="flex items-baseline gap-3 border-b pb-3">
              <h2
                id={`plugin-group-${key}`}
                className="text-base font-semibold"
              >
                {copy.categories[key]}
              </h2>
              <span
                className={cn(
                  pageStyles.figure,
                  "text-muted-foreground text-xs",
                )}
              >
                {items.length}
              </span>
              <span className="text-muted-foreground ml-auto hidden text-xs lg:block">
                {copy.hints[key]}
              </span>
            </div>
            <div
              className={cn(
                "grid grid-cols-1 gap-x-10 lg:grid-cols-2",
                pageStyles.rows,
              )}
            >
              {items.map((entry) => (
                <div key={entry.id} className="min-w-0 border-b">
                  {entry.node}
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
