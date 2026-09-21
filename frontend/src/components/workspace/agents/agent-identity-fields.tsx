"use client";

import { Check, ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import { MomentumGlyph } from "../command-center/momentum-glyph";

import {
  IDENTITY_VOICES,
  identityVoiceIsValid,
  MAX_IDENTITY_VOICE_LENGTH,
  type IdentityPrompt,
} from "./agent-identity-helpers";

import styles from "./agent-identity.module.css";

export function AgentIdentityFields({
  name,
  displayName,
  role,
  prompt,
  scope,
  disabled = false,
  promptAvailable = true,
  onDisplayNameChange,
  onRoleChange,
  onPromptChange,
}: {
  name: string;
  displayName: string;
  role: string;
  prompt: IdentityPrompt;
  scope: string;
  disabled?: boolean;
  promptAvailable?: boolean;
  onDisplayNameChange: (value: string) => void;
  onRoleChange: (value: string) => void;
  onPromptChange: (value: IdentityPrompt) => void;
}) {
  const id = useId();
  const [selectedVoice, setSelectedVoice] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const starter = IDENTITY_VOICES.find((voice) => voice.id === selectedVoice);
  const label = displayName.trim() || name || "Your specialist";
  const nameTooLong = [...displayName.trim()].length > 100;
  const voiceInvalid = !identityVoiceIsValid(prompt.voice);
  return (
    <section className={styles.identity} aria-label="Agent identity">
      <div className={styles.preview}>
        <MomentumGlyph seed={`agent:${name || "new-specialist"}`} size={58} />
        <div className={styles.previewCopy}>
          <strong title={label}>{label}</strong>
          <span>{scope}</span>
        </div>
      </div>
      <div className={styles.field}>
        <label htmlFor={`${id}-name`}>Display name</label>
        <Input
          id={`${id}-name`}
          value={displayName}
          disabled={disabled}
          placeholder={name || "Give this expert a recognizable name"}
          aria-invalid={nameTooLong}
          aria-describedby={`${id}-name-help`}
          onChange={(event) => onDisplayNameChange(event.target.value)}
        />
        <p id={`${id}-name-help`} data-error={nameTooLong}>
          {[...displayName.trim()].length}/100 characters. The stable identifier
          stays {name || "the name you choose below"}.
        </p>
      </div>
      <div className={styles.field}>
        <label htmlFor={`${id}-role`}>Role &amp; expertise</label>
        <Textarea
          id={`${id}-role`}
          value={role}
          disabled={disabled}
          placeholder="What this agent is responsible for, and where its expertise belongs."
          onChange={(event) => onRoleChange(event.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor={`${id}-voice`}>Voice &amp; personality</label>
        <Textarea
          id={`${id}-voice`}
          value={prompt.voice}
          disabled={disabled || !promptAvailable}
          placeholder="How should this expert communicate?"
          aria-invalid={voiceInvalid}
          aria-describedby={`${id}-voice-help`}
          onChange={(event) =>
            onPromptChange({ ...prompt, voice: event.target.value })
          }
        />
        <p id={`${id}-voice-help`} data-error={voiceInvalid}>
          {voiceInvalid
            ? `Use up to ${MAX_IDENTITY_VOICE_LENGTH} characters without reserved voice markers.`
            : "Saved as a Voice section in the existing working brief. Model, tools and permissions stay separate."}
        </p>
      </div>
      <details className={styles.starters}>
        <summary>
          <ChevronRight size={15} /> Try a starter voice
        </summary>
        <p>
          Optional writing directions. Preview one, then add it to your draft.
        </p>
        <div className={styles.voiceChoices}>
          {IDENTITY_VOICES.map((voice) => (
            <button
              type="button"
              key={voice.id}
              disabled={disabled || !promptAvailable}
              aria-pressed={selectedVoice === voice.id}
              onClick={() => setSelectedVoice(voice.id)}
            >
              <span>
                <MomentumGlyph seed={`voice:${voice.id}`} size={26} />{" "}
                {voice.name}
              </span>
              <small>{voice.character}</small>
            </button>
          ))}
        </div>
        {starter && (
          <div className={styles.voicePreview}>
            <p>{starter.voice}</p>
            <button
              type="button"
              disabled={disabled || !promptAvailable}
              onClick={() => {
                onPromptChange({ ...prompt, voice: starter.voice });
                setNotice(
                  `${starter.name} voice added to your draft. Save to apply it.`,
                );
              }}
            >
              <Check size={15} /> Use {starter.name} voice in draft
            </button>
          </div>
        )}
        {notice && <p role="status">{notice}</p>}
      </details>
      <div className={styles.field}>
        <label htmlFor={`${id}-brief`}>Working brief &amp; guardrails</label>
        <Textarea
          id={`${id}-brief`}
          className={styles.brief}
          value={prompt.brief}
          disabled={disabled || !promptAvailable}
          spellCheck={false}
          aria-describedby={`${id}-brief-help`}
          onChange={(event) =>
            onPromptChange({ ...prompt, brief: event.target.value })
          }
        />
        <p id={`${id}-brief-help`}>
          {promptAvailable
            ? "The actual instructions used on the next run. Keep existing expertise, boundaries and approval rules intact."
            : "The full brief was not included in this record. Reopen after refreshing to edit it safely."}
        </p>
      </div>
    </section>
  );
}
