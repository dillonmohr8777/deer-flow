"use client";

import { type ComponentProps, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, pageStyles } from "@/components/workspace/page-body";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import type { PluginAction } from "./plugin-action";
import { pluginCategories, type PluginCategory } from "./plugin-catalog";

export type PluginDirectoryEntry = {
  id: string;
  category: PluginCategory;
  search: string;
  installed: boolean;
  /** A setup reference, not an integration MomoBot can configure itself. */
  guide?: boolean;
  node: ReactNode;
};

/**
 * One visible weight per kind of action: Connect is the call to act (royal
 * word on a royal hairline), Configure is an ordinary outlined control, and
 * Details or a setup guide only read, so they stay quiet.
 */
export function PluginActionButton({
  action,
  className,
  ...props
}: { action: PluginAction } & ComponentProps<typeof Button>) {
  const quiet = action === "details" || action === "guide";
  return (
    <Button
      size="sm"
      variant={quiet ? "ghost" : "outline"}
      data-action={action}
      className={cn(
        "h-9 px-3 text-[13px] font-semibold",
        action === "connect" && "border-primary text-primary",
        quiet &&
          "text-muted-foreground hover:text-foreground underline-offset-4 hover:underline",
        className,
      )}
      {...props}
    />
  );
}

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
  // Connected tools lead: they are what the agents can use today. What is
  // left follows by category, integrations MomoBot configures before guides.
  const connected = visible
    .filter((entry) => entry.installed)
    .sort(
      (a, b) =>
        pluginCategories.indexOf(a.category) -
        pluginCategories.indexOf(b.category),
    );
  const available = visible.filter((entry) => !entry.installed);
  return (
    <div className="space-y-10">
      {connected.length > 0 && (
        <section aria-labelledby="plugin-group-connected">
          <div className="flex items-baseline gap-3 pb-3">
            <h2 id="plugin-group-connected" className="text-lg font-semibold">
              {copy.connectedSection}
            </h2>
            <span
              className={cn(pageStyles.figure, "text-muted-foreground text-sm")}
            >
              {connected.length}
            </span>
            <span className="text-muted-foreground ml-auto hidden text-[13px] lg:block">
              {copy.connectedHint}
            </span>
          </div>
          <div
            data-testid="plugin-connected"
            className={cn(
              "bg-card grid grid-cols-1 gap-x-10 rounded-md border px-3 sm:px-4 md:px-6 lg:grid-cols-2",
              pageStyles.sheet,
              pageStyles.rows,
              "[&>*:last-child]:border-b-0",
              "lg:[&>*:nth-child(odd):nth-last-child(2)]:border-b-0",
            )}
          >
            {connected.map((entry) => (
              <div key={entry.id} className="min-w-0 border-b">
                {entry.node}
              </div>
            ))}
          </div>
        </section>
      )}
      {available.length > 0 && (
        <div className="space-y-9">
          {connected.length > 0 && (
            <p className={pageStyles.eyebrow}>{copy.availableSection}</p>
          )}
          {pluginCategories.map((key) => {
            const items = available
              .filter((entry) => entry.category === key)
              .sort((a, b) => Number(!!a.guide) - Number(!!b.guide));
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
      )}
    </div>
  );
}
