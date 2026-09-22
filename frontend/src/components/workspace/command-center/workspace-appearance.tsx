"use client";

import { Check, ImagePlus, Pause, Play, RotateCcw, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { PluginIconError, preparePluginIcon } from "@/core/mcp/icon";

import { type BrandTreatment } from "./appearance-preferences";
import { useWorkspaceAppearance } from "./appearance-provider";
import { MomentumGlyph } from "./momentum-glyph";

import styles from "./workspace-appearance.module.css";

const treatments: {
  value: BrandTreatment;
  name: string;
  description: string;
}[] = [
  {
    value: "classic",
    name: "Classic",
    description: "Crisp marks. Clear space.",
  },
  {
    value: "current",
    name: "Current",
    description: "Cool light. Sculpted depth.",
  },
  {
    value: "paper",
    name: "Paper cutout",
    description: "Ivory layers. Cobalt character.",
  },
];

export function BrandMotionToggle({ compact = false }: { compact?: boolean }) {
  const { preferences, update, canCustomize, reducedMotion } =
    useWorkspaceAppearance();
  const classic = preferences.treatment === "classic";
  const animated = preferences.motion && !reducedMotion && !classic;
  return (
    <button
      className={styles.motionToggle}
      data-compact={compact}
      type="button"
      role={compact ? undefined : "switch"}
      aria-label={
        compact
          ? animated
            ? "Pause brand animation"
            : "Enable brand animation"
          : "Brand motion"
      }
      aria-checked={compact ? undefined : animated}
      aria-pressed={compact ? animated : undefined}
      disabled={!canCustomize || reducedMotion || classic}
      title={
        reducedMotion
          ? "Your system’s reduced-motion setting keeps brand animation still."
          : classic
            ? "Classic keeps the brand still. Choose Current or Paper cutout for optional motion."
            : "Decorative brand animation only; agent activity is unchanged."
      }
      onClick={() => update({ motion: !preferences.motion })}
    >
      {animated ? <Pause size={14} /> : <Play size={14} />}
      {!compact &&
        (reducedMotion
          ? "Reduced motion"
          : classic
            ? "Still style"
            : animated
              ? "Motion on"
              : "Motion off")}
    </button>
  );
}

export function WorkspaceAppearance({ onClose }: { onClose: () => void }) {
  const {
    preferences,
    persistence,
    canCustomize,
    reducedMotion,
    update,
    reset,
  } = useWorkspaceAppearance();
  const id = useId();
  const uploadInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState(preferences.label);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );
  useEffect(() => setLabel(preferences.label), [preferences.label]);

  async function chooseLogo(file: File) {
    const current = ++generation.current;
    setBusy(true);
    setError(null);
    try {
      const logo = await preparePluginIcon(file);
      if (generation.current === current) update({ logo });
    } catch (failure) {
      if (generation.current === current)
        setError(
          failure instanceof PluginIconError && failure.code === "size"
            ? "Choose a PNG, JPEG or WebP smaller than 2 MB."
            : "That image could not be used. Choose a valid PNG, JPEG or WebP; SVG and remote URLs are not supported.",
        );
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  function resetAppearance() {
    generation.current++;
    setBusy(false);
    setError(null);
    setLabel("");
    reset();
  }

  return (
    <section
      className={styles.panel}
      id="workspace-appearance"
      aria-labelledby={`${id}-title`}
    >
      <div className={styles.panelHead}>
        <div>
          <h2 id={`${id}-title`}>Make it yours.</h2>
          <p>One visual language for your brand and your agent team.</p>
        </div>
        <button
          type="button"
          className={styles.close}
          aria-label="Close appearance"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div className={styles.panelBody}>
        <fieldset className={styles.treatments} disabled={!canCustomize}>
          <legend>Workspace style</legend>
          <div className={styles.choices}>
            {treatments.map((treatment) => (
              <label
                key={treatment.value}
                className={styles.choice}
                data-treatment={treatment.value}
                data-selected={preferences.treatment === treatment.value}
              >
                <input
                  type="radio"
                  name={`${id}-treatment`}
                  value={treatment.value}
                  checked={preferences.treatment === treatment.value}
                  onChange={() => update({ treatment: treatment.value })}
                />
                <span className={styles.choiceArt} aria-hidden="true">
                  <MomentumGlyph seed="agent:momentum-design" size={44} />
                </span>
                <span className={styles.choiceName}>
                  {treatment.name}
                  {preferences.treatment === treatment.value && (
                    <Check size={14} aria-hidden="true" />
                  )}
                </span>
                <span className={styles.choiceDescription}>
                  {treatment.description}
                </span>
              </label>
            ))}
          </div>
          <p className={styles.motionNote}>
            {reducedMotion
              ? "Reduced motion is enabled on your device. The selected style stays visible without movement."
              : "Brand motion is optional. Your agents’ recorded activity always stays separate."}
          </p>
        </fieldset>
        <div className={styles.personalBrand}>
          <h3>Your brand, locally.</h3>
          <p>
            Preview a client or team logo in this browser. This does not change
            the shared workspace.
          </p>
          <label htmlFor={`${id}-name`}>Brand name</label>
          <input
            id={`${id}-name`}
            type="text"
            value={label}
            placeholder="e.g. Your studio"
            maxLength={80}
            disabled={!canCustomize}
            onChange={(event) =>
              setLabel([...event.target.value].slice(0, 40).join(""))
            }
            onBlur={() => update({ label })}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                update({ label });
              }
            }}
          />
          <div className={styles.uploadActions}>
            <button
              type="button"
              onClick={() => uploadInput.current?.click()}
              disabled={!canCustomize || busy}
            >
              <ImagePlus size={16} />
              {busy
                ? "Preparing logo…"
                : preferences.logo
                  ? "Change logo"
                  : "Choose logo"}
            </button>
            {preferences.logo && (
              <button
                type="button"
                className={styles.quiet}
                onClick={() => {
                  generation.current++;
                  setBusy(false);
                  setError(null);
                  update({ logo: null });
                }}
              >
                Remove
              </button>
            )}
          </div>
          <input
            ref={uploadInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            aria-label="Choose a local brand logo"
            disabled={!canCustomize || busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void chooseLogo(file);
            }}
          />
          <small>PNG, JPEG or WebP · up to 2 MB · stays on this device</small>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
      <div className={styles.panelFoot}>
        <p role="status">
          {persistence === "loading"
            ? "Loading your appearance…"
            : persistence === "local"
              ? "Saved for your account in this browser. Other teammates keep their own appearance."
              : "Browser storage is unavailable. Changes last only for this visit."}
        </p>
        <button
          type="button"
          onClick={resetAppearance}
          disabled={!canCustomize}
        >
          <RotateCcw size={14} />
          Reset appearance
        </button>
      </div>
    </section>
  );
}
