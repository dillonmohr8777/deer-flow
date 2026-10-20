import { describe, expect, it } from "@rstest/core";

import { priceLabel, sharedNote } from "@/core/momobot-brand/pricing";

describe("priceLabel", () => {
  it("stays hidden unless the server says show_pricing", () => {
    expect(priceLabel({ monthly_usd: 5 }, false)).toBeNull();
    expect(priceLabel(undefined, false)).toBeNull();
  });

  it("shows Not priced for a missing amount, never $0", () => {
    expect(priceLabel({ monthly_usd: null }, true)).toBe("Not priced");
    expect(priceLabel(undefined, true)).toBe("Not priced");
    expect(priceLabel({ monthly_usd: 0 }, true)).toBe("$0/mo");
  });

  it("formats a real amount", () => {
    expect(priceLabel({ monthly_usd: 1250 }, true)).toBe("$1,250/mo");
  });
});

describe("sharedNote", () => {
  it("names the agents sharing a package", () => {
    expect(
      sharedNote({ monthly_usd: 5, shared_with: ["a", "z"] }, { a: "Fake A" }),
    ).toBe("Shared with Fake A, z");
    expect(sharedNote({ monthly_usd: 5 }, {})).toBeNull();
  });
});
