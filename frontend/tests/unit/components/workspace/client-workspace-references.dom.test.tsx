import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import {
  ClientProjectReference,
  ClientProjectList,
  ClientScheduleList,
} from "@/components/workspace/client-workspace-references";
const state = rs.hoisted(() => ({
  kind: "projects",
  error: false,
  keys: [] as string[],
}));
rs.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: string[] }) => {
    state.keys.push(options.queryKey.join("/"));
    return {
      isPending: false,
      isError: state.error,
      data:
        state.kind === "projects"
          ? [{ id: "own-project", name: "Reference list" }]
          : state.kind === "documents"
            ? {
                documents: [
                  {
                    id: "document1",
                    name: "Homes.txt",
                    content_missing: false,
                  },
                ],
                total: 1,
              }
            : [
                {
                  id: "task1",
                  title: "Weekly update",
                  status: "paused",
                  next_run_at: null,
                },
              ],
    };
  },
}));
rs.mock("@/core/client-references/api", () => ({
  listClientReferenceProjects: rs.fn(),
  listClientReferenceDocuments: rs.fn(),
  urlOfClientReferenceContent: () =>
    "/api/client-references/projects/own-project/documents/document1/content?download=true",
}));
rs.mock("@/core/scheduled-tasks/api", () => ({
  fetchScheduledTaskStatuses: rs.fn(),
}));
afterEach(() => {
  cleanup();
  state.kind = "projects";
  state.error = false;
  state.keys = [];
});
describe("client workspace references", () => {
  it("links only the returned workspace projects without management controls", () => {
    const { container } = render(<ClientProjectList />);
    expect(
      screen.getByRole("link", { name: "Reference list" }).getAttribute("href"),
    ).toBe("/workspace/projects/own-project");
    expect(container.querySelector("button,input,textarea,form")).toBeNull();
  });
  it("offers document download without chats, uploads or edits", () => {
    state.kind = "documents";
    const { container } = render(
      <ClientProjectReference projectId="own-project" />,
    );
    expect(
      screen.getByRole("link", { name: "Homes.txt" }).getAttribute("href"),
    ).toContain("/api/client-references/projects/own-project/documents/");
    expect(container.querySelector("button,input,textarea,form")).toBeNull();
    expect(state.keys).toEqual(["client-reference-documents/own-project"]);
  });
  it("shows task state without execution or history controls", () => {
    state.kind = "tasks";
    const { container } = render(<ClientScheduleList />);
    expect(screen.getByText("Weekly update")).toBeTruthy();
    expect(screen.getByText(/paused/)).toBeTruthy();
    expect(container.querySelector("button,input,textarea,form,a")).toBeNull();
  });
  it("shows unavailable instead of claiming a disabled scheduler is active", () => {
    state.error = true;
    render(<ClientScheduleList />);
    expect(screen.getByRole("alert").textContent).toContain("unavailable");
  });
});
