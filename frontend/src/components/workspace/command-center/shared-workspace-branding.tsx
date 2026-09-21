"use client";

import { ImagePlus, RotateCcw } from "lucide-react";
import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";

import { preparePluginIcon } from "@/core/mcp/icon";
import {
  WorkspaceBrandingError,
  type BrandingDraft,
  type WorkspaceBranding,
} from "@/core/workspaces/api";
import type { useWorkspaceBranding } from "@/core/workspaces/hooks";

import styles from "./workspace-appearance.module.css";

type SharedState = ReturnType<typeof useWorkspaceBranding>;
const draftFrom = (data: WorkspaceBranding): BrandingDraft => ({
  brand_name: data.brand_name,
  logo: data.logo,
  treatment: data.treatment,
});

export function SharedWorkspaceBranding({ shared }: { shared: SharedState }) {
  if (shared.branding.isPending)
    return (
      <div className={styles.personalBrand}>
        <h3>Shared workspace brand</h3>
        <p role="status">Loading the workspace brand…</p>
      </div>
    );
  if (!shared.branding.data)
    return (
      <div className={styles.personalBrand}>
        <h3>Shared workspace brand</h3>
        <p className={styles.error} role="alert">
          The shared brand could not be loaded. Your personal appearance is
          still available.
        </p>
        <div className={styles.uploadActions}>
          <button type="button" onClick={() => void shared.branding.refetch()}>
            Try again
          </button>
        </div>
      </div>
    );
  return (
    <BrandingEditor
      key={shared.workspaceId}
      initial={shared.branding.data}
      shared={shared}
    />
  );
}

