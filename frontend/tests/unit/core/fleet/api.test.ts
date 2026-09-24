import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  listClientAgents,
  listFleetTemplates,
  stampClientAgent,
} from "@/core/fleet/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

const TEMPLATE = {
  id: "weekly-client-report",
  version: "1",
  name: "Weekly Client Report",
  description: "Pulls the week's numbers into a short report draft.",
  model: "openrouter-sonnet-5",
  skills: ["data-analysis"],
  tool_groups: ["web"],
  mcp_plugins: [],
  schedule: { cron: "0 8 * * 1", timezone: "America/New_York" },
  acceptance_criteria: ["Covers only the most recent 7 days."],
};

const BINDING = {
  client_id: "client-1",
  template_id: "weekly-client-report",
  template_version: "1",
  agent_name: "acme-weekly-client-report",
  display_name: null,
  description: "Weekly report",
  scheduled_task_id: "task-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("listFleetTemplates", () => {
  test("returns the template catalog on 200", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { templates: [TEMPLATE] }),
    );
    const result = await listFleetTemplates();
    expect(result).toEqual([TEMPLATE]);
    expect(mockedFetch.mock.calls[0]?.[0]).toBe("/api/fleet/templates");
  });

  test("surfaces the backend detail on failure", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(500, { detail: "Fleet template 'x' failed validation" }),
    );
    await expect(listFleetTemplates()).rejects.toThrow(
      "Fleet template 'x' failed validation",
    );
  });

  test("falls back to a generic message with no backend detail", async () => {
    mockedFetch.mockResolvedValueOnce(new Response("", { status: 500 }));
    await expect(listFleetTemplates()).rejects.toThrow(
      "Failed to load fleet templates.",
    );
  });
});

describe("listClientAgents", () => {
  test("returns the client's stamped agents on 200", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { agents: [BINDING] }));
    const result = await listClientAgents("client-1");
    expect(result).toEqual([BINDING]);
    expect(mockedFetch.mock.calls[0]?.[0]).toBe("/api/clients/client-1/agents");
  });

  test("surfaces a 404 as an error", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(404, { detail: "Client not found" }),
    );
    await expect(listClientAgents("does-not-exist")).rejects.toThrow(
      "Client not found",
    );
  });
});

describe("stampClientAgent", () => {
  test("posts the template id and returns the stamped binding", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(201, BINDING));

    const result = await stampClientAgent("client-1", "weekly-client-report");

    expect(result).toEqual(BINDING);
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("/api/clients/client-1/agents");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      template_id: "weekly-client-report",
    });
  });

  test("returns the existing binding on an idempotent 200", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, BINDING));
    const result = await stampClientAgent("client-1", "weekly-client-report");
    expect(result).toEqual(BINDING);
  });

  test("surfaces a 403 authorization error", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail:
          "Only an organization admin or someone assigned to this client can stamp an agent.",
      }),
    );
    await expect(
      stampClientAgent("client-1", "weekly-client-report"),
    ).rejects.toThrow(/organization admin/);
  });
});
