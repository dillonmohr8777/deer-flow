export const AUTH_REQUEST_TIMEOUT_MS = 5_000;

/**
 * Name of the HttpOnly session cookie the Gateway sets on login, read here
 * for the SSR auth check. Must match the Gateway's
 * `app.gateway.auth.session_cookie.ACCESS_TOKEN_COOKIE_NAME`, which is
 * namespaced by the same `DEER_FLOW_AUTH_COOKIE_PREFIX` env var — set it
 * identically on both frontend and gateway containers for a deployment.
 *
 * Two DeerFlow instances reachable on the same hostname but different ports
 * (e.g. a private workspace beside the main site) share one browser cookie
 * jar, since cookies are host-scoped, not port-scoped. Without a per-instance
 * prefix, both instances read/write the same `access_token` cookie name and
 * silently clobber each other's session.
 */
export const ACCESS_TOKEN_COOKIE_NAME = `${process.env.DEER_FLOW_AUTH_COOKIE_PREFIX ?? ""}access_token`;
