import { beforeEach, expect, rs, test } from "@rstest/core";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({ fetch: fetchWithAuth }));

beforeEach(() => {
  fetchWithAuth.mockReset();
});

test("fetches the authenticated brief endpoint", async () => {
  const brief = {
    generated_at: "2026-09-23T12:00:00Z",
    assigned_clients: [],
    activity: [],
    due_today: [],
    waiting_on_you: [],
  };
  fetchWithAuth.mockResolvedValue({ ok: true, json: async () => brief });

  const { fetchTodayBrief } = await import("@/core/briefs/api");
  await expect(fetchTodayBrief()).resolves.toEqual(brief);
  expect(fetchWithAuth).toHaveBeenLastCalledWith(
    expect.stringContaining("/api/briefs/today"),
    { method: "GET" },
  );
});

test("a failed read stays an error instead of becoming empty data", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 503,
    json: rs.fn(),
  });
  const { fetchTodayBrief } = await import("@/core/briefs/api");
  await expect(fetchTodayBrief()).rejects.toThrow("Brief request failed (503)");
});
