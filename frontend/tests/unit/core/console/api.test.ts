import { beforeEach, expect, rs, test } from "@rstest/core";

const fetchWithAuth = rs.fn();
const cancel = rs.fn();

rs.mock("@/core/api/fetcher", () => ({ fetch: fetchWithAuth }));
rs.mock("@/core/api", () => ({ getAPIClient: () => ({ runs: { cancel } }) }));

beforeEach(() => {
  fetchWithAuth.mockReset();
  cancel.mockReset();
  fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({}) });
});

test("console requests use the authenticated gateway and bounded query parameters", async () => {
  const { fetchConsoleRuns, fetchConsoleUsage } =
    await import("@/core/console/api");

  await fetchConsoleRuns({ status: "error", offset: 20 });
  expect(fetchWithAuth).toHaveBeenLastCalledWith(
    expect.stringContaining(
      "/api/console/runs?limit=20&offset=20&status=error",
    ),
    { method: "GET" },
  );

  await fetchConsoleUsage();
  const usageUrl = String(fetchWithAuth.mock.calls.at(-1)?.[0]);
  expect(usageUrl).toContain("/api/console/usage?days=14&tz_offset_minutes=");
});

test("cancel delegates to the LangGraph run manager", async () => {
  const { cancelConsoleRun } = await import("@/core/console/api");
  await cancelConsoleRun("thread/1", "run/2");
  expect(cancel).toHaveBeenCalledWith("thread/1", "run/2");
});

test("failed console reads stay errors instead of becoming empty data", async () => {
  const { fetchConsoleStats } = await import("@/core/console/api");
  const json = rs.fn();
  fetchWithAuth.mockResolvedValue({ ok: false, status: 403, json });
  await expect(fetchConsoleStats()).rejects.toThrow(
    "Console request failed (403)",
  );
  expect(json).not.toHaveBeenCalled();
});
