export const DEFAULT_AUTH_NEXT_PATH = "/workspace";

export function validateAuthNextPath(
  nextPath: string | null | undefined,
): string | null {
  if (!nextPath) {
    return null;
  }
  if (!nextPath.startsWith("/")) {
    return null;
  }
  if (nextPath.startsWith("//")) {
    return null;
  }
  if (nextPath.includes("\\") || nextPath.includes(":")) {
    return null;
  }
  // Browsers strip tab/newline/CR from URLs, so "/\t/evil.example" becomes
  // "//evil.example". Refuse every control character and space outright.
  for (const ch of nextPath) {
    const code = ch.charCodeAt(0);
    if (code <= 0x20 || code === 0x7f) return null;
  }
  // Belt and braces: whatever survives must still resolve to this origin.
  if (typeof window !== "undefined") {
    try {
      const resolved = new URL(nextPath, window.location.origin);
      if (resolved.origin !== window.location.origin) return null;
    } catch {
      return null;
    }
  }
  return nextPath;
}

export function resolveAuthNextPath(
  nextPath: string | null | undefined,
  fallback = DEFAULT_AUTH_NEXT_PATH,
): string {
  return validateAuthNextPath(nextPath) ?? fallback;
}
