import { afterEach, beforeEach, describe, expect, rs, test } from "@rstest/core";

// Two DeerFlow instances reachable on the same hostname but different ports
// share one browser cookie jar (cookies are host-scoped, not port-scoped).
// DEER_FLOW_AUTH_COOKIE_PREFIX lets a deployment namespace its session
// cookie so it doesn't collide with another instance's. See the matching
// backend test: backend/tests/test_session_cookie_prefix.py.

const ENV_KEY = "DEER_FLOW_AUTH_COOKIE_PREFIX" as const;

function loadFreshConstants() {
  rs.resetModules();
  return import("@/core/auth/constants");
}

describe("ACCESS_TOKEN_COOKIE_NAME", () => {
  let saved: string | undefined;

  beforeEach(() => {
    saved = process.env[ENV_KEY];
    delete process.env[ENV_KEY];
  });

  afterEach(() => {
    if (saved === undefined) {
      delete process.env[ENV_KEY];
    } else {
      process.env[ENV_KEY] = saved;
    }
  });

  test("defaults to the unprefixed cookie name", async () => {
    const { ACCESS_TOKEN_COOKIE_NAME } = await loadFreshConstants();
    expect(ACCESS_TOKEN_COOKIE_NAME).toBe("access_token");
  });

  test("namespaces the cookie name from DEER_FLOW_AUTH_COOKIE_PREFIX", async () => {
    process.env[ENV_KEY] = "dillon_workspace_";
    const { ACCESS_TOKEN_COOKIE_NAME } = await loadFreshConstants();
    expect(ACCESS_TOKEN_COOKIE_NAME).toBe("dillon_workspace_access_token");
  });
});
