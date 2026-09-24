import { afterEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("next/headers", () => ({
  cookies: rs.fn(async () => ({
    get: () => ({ value: "session-token" }),
  })),
}));

import { isDeskEnabledOnServer } from "@/core/features/server";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

function gatewayAnswers(answer: () => Promise<Response>) {
  const spy = rs.fn(answer);
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

describe("isDeskEnabledOnServer", () => {
  it("sends the session to the gateway and honours an explicit true", async () => {
    const spy = gatewayAnswers(async () =>
      Response.json({ agents_api: { enabled: true }, desk: { enabled: true } }),
    );
    await expect(isDeskEnabledOnServer()).resolves.toBe(true);
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/features$/);
    expect(init.headers).toEqual({ Cookie: "access_token=session-token" });
  });

  it("fails closed so client-facing MomoBot lands on Command Center", async () => {
    gatewayAnswers(async () =>
      Response.json({ agents_api: { enabled: true } }),
    );
    await expect(isDeskEnabledOnServer()).resolves.toBe(false);
    gatewayAnswers(async () => new Response("nope", { status: 401 }));
    await expect(isDeskEnabledOnServer()).resolves.toBe(false);
    gatewayAnswers(async () => {
      throw new TypeError("gateway unreachable");
    });
    await expect(isDeskEnabledOnServer()).resolves.toBe(false);
  });
});
