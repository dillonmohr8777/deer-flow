const VOICE_START = "\n\n<!-- momentum:voice:v1 -->\n## Voice\n";
const VOICE_END = "\n<!-- /momentum:voice -->";

export const MAX_IDENTITY_VOICE_LENGTH = 1600;

export type IdentityPrompt = { brief: string; voice: string };

/** Only our exact trailing section is editable separately; existing prose is untouched. */
export function splitIdentityPrompt(prompt: string): IdentityPrompt {
  const start = prompt.lastIndexOf(VOICE_START);
  if (start < 0 || !prompt.endsWith(VOICE_END))
    return { brief: prompt, voice: "" };
  const voice = prompt.slice(start + VOICE_START.length, -VOICE_END.length);
  if (voice.includes("<!-- momentum:voice") || voice.includes(VOICE_END))
    return { brief: prompt, voice: "" };
  return { brief: prompt.slice(0, start), voice };
}

export function identityVoiceIsValid(voice: string): boolean {
  return (
    [...voice.trim()].length <= MAX_IDENTITY_VOICE_LENGTH &&
    !voice.includes("<!-- momentum:voice") &&
    !voice.includes("<!-- /momentum:voice")
  );
}

export function composeIdentityPrompt({
  brief,
  voice,
}: IdentityPrompt): string {
  return voice.trim()
    ? `${brief}${VOICE_START}${voice.trim()}${VOICE_END}`
    : brief;
}

export function identityPromptChanged(
  original: string,
  draft: IdentityPrompt,
): boolean {
  const initial = splitIdentityPrompt(original);
  return draft.brief !== initial.brief || draft.voice !== initial.voice;
}

export const IDENTITY_VOICES = [
  {
    id: "scout",
    name: "Scout",
    character: "Curious. Precise. Evidence first.",
    voice:
      "Be curious, precise, and economical with words. Lead with what the evidence supports, then explain what remains uncertain. Ask sharp questions, name sources, and make the next decision easy to see. Warmth is welcome; confidence must be earned.",
  },
  {
    id: "studio",
    name: "Studio",
    character: "Inventive. Opinionated. Clear.",
    voice:
      "Bring an inventive point of view and explain the craft behind it. Use vivid, specific language and a little wit when it helps. Offer a strong recommendation with a reason, keep feedback constructive, and separate proposed creative ideas from approved facts.",
  },
  {
    id: "anchor",
    name: "Anchor",
    character: "Calm. Direct. Thoughtful.",
    voice:
      "Sound like a thoughtful partner: calm, candid, and easy to understand. Start with the outcome, explain tradeoffs plainly, and end with a concrete next step when one exists. Avoid hype, keep commitments precise, and say when a result is not yet verified.",
  },
] as const;
