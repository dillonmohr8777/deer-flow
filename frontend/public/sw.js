/*
 * MomoBot's only offline content is a generic connection screen and public
 * app icons. Never store app HTML, RSC payloads, API results or client files.
 * No background sync, offline writes, push or agent execution is implied.
 */
const CACHE_PREFIX = "momobot-public-offline-";
const CACHE_NAME = `${CACHE_PREFIX}v1`;
const OFFLINE_URL = "/offline.html";
const PUBLIC_ASSETS = new Map([
  [OFFLINE_URL, "text/html"],
  ["/icons/icon-192.png", "image/png"],
  ["/icons/icon-512.png", "image/png"],
  ["/icons/icon-512-maskable.png", "image/png"],
  ["/icons/apple-touch-icon.png", "image/png"],
]);

function publicAssetPath(url) {
  return url.origin === self.location.origin &&
    !url.search &&
    PUBLIC_ASSETS.has(url.pathname)
    ? url.pathname
    : null;
}

async function precachePublicAssets() {
  // Fetch anonymously and reject redirects, including a login response served
  // in place of an icon. Validate everything before writing any cache entry.
  const assets = await Promise.all(
    [...PUBLIC_ASSETS].map(async ([path, contentType]) => {
      const request = new Request(new URL(path, self.location.origin), {
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
        mode: "same-origin",
      });
      const response = await fetch(request);
      if (
        !response.ok ||
        response.type !== "basic" ||
        response.redirected ||
        response.url !== request.url ||
        response.headers.get("content-type")?.split(";")[0]?.trim() !==
          contentType
      ) {
        throw new Error("MomoBot public offline asset is unavailable");
      }
      return [request, response];
    }),
  );
  const cache = await caches.open(CACHE_NAME);
  await Promise.all(
    assets.map(([request, response]) => cache.put(request, response)),
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(precachePublicAssets().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter(
            (name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME,
          )
          .map((name) => caches.delete(name)),
      );
      // Prune anything unexpected left in this worker's cache. Other app caches
      // belong to their owners and are never read or changed by this worker.
      const cache = await caches.open(CACHE_NAME);
      const keys = await cache.keys();
      await Promise.all(
        keys
          .filter((request) => !publicAssetPath(new URL(request.url)))
          .map((request) => cache.delete(request)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  event.respondWith(
    // Bypass the HTTP cache too: a new account/session must always reach the
    // server. There are deliberately no runtime cache writes, on any route.
    fetch(request, { cache: "no-store" }).catch(async (error) => {
      if (request.method !== "GET") throw error;
      const publicPath = publicAssetPath(url);
      const apiPath =
        url.pathname === "/api" ||
        url.pathname.startsWith("/api/") ||
        url.pathname === "/mock/api" ||
        url.pathname.startsWith("/mock/api/");
      const offlineNavigation =
        request.mode === "navigate" &&
        url.origin === self.location.origin &&
        !apiPath;
      if (!publicPath && !offlineNavigation) throw error;

      const cache = await caches.open(CACHE_NAME);
      const fallback = await cache.match(publicPath || OFFLINE_URL);
      if (!fallback) throw error;
      return fallback;
    }),
  );
});