function BrandingEditor({
  initial,
  shared,
}: {
  initial: WorkspaceBranding;
  shared: SharedState;
}) {
  const [snapshot, setSnapshot] = useState(initial);
  const [draft, setDraft] = useState(() => draftFrom(initial));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [permissionLost, setPermissionLost] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const generation = useRef(0);
  const upload = useRef<HTMLInputElement>(null);
  const id = useId();
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );
  const busy = preparing || shared.save.isPending || shared.reset.isPending;
  const canEdit = Boolean(shared.branding.data?.can_edit) && !permissionLost;
  const stale =
    conflict ||
    (shared.branding.data?.version ?? snapshot.version) !== snapshot.version;
  const normalizedName = (draft.brand_name ?? "").trim();
  const nameLength = [...normalizedName].length;
  const draftLabel = normalizedName || snapshot.workspace_name;
  const invalidName =
    nameLength > 120 || /[\u0000-\u001f\u007f]/.test(draft.brand_name ?? "");
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftFrom(snapshot));

  function accept(data: WorkspaceBranding, message: string) {
    generation.current++;
    setPreparing(false);
    setSnapshot(data);
    setDraft(draftFrom(data));
    setConflict(false);
    setPermissionLost(false);
    setConfirmReset(false);
    setError(null);
    setNotice(message);
  }
  function fail(cause: unknown) {
    if (cause instanceof WorkspaceBrandingError) {
      if (cause.status === 412) setConflict(true);
      if (cause.status === 403 || cause.status === 404) setPermissionLost(true);
    }
    setError(
      cause instanceof Error
        ? cause.message
        : "The shared brand could not be saved. Your draft is still here.",
    );
  }
  async function chooseLogo(file: File) {
    const current = ++generation.current;
    setPreparing(true);
    setError(null);
    setNotice("");
    try {
      const logo = await preparePluginIcon(file);
      if (current === generation.current)
        setDraft((value) => ({ ...value, logo }));
    } catch {
      if (current === generation.current)
        setError(
          "Choose a valid PNG, JPEG or WebP smaller than 2 MB. SVG and remote URLs are not supported.",
        );
    } finally {
      if (current === generation.current) setPreparing(false);
    }
  }
  async function save() {
    if (busy || !canEdit || stale || invalidName) return;
    setError(null);
    setNotice("");
    try {
      accept(
        await shared.save.mutateAsync({
          draft: { ...draft, brand_name: normalizedName || null },
          version: snapshot.version,
        }),
        "Shared brand saved. Everyone in this workspace can see it.",
      );
    } catch (cause) {
      fail(cause);
    }
  }
  async function reset() {
    if (busy || !canEdit || stale) return;
    setError(null);
    setNotice("");
    try {
      accept(
        await shared.reset.mutateAsync(snapshot.version),
        "The workspace’s default brand has been restored.",
      );
    } catch (cause) {
      fail(cause);
    }
  }
  async function refresh() {
    const result = await shared.branding.refetch();
    if (result.data && !result.error)
      accept(
        result.data,
        "Latest shared branding loaded. You can edit this version.",
      );
    else fail(result.error);
  }
  return (
    <div className={styles.personalBrand} data-shared-branding="true">
      <h3>One brand. Your whole workspace.</h3>
      {shared.branding.error && (
        <p className={styles.error} role="alert">
          The saved brand could not be refreshed. Your draft is still here;
          saving will check its version.
        </p>
      )}
      <p>
        <strong className={styles.workspaceName}>
          {snapshot.workspace_name}
        </strong>{" "}
        · Shared with this workspace’s members.{" "}
        {canEdit
          ? "Changes go live for the team when you save."
          : "Only a workspace owner or admin can edit this brand."}
      </p>
      <div className={styles.brandDraftPreview}>
        {draft.logo && (
          <Image
            src={draft.logo}
            alt="Workspace logo preview"
            width={48}
            height={48}
            unoptimized
          />
        )}
        <strong title={draftLabel}>{draftLabel}</strong>
        {dirty && <span>Unsaved</span>}
      </div>
      <label htmlFor={`${id}-shared-name`}>Workspace brand name</label>
      <input
        id={`${id}-shared-name`}
        type="text"
        value={draft.brand_name ?? ""}
        placeholder={snapshot.workspace_name}
        disabled={!canEdit || busy}
        aria-invalid={invalidName}
        aria-describedby={`${id}-name-help`}
        onChange={(event) => {
          setDraft((value) => ({
            ...value,
            brand_name: event.target.value || null,
          }));
          setNotice("");
        }}
      />
      <small id={`${id}-name-help`}>
        {nameLength}/120 characters. Empty uses the workspace name.
      </small>
      <label htmlFor={`${id}-style`}>Default workspace style</label>
      <select
        id={`${id}-style`}
        value={draft.treatment}
        disabled={!canEdit || busy}
        onChange={(event) =>
          setDraft((value) => ({
            ...value,
            treatment: event.target.value as BrandingDraft["treatment"],
          }))
        }
      >
        <option value="classic">Classic</option>
        <option value="current">Current</option>
        <option value="paper">Paper cutout</option>
      </select>
      <small>
        Members can keep a personal visual style. Motion is always their own
        choice.
      </small>
      {canEdit && (
        <>
          <div className={styles.uploadActions}>
            <button
              type="button"
              disabled={busy}
              onClick={() => upload.current?.click()}
            >
              <ImagePlus size={16} />
              {preparing
                ? "Preparing logo…"
                : draft.logo
                  ? "Change shared logo"
                  : "Choose shared logo"}
            </button>
            {draft.logo && (
              <button
                type="button"
                className={styles.quiet}
                disabled={busy}
                onClick={() => setDraft((value) => ({ ...value, logo: null }))}
              >
                Remove logo
              </button>
            )}
          </div>
          <input
            ref={upload}
            type="file"
            hidden
            accept="image/png,image/jpeg,image/webp"
            aria-label="Choose a shared workspace logo"
            disabled={busy || !canEdit}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void chooseLogo(file);
            }}
          />
          <small>
            PNG, JPEG or WebP · up to 2 MB · stored with this workspace after
            Save
          </small>
        </>
      )}
      {invalidName && (
        <p className={styles.error} role="alert">
          Use up to 120 characters without control characters.
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {stale && (
        <p className={styles.error}>
          A newer version exists. Your draft is preserved until you choose to
          load it.
        </p>
      )}
      {(stale || permissionLost) && (
        <div className={styles.uploadActions}>
          <button
            type="button"
            disabled={busy || shared.branding.isFetching}
            onClick={() => void refresh()}
          >
            Discard draft &amp; load latest
          </button>
        </div>
      )}
      {canEdit && (
        <div className={styles.sharedActions}>
          <button
            type="button"
            className={styles.saveShared}
            disabled={busy || stale || invalidName || !dirty}
            onClick={() => void save()}
          >
            {shared.save.isPending ? "Saving…" : "Save shared brand"}
          </button>
          <button
            type="button"
            disabled={busy || stale}
            onClick={() => setConfirmReset(true)}
          >
            <RotateCcw size={14} /> Reset shared brand
          </button>
        </div>
      )}
      {confirmReset && canEdit && (
        <div className={styles.resetConfirmation}>
          <p>
            Restore the workspace name, remove its shared logo and use Current
            as the default style?
          </p>
          <div className={styles.uploadActions}>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirmReset(false)}
            >
              Keep branding
            </button>
            <button
              type="button"
              disabled={busy || stale}
              onClick={() => void reset()}
            >
              {shared.reset.isPending ? "Resetting…" : "Reset for everyone"}
            </button>
          </div>
        </div>
      )}
      <p role="status" className={styles.brandStatus}>
        {notice ||
          (dirty
            ? "Draft only. The saved workspace brand stays visible until you save."
            : `Saved workspace branding · version ${snapshot.version}`)}
      </p>
    </div>
  );
}
