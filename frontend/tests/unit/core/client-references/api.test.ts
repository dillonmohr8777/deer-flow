import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  listClientReferenceDocuments,
  listClientReferenceProjects,
  urlOfClientReferenceContent,
} from "@/core/client-references/api";

const mockedFetch = rs.mocked(fetcher);
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("explicit client reference reads", () => {
  it("uses only the scoped project projection with no-store GET", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          projects: [{ id: "p", name: "Reference", status: "active" }],
        }),
        { status: 200 },
      ),
    );
    await expect(listClientReferenceProjects()).resolves.toEqual([
      { id: "p", name: "Reference", status: "active" },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/client-references/projects",
      { method: "GET", cache: "no-store" },
    );
  });

  it("reads approved document metadata through the scoped surface", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ documents: [], total: 0, limit: 100, offset: 0 }),
        { status: 200 },
      ),
    );
    await expect(
      listClientReferenceDocuments("own-project"),
    ).resolves.toMatchObject({ documents: [], total: 0 });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/client-references/projects/own-project/documents",
      { method: "GET", cache: "no-store" },
    );
  });

  it("does not fall back to staff project APIs after a refusal", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("private server details", { status: 403 }),
    );
    await expect(listClientReferenceProjects()).rejects.toThrow(
      "References are unavailable for this account.",
    );
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it("encodes each content identifier and links only to original attachments", () => {
    expect(urlOfClientReferenceContent("project/name", "doc?key=value")).toBe(
      "/backend/api/client-references/projects/project%2Fname/documents/doc%3Fkey%3Dvalue/content?download=true",
    );
  });
});
