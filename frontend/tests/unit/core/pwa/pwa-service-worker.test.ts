import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, it } from "@rstest/core";

const ORIGIN = "https://momo.example.test";
const CACHE_NAME = "momobot-public-offline-v1";
const PUBLIC_PATHS = [
  "/offline.html",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-512-maskable.png",
  "/icons/apple-touch-icon.png",
];
const source = readFileSync(join(process.cwd(), "public/sw.js"), "utf8");
const MALFORMED_PUSH = Symbol("malformed push payload");

type Fetcher = (request: Request, options?: RequestInit) => Promise<Response>;
type WorkerEvent = {
  request: Request;
  waitUntil: (promise: Promise<unknown>) => void;
  respondWith: (promise: Promise<Response>) => void;
};

function responseFor(url: string, body?: string, contentType?: string) {
  const response = new Response(
    body ?? (url.endsWith(".html") ? "generic offline" : "public icon"),
    {
      headers: {
        "content-type":
          contentType ??
          (url.endsWith(".html") ? "text/html; charset=utf-8" : "image/png"),
      },
    },
  );
  Object.defineProperties(response, {
    url: { value: url, configurable: true },
    type: { value: "basic", configurable: true },
  });
  return response;
}

type NotificationEvent = {
  data: { json: () => unknown } | null;
  waitUntil: (promise: Promise<unknown>) => void;
};
type ClickEvent = {
  notification: { data: unknown; close: () => void };
  waitUntil: (promise: Promise<unknown>) => void;
};

function createWorker() {
  const listeners = new Map<
    string,
    (event: WorkerEvent | NotificationEvent | ClickEvent) => void
  >();
  const stores = new Map<string, Map<string, Response>>();
  const calls: { request: Request; options?: RequestInit }[] = [];
  const writes: string[] = [];
  const notifications: { title: string; options: Record<string, unknown> }[] =
    [];
  const windowClients: { url: string; focused: boolean }[] = [];
  let opened: string | undefined;
  let fetcher: Fetcher = async (request) => responseFor(request.url);
  let claimed = false;

  function openCache(name: string) {
    let store = stores.get(name);
    if (!store) {
      store = new Map();
      stores.set(name, store);
    }
    const entries = store;
    return {
      put: async (request: Request, response: Response) => {
        writes.push(request.url);
        entries.set(request.url, response.clone());
      },
      match: async (request: string | Request) =>
        entries
          .get(
            new URL(typeof request === "string" ? request : request.url, ORIGIN)
              .href,
          )
          ?.clone(),
      keys: async () => [...entries.keys()].map((url) => new Request(url)),
      delete: async (request: Request) => entries.delete(request.url),
    };
  }

  runInNewContext(source, {
    Request,
    URL,
    Map,
    self: {
      location: { origin: ORIGIN },
      addEventListener: (
        name: string,
        listener: (event: WorkerEvent | NotificationEvent | ClickEvent) => void,
      ) => listeners.set(name, listener),
      skipWaiting: async () => undefined,
      registration: {
        showNotification: async (
          title: string,
          options: Record<string, unknown>,
        ) => {
          notifications.push({ title, options });
        },
      },
      clients: {
        claim: async () => {
          claimed = true;
        },
        matchAll: async () =>
          windowClients.map((client) => ({
            url: client.url,
            focus: async () => {
              client.focused = true;
            },
          })),
        openWindow: async (url: string) => {
          opened = url;
        },
      },
    },
    caches: {
      open: async (name: string) => openCache(name),
      keys: async () => [...stores.keys()],
      delete: async (name: string) => stores.delete(name),
    },
    fetch: async (request: Request, options?: RequestInit) => {
      calls.push({ request, options });
      return fetcher(request, options);
    },
  });

  async function lifecycle(name: string) {
    let pending: Promise<unknown> | undefined;
    listeners.get(name)?.({
      request: new Request(ORIGIN),
      waitUntil: (promise) => {
        pending = promise;
      },
      respondWith: () => {
        throw new Error("Unexpected fetch in lifecycle");
      },
    });
    if (!pending) throw new Error(`Missing ${name} event`);
    return pending;
  }

  async function request(
    path: string,
    options: RequestInit & { navigation?: boolean } = {},
  ) {
    const { navigation, ...init } = options;
    const request = new Request(new URL(path, ORIGIN), init);
    if (navigation)
      Object.defineProperty(request, "mode", { value: "navigate" });
    let pending: Promise<Response> | undefined;
    listeners.get("fetch")?.({
      request,
      waitUntil: () => {
        throw new Error("Unexpected background write");
      },
      respondWith: (promise) => {
        pending = promise;
      },
    });
    if (!pending) throw new Error("Fetch was not handled");
    return pending;
  }

  async function push(payload?: unknown) {
    let pending: Promise<unknown> | undefined;
    (
      listeners.get("push") as ((event: NotificationEvent) => void) | undefined
    )?.({
      data:
        payload === undefined
          ? null
          : {
              json: () => {
                if (payload === MALFORMED_PUSH)
                  throw new SyntaxError("Unexpected token");
                return JSON.parse(JSON.stringify(payload));
              },
            },
      waitUntil: (promise) => {
        pending = promise;
      },
    });
    if (!pending) throw new Error("Missing push event");
    return pending;
  }

  async function notificationclick(data: unknown) {
    const notification = { data, close: () => undefined };
    let pending: Promise<unknown> | undefined;
    (
      listeners.get("notificationclick") as
        | ((event: ClickEvent) => void)
        | undefined
    )?.({
      notification,
      waitUntil: (promise) => {
        pending = promise;
      },
    });
    if (!pending) throw new Error("Missing notificationclick event");
    await pending;
    return notification;
  }

  return {
    calls,
    writes,
    stores,
    lifecycle,
    request,
    push,
    notificationclick,
    notifications,
    openedUrl: () => opened,
    addWindowClient: (url: string) =>
      windowClients.push({ url, focused: false }),
    isWindowClientFocused: (url: string) =>
      windowClients.find((client) => client.url === url)?.focused ?? false,
    setFetcher: (next: Fetcher) => {
      fetcher = next;
    },
    isClaimed: () => claimed,
  };
}

