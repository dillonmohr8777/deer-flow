import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import {
  AgentRoomAccessDeniedError,
  fetchAgentRoomEnabled,
  listAgentRoomMessages,
  postAgentRoomMessage,
} from "@/core/agent-room/api";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

const network = rs.fn<typeof globalThis.fetch>();
let originalFetch: typeof globalThis.fetch;
beforeEach(() => {
  originalFetch = globalThis.fetch;
  globalThis.fetch = network;
  document.cookie = "csrf_token=fixture-csrf; path=/";
  network.mockResolvedValue(
    new Response(JSON.stringify({ messages: [] }), { status: 200 }),
  );
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  document.cookie = "csrf_token=; max-age=0; path=/";
  network.mockReset();
});

describe("real Room transport owner fence", () => {
  it("sends the captured owner and cancellable signal on private discovery and message reads", async () => {
    const controller = new AbortController();
    network.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          agents_api: { enabled: true },
          desk: { enabled: true },
        }),
        { status: 200 },
      ),
    );
    expect(await fetchAgentRoomEnabled("owner-A", controller.signal)).toBe(
      true,
    );
    await listAgentRoomMessages("owner-A", controller.signal);
    for (const [, init] of network.mock.calls) {
      expect(new Headers(init?.headers).get("X-Expected-User-Id")).toBe(
        "owner-A",
      );
      expect(init?.signal).toBe(controller.signal);
      expect(init?.credentials).toBe("include");
    }
  });

  it("preserves the captured owner alongside actual credential/CSRF headers on a post", async () => {
    const input = {
      body: "Owner A draft",
      message_type: "instruction" as const,
    };
    await postAgentRoomMessage(input, "owner-A");
    const [, init] = network.mock.calls[0]!;
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Expected-User-Id")).toBe("owner-A");
    expect(headers.get("X-CSRF-Token")).toBe("fixture-csrf");
    expect(init?.credentials).toBe("include");
    expect(init?.body).toBe(JSON.stringify(input));
  });

  it("surfaces the server's account-change refusal without retrying the draft", async () => {
    network.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: "The signed-in account changed; reload this page",
        }),
        { status: 409 },
      ),
    );
    await expect(
      postAgentRoomMessage(
        { body: "Old owner draft", message_type: "instruction" },
        "owner-A",
      ),
    ).rejects.toThrow("signed-in account changed");
    expect(network).toHaveBeenCalledTimes(1);
  });

  for (const status of [403, 404]) {
    it(`throws AgentRoomAccessDeniedError on a ${status} discovery response (f134 review)`, async () => {
      network.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "nope" }), { status }),
      );
      await expect(fetchAgentRoomEnabled("owner-A")).rejects.toBeInstanceOf(
        AgentRoomAccessDeniedError,
      );
    });
  }

  for (const status of [401, 500]) {
    it(`throws a plain Error, not AgentRoomAccessDeniedError, on a ${status} discovery response (f134 review)`, async () => {
      network.mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "nope" }), { status }),
      );
      const error = await fetchAgentRoomEnabled("owner-A").catch(
        (e: unknown) => e,
      );
      expect(error).toBeInstanceOf(Error);
      expect(error).not.toBeInstanceOf(AgentRoomAccessDeniedError);
    });
  }
});
