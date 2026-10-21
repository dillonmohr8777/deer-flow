import type { BrandPrice } from "./types";

/**
 * Price line for one package, or null when prices must stay hidden.
 * A missing amount is "Not priced", never $0. Packages are never summed:
 * a shared package appears under each agent that uses it.
 */
export function priceLabel(
  price: BrandPrice | undefined,
  showPricing: boolean,
): string | null {
  if (!showPricing) return null;
  if (price?.monthly_usd == null) return "Not priced";
  return `$${price.monthly_usd.toLocaleString("en-US")}/mo`;
}

/** "Shared with A, B" using agent names; ids fall back to themselves. */
export function sharedNote(
  price: BrandPrice | undefined,
  names: Record<string, string>,
): string | null {
  const ids = price?.shared_with;
  if (!ids?.length) return null;
  return `Shared with ${ids.map((id) => names[id] ?? id).join(", ")}`;
}