describe("MomoBot public-only service worker", () => {
  it("precaches only the generic offline page and exact public icons, anonymously", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    expect(worker.writes.sort()).toEqual(
      PUBLIC_PATHS.map((path) => ORIGIN + path).sort(),
    );
    for (const { request } of worker.calls) {
      expect(request.credentials).toBe("omit");
      expect(request.cache).toBe("no-store");
      expect(request.redirect).toBe("error");
      expect(request.mode).toBe("same-origin");
    }
  });

  it("rejects redirected, substituted or non-public precache responses before writing anything", async () => {
    for (const invalid of [
      "redirected",
      "login",
      "content-type",
      "opaque",
      "status",
    ]) {
      const worker = createWorker();
      worker.setFetcher(async (request) => {
        const response = responseFor(request.url);
        if (request.url.endsWith("icon-192.png")) {
          if (invalid === "redirected")
            Object.defineProperty(response, "redirected", { value: true });
          if (invalid === "login")
            Object.defineProperty(response, "url", {
              value: ORIGIN + "/login",
            });
          if (invalid === "content-type")
            response.headers.set("content-type", "text/html");
          if (invalid === "opaque")
            Object.defineProperty(response, "type", { value: "opaque" });
          if (invalid === "status")
            return new Response("unauthorized", { status: 401 });
        }
        return response;
      });
      await expect(worker.lifecycle("install")).rejects.toThrow(
        "public offline asset",
      );
      expect(worker.writes).toEqual([]);
    }
  });

  it("does not cache API, workspace, auth, RSC, artifact or mutation responses", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    worker.setFetcher(async () => new Response("private owner A data"));
    for (const path of [
      "/api/v1/auth/me",
      "/api/threads/private-thread/messages",
      "/workspace/agent-room",
      "/workspace?_rsc=private-payload",
      "/auth/callback?code=private-code",
      "/artifacts/view?path=private-file",
      "/api/artifacts/private-file",
      "https://private-api.example.test/api/runs",
    ]) {
      expect(await (await worker.request(path)).text()).toBe(
        "private owner A data",
      );
    }
    await worker.request("/api/agent-runs", {
      method: "POST",
      body: "private input",
    });
    expect(worker.writes).toHaveLength(PUBLIC_PATHS.length);
    expect(
      worker.calls
        .slice(PUBLIC_PATHS.length)
        .every(({ options }) => options?.cache === "no-store"),
    ).toBe(true);
  });

  it("never serves a previous account response after logout or an account switch", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    worker.setFetcher(async () => new Response("owner A"));
    await worker.request("/workspace", { navigation: true });
    await worker.request("/api/v1/auth/me");
    await worker.request("/api/v1/auth/logout", { method: "POST" });
    worker.setFetcher(async () => new Response("owner B"));
    expect(
      await (await worker.request("/workspace", { navigation: true })).text(),
    ).toBe("owner B");
    expect(await (await worker.request("/api/v1/auth/me")).text()).toBe(
      "owner B",
    );
    worker.setFetcher(async () => {
      throw new Error("offline");
    });
    expect(
      await (await worker.request("/workspace", { navigation: true })).text(),
    ).toBe("generic offline");
    await expect(worker.request("/api/v1/auth/me")).rejects.toThrow("offline");
    expect(worker.writes).toHaveLength(PUBLIC_PATHS.length);
  });

  it("passes network login redirects through without storing the destination HTML", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    worker.setFetcher(async () => {
      const response = responseFor(ORIGIN + "/login", "login form");
      Object.defineProperty(response, "redirected", { value: true });
      return response;
    });
    const response = await worker.request("/workspace", { navigation: true });
    expect(response.redirected).toBe(true);
    expect(await response.text()).toBe("login form");
    expect(worker.writes).toHaveLength(PUBLIC_PATHS.length);
  });

  it("allows only generic navigation and exact public icon fallbacks while offline", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    worker.setFetcher(async () => {
      throw new Error("offline");
    });
    expect(
      await (
        await worker.request("/workspace/chats/private-thread", {
          navigation: true,
        })
      ).text(),
    ).toBe("generic offline");
    expect(await (await worker.request("/icons/icon-192.png")).text()).toBe(
      "public icon",
    );
    for (const path of [
      "/api",
      "/api/v1/auth/me",
      "/mock/api/threads",
      "/workspace?_rsc=private",
      "/icons/icon-192.png?owner=private",
      "https://other.example.test/icons/icon-192.png",
    ]) {
      await expect(worker.request(path)).rejects.toThrow("offline");
    }
    await expect(
      worker.request("/api/runs", { method: "POST", body: "private" }),
    ).rejects.toThrow("offline");
    await expect(
      worker.request("/api/v1/auth/me", { navigation: true }),
    ).rejects.toThrow("offline");
  });

  it("fails closed when the generic offline cache has been evicted", async () => {
    const worker = createWorker();
    worker.setFetcher(async () => {
      throw new Error("offline");
    });
    await expect(
      worker.request("/workspace", { navigation: true }),
    ).rejects.toThrow("offline");
  });

  it("prunes stale own caches and unexpected entries without touching other app caches", async () => {
    const worker = createWorker();
    await worker.lifecycle("install");
    worker.stores.set(
      "momobot-public-offline-v0",
      new Map([[ORIGIN + "/workspace", new Response("private stale HTML")]]),
    );
    worker.stores.set(
      "another-app",
      new Map([[ORIGIN + "/other", new Response("other app")]]),
    );
    worker.stores
      .get(CACHE_NAME)
      ?.set(ORIGIN + "/api/private", new Response("private old data"));
    worker.stores
      .get(CACHE_NAME)
      ?.set(
        ORIGIN + "/icons/icon-192.png?owner=private",
        new Response("private substituted asset"),
      );
    await worker.lifecycle("activate");
    expect([...worker.stores.keys()].sort()).toEqual(
      ["another-app", CACHE_NAME].sort(),
    );
    expect([...(worker.stores.get(CACHE_NAME)?.keys() ?? [])].sort()).toEqual(
      PUBLIC_PATHS.map((path) => ORIGIN + path).sort(),
    );
    expect(worker.isClaimed()).toBe(true);
  });

  it("shows a push notification from a well-formed payload, falling back to app icons", async () => {
    const worker = createWorker();
    await worker.push({
      title: "Momo needs your yes",
      body: "A board thread is waiting on your approval.",
      url: "/workspace/board/thread-1",
    });
    expect(worker.notifications).toEqual([
      {
        title: "Momo needs your yes",
        options: {
          body: "A board thread is waiting on your approval.",
          icon: "/icons/icon-192.png",
          badge: "/icons/icon-192.png",
          data: { url: "/workspace/board/thread-1" },
        },
      },
    ]);
  });

  it("falls back to generic copy and the workspace root for missing, malformed or hostile push payloads", async () => {
    for (const payload of [
      undefined,
      MALFORMED_PUSH,
      null,
      [],
      false,
      "text",
      { title: 42, body: { nested: true } },
      { url: "https://evil.example.test/phish" },
      { url: "//evil.example.test" },
    ]) {
      const worker = createWorker();
      await worker.push(payload);
      expect(worker.notifications).toEqual([
        {
          title: "MomoBot",
          options: {
            body: "",
            icon: "/icons/icon-192.png",
            badge: "/icons/icon-192.png",
            data: { url: "/workspace" },
          },
        },
      ]);
    }
  });

  it("focuses an already-open client on the notification's target instead of opening a new one", async () => {
    const worker = createWorker();
    worker.addWindowClient(ORIGIN + "/workspace/board/thread-1");
    const notification = await worker.notificationclick({
      url: "/workspace/board/thread-1",
    });
    expect(notification.close).toBeInstanceOf(Function);
    expect(
      worker.isWindowClientFocused(ORIGIN + "/workspace/board/thread-1"),
    ).toBe(true);
    expect(worker.openedUrl()).toBeUndefined();
  });

  it("opens a new window at the notification's target when nothing is already open there", async () => {
    const worker = createWorker();
    await worker.notificationclick({ url: "/workspace/board/thread-9" });
    expect(worker.openedUrl()).toBe(ORIGIN + "/workspace/board/thread-9");
  });

  it("never opens a notification target outside the app's own origin", async () => {
    for (const hostile of [
      "https://evil.example.test/phish",
      "//evil.example.test/phish",
      "/\\evil.example.test/phish",
      "/\n/evil.example.test/phish",
      "/\t/evil.example.test/phish",
      "/\r\\evil.example.test/phish",
    ]) {
      const worker = createWorker();
      await worker.notificationclick({ url: hostile });
      expect(worker.openedUrl()).toBe(ORIGIN + "/workspace");
    }
  });

  it("canonicalizes same-origin notification paths while preserving the query and fragment", async () => {
    const worker = createWorker();
    await worker.notificationclick({
      url: "/workspace/board/../ceo?tab=pending#item",
    });
    expect(worker.openedUrl()).toBe(ORIGIN + "/workspace/ceo?tab=pending#item");
  });

  it("rejects control characters in push destinations before storing notification data", async () => {
    for (const url of [
      "/\n/evil.example.test",
      "/\t/evil.example.test",
      "/\r\\evil.example.test",
    ]) {
      const worker = createWorker();
      await worker.push({ url });
      expect(worker.notifications[0]?.options.data).toEqual({
        url: "/workspace",
      });
    }
  });
});
