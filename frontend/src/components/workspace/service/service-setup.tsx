"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { useServiceTiersEnabled } from "@/core/features";
import {
  TIER_COPY,
  applyOnboarding,
  getServiceSettings,
  previewOnboarding,
  updateServiceSettings,
  type PlanPreview,
  type ServiceSettings,
  type ServiceTier,
} from "@/core/service-tiers/api";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";

/** Service settings and the one-hour onboarding call, for the workspace you are in. */
export function ServiceSetup() {
  const { enabled, isLoading } = useServiceTiersEnabled();
  const workspaces = useWorkspaceSelection();
  const workspaceId = workspaces.data?.active_workspace_id ?? null;
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <main className="h-full min-w-0 overflow-y-auto p-4 md:p-6">
          <header className="mb-6">
            <h1 className="text-2xl font-semibold">Service setup</h1>
            <p className="text-muted-foreground text-sm">
              Pick how this client is served, then run the onboarding call.
            </p>
          </header>
          {isLoading || workspaces.isLoading ? (
            <p role="status">Loading…</p>
          ) : !enabled ? (
            <p className="text-muted-foreground">
              Service tiers are turned off for this MomoBot.
            </p>
          ) : !workspaceId ? (
            <p className="text-muted-foreground">
              Switch to the client&apos;s workspace first (top of the sidebar),
              then come back here.
            </p>
          ) : (
            <WorkspaceService key={workspaceId} workspaceId={workspaceId} />
          )}
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function WorkspaceService({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient();
  const key = ["service-settings", workspaceId];
  const settings = useQuery({
    queryKey: key,
    queryFn: () => getServiceSettings(workspaceId),
    retry: false,
  });
  const save = (next: ServiceSettings) => queryClient.setQueryData(key, next);
  if (settings.isLoading) return <p role="status">Loading…</p>;
  if (settings.isError || !settings.data) {
    return <p role="alert">{settings.error?.message}</p>;
  }
  return (
    <div className="max-w-3xl space-y-8">
      <SettingsForm
        key={settings.data.version}
        settings={settings.data}
        onSaved={save}
      />
      <Onboarding settings={settings.data} onApplied={save} />
    </div>
  );
}

function SettingsForm({
  settings,
  onSaved,
}: {
  settings: ServiceSettings;
  onSaved: (next: ServiceSettings) => void;
}) {
  const { user } = useAuth();
  const [tier, setTier] = useState<ServiceTier | "">(
    settings.service_tier ?? "",
  );
  const [bookingUrl, setBookingUrl] = useState(settings.booking_url ?? "");
  const [soldByMe, setSoldByMe] = useState(
    Boolean(user && settings.sold_by_user_id === user.id),
  );
  const soldByOther = Boolean(
    settings.sold_by_user_id && settings.sold_by_user_id !== user?.id,
  );
  const mutation = useMutation({
    mutationFn: () =>
      updateServiceSettings(settings.workspace_id, {
        service_tier: tier === "" ? null : tier,
        booking_url:
          tier === "software" && bookingUrl.trim() ? bookingUrl : null,
        sold_by_user_id: soldByMe
          ? (user?.id ?? null)
          : soldByOther
            ? settings.sold_by_user_id
            : null,
        expected_version: settings.version,
      }),
    onSuccess: onSaved,
  });
  const disabled = !settings.can_edit || mutation.isPending;
  return (
    <section aria-labelledby="service-settings" className="space-y-4">
      <h2 id="service-settings" className="text-lg font-semibold">
        How {settings.workspace_name} is served
      </h2>
      {!settings.can_edit && (
        <p className="text-muted-foreground text-sm">
          Only a workspace owner or admin can change this.
        </p>
      )}
      <fieldset className="space-y-2" disabled={disabled}>
        <legend className="sr-only">Service tier</legend>
        <label className="flex gap-3 rounded border p-3">
          <input
            type="radio"
            name="tier"
            checked={tier === ""}
            onChange={() => setTier("")}
          />
          <span>
            <span className="font-medium">Not set</span>
            <span className="text-muted-foreground block text-sm">
              Everything works the way it does today.
            </span>
          </span>
        </label>
        {settings.tiers.map((value) => (
          <label key={value} className="flex gap-3 rounded border p-3">
            <input
              type="radio"
              name="tier"
              checked={tier === value}
              onChange={() => setTier(value)}
            />
            <span>
              <span className="font-medium">{TIER_COPY[value].name}</span>
              <span className="text-muted-foreground block text-sm">
                {TIER_COPY[value].summary}
              </span>
            </span>
          </label>
        ))}
      </fieldset>
      {tier === "software" && (
        <label className="block space-y-1">
          <span className="text-sm font-medium">
            Booking link for the client (optional)
          </span>
          <Input
            type="url"
            placeholder="https://"
            value={bookingUrl}
            disabled={disabled}
            onChange={(event) => setBookingUrl(event.target.value)}
          />
          <span className="text-muted-foreground block text-sm">
            Shows a &quot;Book a call&quot; button in the client&apos;s inbox.
          </span>
        </label>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={soldByMe}
          disabled={disabled}
          onChange={(event) => setSoldByMe(event.target.checked)}
        />
        I sold this client
        {soldByOther && !soldByMe ? " (now: another teammate)" : ""}
      </label>
      {mutation.isError && <p role="alert">{mutation.error.message}</p>}
      <Button disabled={disabled} onClick={() => mutation.mutate()}>
        {mutation.isPending ? "Saving…" : "Save"}
      </Button>
    </section>
  );
}

function Onboarding({
  settings,
  onApplied,
}: {
  settings: ServiceSettings;
  onApplied: (next: ServiceSettings) => void;
}) {
  const [name, setName] = useState(settings.workspace_name);
  const [contract, setContract] = useState("");
  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const preview = useMutation({
    mutationFn: () => previewOnboarding(settings.workspace_id, contract),
    onSuccess: (result) => {
      setPlan(result);
      setSkipped(new Set());
    },
  });
  const apply = useMutation({
    mutationFn: () =>
      applyOnboarding(settings.workspace_id, {
        contract_text: contract,
        expected_version: settings.version,
        workspace_name: name.trim() || null,
        items: (plan?.items ?? [])
          .filter((_, index) => !skipped.has(index))
          .map(({ title, cadence, kind }) => ({ title, cadence, kind })),
        timezone:
          Intl.DateTimeFormat().resolvedOptions().timeZone ||
          "America/New_York",
      }),
    onSuccess: onApplied,
  });
  const done = settings.onboarding;
  if (done) {
    return (
      <section aria-labelledby="onboarding" className="space-y-3">
        <h2 id="onboarding" className="text-lg font-semibold">
          Onboarding call
        </h2>
        <p>
          Done on {new Date(done.applied_at).toLocaleDateString()}.{" "}
          {done.items.length} items are in the plan
          {done.tasks_paused ? ", and every task starts paused" : ""}.
        </p>
        <ul className="list-disc pl-5 text-sm">
          {done.items.map((item, index) => (
            <li key={index}>
              {item.title} ({item.cadence_label})
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground text-sm">
          Nothing runs, posts or sends until someone turns a task on in{" "}
          <Link className="underline" href="/workspace/scheduled-tasks">
            Scheduled tasks
          </Link>
          .
        </p>
      </section>
    );
  }
  const busy = preview.isPending || apply.isPending;
  const disabled = !settings.can_edit || busy;
  return (
    <section aria-labelledby="onboarding" className="space-y-5">
      <h2 id="onboarding" className="text-lg font-semibold">
        Onboarding call (about an hour)
      </h2>
      <div className="space-y-1">
        <h3 className="font-medium">1. Name the workspace</h3>
        <Input
          aria-label="Workspace name"
          value={name}
          maxLength={120}
          disabled={disabled}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="space-y-1">
        <h3 className="font-medium">2. Connect their accounts</h3>
        <p className="text-muted-foreground text-sm">
          With the client on the call, connect GA4, the website, email, Google
          Ads and their social accounts from Settings, under connections. Come
          back here when that is done.
        </p>
      </div>
      <div className="space-y-2">
        <h3 className="font-medium">3. Paste what we agreed to do</h3>
        <Textarea
          aria-label="Contract or scope of work"
          placeholder="Paste the contract or scope, for example: 4 blog posts per month, weekly social posts, monthly report."
          value={contract}
          rows={8}
          maxLength={50000}
          disabled={disabled}
          onChange={(event) => {
            setContract(event.target.value);
            setPlan(null);
          }}
        />
        <Button
          variant="outline"
          disabled={disabled || !contract.trim()}
          onClick={() => preview.mutate()}
        >
          {preview.isPending ? "Reading…" : "Show the plan"}
        </Button>
        {preview.isError && <p role="alert">{preview.error.message}</p>}
      </div>
      {plan && (
        <div className="space-y-3">
          <h3 className="font-medium">4. Check the plan</h3>
          {plan.items.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Momo could not find any work in that text. Add lines like
              &quot;weekly social posts&quot; and try again.
            </p>
          ) : (
            <ul className="divide-y rounded border">
              {plan.items.map((item, index) => (
                <li key={index} className="flex items-start gap-3 p-3">
                  <input
                    type="checkbox"
                    aria-label={`Include ${item.title}`}
                    checked={!skipped.has(index)}
                    disabled={disabled}
                    onChange={(event) =>
                      setSkipped((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.delete(index);
                        else next.add(index);
                        return next;
                      })
                    }
                  />
                  <span>
                    <span className="block">{item.title}</span>
                    <span className="text-muted-foreground text-sm">
                      {item.kind_label}, {item.cadence_label}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-muted-foreground text-sm">
            Creating the plan makes one scheduled task per item, all paused.
            Nothing runs, posts or sends until someone turns a task on.
          </p>
          {apply.isError && <p role="alert">{apply.error.message}</p>}
          <Button
            disabled={disabled || plan.items.length === skipped.size}
            onClick={() => apply.mutate()}
          >
            {apply.isPending ? "Creating…" : "Create the plan"}
          </Button>
        </div>
      )}
    </section>
  );
}
