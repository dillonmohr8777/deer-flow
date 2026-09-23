"use client";

import { ArrowLeftIcon, ChevronRightIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { PluginRow } from "./plugin-directory";

export function ExtensionGallery({ query = "" }: { query?: string }) {
  const { t } = useI18n();
  const publicQuery = useFrontendExtensions();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = params.get("extension");
  const entries = publicQuery.data ?? [];
  const source = publicQuery;
  function select(namespace?: string) {
    const next = new URLSearchParams(params);
    next.set("tab", "extensions");
    if (namespace) next.set("extension", namespace);
    else next.delete("extension");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }
  if (source.isPending) return <WorkingState label={t.extensions.loading} />;
  if (source.isError)
    return (
      <ErrorState
        message={t.extensions.unavailable}
        action={
          <Button variant="outline" onClick={() => void source.refetch()}>
            {t.extensions.retry}
          </Button>
        }
      />
    );
  const reload = (
    <Button variant="outline" onClick={() => window.location.reload()}>
      {t.extensions.reloadAll}
    </Button>
  );
  if (selected) {
    const entry = entries.find((item) => item.namespace === selected);
    return (
      <div className="space-y-6">
        {reload}
        <Button variant="ghost" onClick={() => select()}>
          <ArrowLeftIcon />
          {t.extensions.all}
        </Button>
        {!entry ? (
          <p>{t.extensions.notInstalled}</p>
        ) : (
          <div className="max-w-3xl space-y-4">
            <h2 className="text-2xl font-semibold">{entry.title}</h2>
            <p className="text-muted-foreground">{entry.description}</p>
            <p>
              {entry.settings.enabled === true
                ? t.extensions.enabledManaged
                : t.extensions.disabledManaged}
            </p>
          </div>
        )}
      </div>
    );
  }
  const visible = entries.filter((entry) =>
    `${entry.title} ${entry.description}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="space-y-5">
      {reload}
      <p className="text-muted-foreground text-sm">
        {t.extensions.deploymentHint}
      </p>
      <div className={cn("grid gap-x-10 md:grid-cols-2", pageStyles.rows)}>
        {visible.map((entry) => {
          const loaded = publicQuery.data?.find(
            (item) => item.namespace === entry.namespace,
          );
          const Icon = extensionIcon(loaded?.extension?.icon);
          return (
            <div key={entry.namespace} className="min-w-0 border-b">
              <PluginRow
                name={entry.title}
                description={entry.description}
                icon={
                  <div className="bg-muted flex size-10 shrink-0 items-center justify-center rounded-lg border">
                    <Icon className="size-5" />
                  </div>
                }
                label={
                  loaded?.error ? (
                    <StatusTag tone="unknown">
                      {t.extensions.moduleUnavailable}
                    </StatusTag>
                  ) : entry.settings.enabled === true ? (
                    <StatusTag tone="ok">{t.capabilities.enabled}</StatusTag>
                  ) : (
                    <StatusTag tone="idle">{t.capabilities.disabled}</StatusTag>
                  )
                }
                onDetails={() => select(entry.namespace)}
                detailsLabel={t.extensions.view(entry.title)}
              >
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t.extensions.open(entry.title)}
                  onClick={() => select(entry.namespace)}
                >
                  <ChevronRightIcon />
                </Button>
              </PluginRow>
            </div>
          );
        })}
      </div>
      {!visible.length && (
        <div role="status">
          <EmptyState momo="engineer">{t.extensions.noResults}</EmptyState>
        </div>
      )}
    </div>
  );
}
