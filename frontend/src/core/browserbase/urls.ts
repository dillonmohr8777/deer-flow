/** Client-side input feedback only; the Gateway must resolve and guard DNS. */
export function publicResearchUrl(value: string): string | null {
  if (value.length > 2048) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      (url.port && url.port !== "443") ||
      !host.includes(".") ||
      host.includes(":") ||
      /^[\d.]+$/.test(host) ||
      /(^|\.)(localhost|local|internal|test|invalid)$/.test(host)
    )
      return null;
    url.hash = "";
    return url.toString();
  } catch {
    return null;
  }
}

export function parseResearchUrls(value: string, maxPages = 3): string[] {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length || lines.length > maxPages)
    throw new Error(
      `Enter one to ${maxPages} public HTTPS URLs, one per line.`,
    );
  const urls = lines.map((line) => publicResearchUrl(line));
  if (urls.some((url) => url === null))
    throw new Error(
      "Use public HTTPS pages without credentials or a custom port.",
    );
  const normalized = urls as string[];
  if (new Set(normalized).size !== normalized.length)
    throw new Error("Each page URL must be different.");
  return normalized;
}
