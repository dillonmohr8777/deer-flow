"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type AuditEvent,
  type AuditEventFilters,
  loadAuditEvents,
} from "@/core/admin/audit-events";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { SettingsSection } from "./settings-section";

function formatTime(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

export function AuditSettingsPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const text = t.settings.audit;
  const canView = user?.system_role === "admin" && !isStaticWebsiteOnly();

  const [appliedFilters, setAppliedFilters] = useState<AuditEventFilters>({});
  const [actionPrefix, setActionPrefix] = useState("");
  const [actor, setActor] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);

  const queryKey = ["audit-events", user?.id, appliedFilters];
  const page = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const result = await loadAuditEvents(appliedFilters, signal);
      setEvents(result.events);
      setCursor(result.next_cursor ?? undefined);
      return result;
    },
    enabled: canView,
  });

  function applyFilters() {
    setAppliedFilters({
      actionPrefix: actionPrefix.trim() || undefined,
      actor: actor.trim() || undefined,
      since: since ? new Date(since).toISOString() : undefined,
      until: until ? new Date(until).toISOString() : undefined,
    });
  }

  function clearFilters() {
    setActionPrefix("");
    setActor("");
    setSince("");
    setUntil("");
    setAppliedFilters({});
  }

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const result = await loadAuditEvents({ ...appliedFilters, cursor });
      setEvents((prev) => [...prev, ...result.events]);
      setCursor(result.next_cursor ?? undefined);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <SettingsSection title={text.title} description={text.description}>
      {!canView ? (
        <p>{text.adminOnly}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <label className="block space-y-1">
              <span className="text-sm">{text.filterActionPrefix}</span>
              <Input
                value={actionPrefix}
                placeholder="auth.login."
                onChange={(e) => setActionPrefix(e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm">{text.filterActor}</span>
              <Input value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label className="block space-y-1">
              <span className="text-sm">{text.filterSince}</span>
              <Input
                type="datetime-local"
                value={since}
                onChange={(e) => setSince(e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm">{text.filterUntil}</span>
              <Input
                type="datetime-local"
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
            </label>
            <Button onClick={applyFilters}>{text.apply}</Button>
            <Button variant="outline" onClick={clearFilters}>
              {text.clear}
            </Button>
          </div>

          {page.isLoading && <p role="status">{text.loading}</p>}
          {page.error && (
            <div role="alert">
              <p>{text.failed}</p>
            </div>
          )}
          {!page.isLoading && !page.error && events.length === 0 && (
            <p>{text.empty}</p>
          )}

          {events.length > 0 && (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th className="p-2 font-medium">{text.columnTime}</th>
                    <th className="p-2 font-medium">{text.columnAction}</th>
                    <th className="p-2 font-medium">{text.columnActor}</th>
                    <th className="p-2 font-medium">{text.columnTarget}</th>
                    <th className="p-2 font-medium">{text.columnOutcome}</th>
                    <th className="p-2 font-medium">{text.columnIp}</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id} className="border-b last:border-0">
                      <td className="p-2 whitespace-nowrap">
                        {formatTime(event.occurred_at)}
                      </td>
                      <td className="p-2 font-mono text-xs">{event.action}</td>
                      <td className="p-2">{event.actor_user_id ?? "none"}</td>
                      <td className="p-2">
                        {event.target_type
                          ? `${event.target_type}:${event.target_id ?? "?"}`
                          : "none"}
                      </td>
                      <td className="p-2">{event.outcome}</td>
                      <td className="p-2">{event.ip ?? "none"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {cursor && (
            <Button
              variant="outline"
              disabled={loadingMore}
              onClick={() => void loadMore()}
            >
              {text.loadMore}
            </Button>
          )}
        </div>
      )}
    </SettingsSection>
  );
}
